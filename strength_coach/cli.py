"""The command line: the v0 slice, plus the calibration loop.

    strength-coach import
    strength-coach run --date 2026-10-20 [--llm on]
    strength-coach review --session 2026-10-15
    strength-coach calibrate

`run` is docs/V0-SCOPE.md section 1: ingest if needed, critique the most recent session,
prescribe the requested day, persist both inside a run trace, and print a rationale that
cites a rule or a stored fact for every number.

`review` is the calibration loop: it shows the session next to the rubric's scores, takes your
marks, stores them append-only, and immediately reports running agreement. Calibration is
therefore continuous -- every review is another data point -- rather than a one-off audit.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import yaml

from strength_coach import __version__, workout
from strength_coach.agents import (
    LLMError,
    build_client,
    explain_critique,
    explain_prescription,
    load_settings,
)
from strength_coach.agents import proposal as proposal_mod
from strength_coach.agents import selection as agent_selection
from strength_coach.critique import UnknownSessionError, build_facts, score_session
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.features import cardio as cardio_feature
from strength_coach.features import continuity_calibration
from strength_coach.features import volume as volume_feature
from strength_coach.features import e1rm_calibration as e1rm_calibration_feature
from strength_coach.features import fatigue_fitness as fatigue_fitness_feature
from strength_coach.features import measurements as measurements_feature
from strength_coach.features import session_feedback as session_feedback_feature
from strength_coach.features import heavy_spinal
from strength_coach.features import high_intensity_exposure as exposure_feature
from strength_coach.features import outcomes as outcomes_feature
from strength_coach.features import prospective as prospective_feature
from strength_coach.features import readiness_feedback
from strength_coach.features import prescription_provenance
from strength_coach.features import injury_signal as injury_signal_mod
from strength_coach.features import readiness as readiness_feature
from strength_coach.features import readiness_baseline
from strength_coach.features import retrospective_validation
from strength_coach.features import programme as programme_feature
from strength_coach.features import deload as deload_feature
from strength_coach.features import readiness_score
from strength_coach.utils import readiness as readiness_utils

READINESS_CLI_FIELDS = {field: field for field in readiness_utils.INPUT_SCORE_FIELDS}
READINESS_CLI_FIELDS.update({field: field for field in readiness_utils.MEASURE_FIELDS})
from strength_coach.critique import persist as persist_critique
from strength_coach.critique.rubric import RUBRIC_VERSION
from strength_coach.eval import backtest, load_marks, record_marks
from strength_coach.eval.report import format_report, format_session_sheet, item_guide_lines
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe import deload as deload_mod
from strength_coach.prescribe import schedule as schedule_mod
from strength_coach.prescribe import selection as selection_mod
from strength_coach.prescribe import config as prescribe_config
from strength_coach.prescribe import schemes as schemes_mod
from strength_coach.rules import RuleContext, evaluate, load_document
from strength_coach.store import db, exercise_admin, importer, queries, repositories
from strength_coach.trace import RunTrace
from strength_coach.utils import io_utils, paths

DEFAULT_TOLERANCE = 0.25


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="strength-coach", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--db", default=None, help="database path (default: data/coach.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("import", help="load data/raw into the store")

    run = sub.add_parser("run", help="critique the last session and prescribe a date")
    run.add_argument("--date", required=True, help="date to prescribe, YYYY-MM-DD")
    run.add_argument("--session-type", choices=("auto", "squat", "hinge", "bench_squat", "bench_hinge"),
                     default="auto", help="session emphasis (default: auto rolling)")
    run.add_argument("--llm", choices=("on", "off"), default="off",
                     help="ask the configured model for a narrative (default: off)")
    run.add_argument("--force", action="store_true",
                     help="regenerate even if this date was already prescribed")
    run.add_argument("--deload", choices=("ask", "yes", "no"), default="ask",
                     help="scheduled deload: ask (interactive, default no), yes, or no")
    run.add_argument("--propose", action="store_true",
                     help="ask the model for a structural proposal (requires --llm on)")
    run.add_argument("--apply-selection", action="store_true",
                     help="apply the shadow selector's exercise substitutions")
    run.add_argument("--selection-llm", action="store_true",
                     help="let the model choose among the filtered candidates (requires --apply-selection)")
    run.add_argument("--selection-confirm", action="store_true",
                     help="confirm a near-comparable (class B) substitution; class C is never automatic")
    run.add_argument("--yes", action="store_true",
                     help="apply an accepted proposal without asking")
    run.add_argument("--minimum-session", action="store_true",
                     help="user-selected volume-only minimum session (MOD-MIN-001)")
    run.add_argument("--target-minutes", type=int, choices=(30, 45, 60), default=None,
                     help="minimum-session target; default from config (45)")
    run.add_argument("--minimum-include-main", action="store_true",
                     help="deeper tier: also reduce main-lift sets to the floor")

    review = sub.add_parser("review", help="mark a session and update calibration")
    review.add_argument("--session", default=None, help="session id (YYYY-MM-DD)")
    review.add_argument("--pending", action="store_true",
                        help="review unreviewed sessions after the last reviewed one, oldest first")
    review.add_argument("--limit", type=int, default=10,
                        help="maximum sessions for --pending (default 10)")
    review.add_argument("--scores", default=None, help="read marks from a YAML file")
    review.add_argument("--confidence", choices=("high", "low", "unknown"), default=None)
    review.add_argument("--note", default=None)
    review.add_argument("--session-rpe", type=float, default=None,
                        help="optional session RPE 1-10 (also asked interactively at review)")
    review.add_argument("--session-minutes", type=float, default=None,
                        help="optional session length in minutes")

    calibrate = sub.add_parser("calibrate", help="report agreement between rubric and marks")
    calibrate.add_argument("--tolerance", type=float, default=None)

    state = sub.add_parser("state", help="show or import athlete state (goals, limits, suitability)")
    state.add_argument("--import", dest="import_file", default=None,
                       help="YAML file of athlete state to record")
    state.add_argument("--force", action="store_true",
                       help="append a new version even if state is already recorded")
    state.add_argument("--rate", metavar="EXERCISE", default=None,
                       help="record a suitability rating for one exercise")
    state.add_argument("--can-do", choices=("yes", "no"), default="yes")
    state.add_argument("--will-do", choices=("yes", "no"), default="yes")
    state.add_argument("--feels-bad", choices=("yes", "no"), default="no")
    state.add_argument("--note", default=None)

    programme = sub.add_parser("programme", help="forecast a rolling A/B/C horizon")
    programme.add_argument("--weeks", type=int, required=True)
    programme.add_argument("--remaining", action="store_true",
                           help="start today instead of the block anchor")
    programme.add_argument("--start", default=None, help="YYYY-MM-DD")
    programme.add_argument("--sessions-per-week", type=int, choices=(1, 2, 3), default=3)
    programme.add_argument("--start-session-type",
                           choices=("auto", "squat", "hinge", "bench_squat", "bench_hinge"),
                           default=None,
                           help="first session type; default: rolling")

    e1rm = sub.add_parser("e1rm", help="set or list manual e1RM overrides")
    e1rm_sub = e1rm.add_subparsers(dest="action", required=True)
    setter = e1rm_sub.add_parser("set", help="override the e1RM for one lift")
    setter.add_argument("--exercise", required=True, help="canonical exercise id")
    setter.add_argument("--kg", type=float, required=True, help="e1RM in kg")
    setter.add_argument("--from", dest="effective_from", default=None,
                        help="YYYY-MM-DD (default: today)")
    setter.add_argument("--until", dest="expires_on", default=None,
                        help="YYYY-MM-DD; omit for no expiry")
    setter.add_argument("--reason", default=None, help="why this override exists")
    e1rm_sub.add_parser("list", help="show recorded overrides")
    e1rm_cal = e1rm_sub.add_parser(
        "calibrate", help="compare measured tests with the formula estimate (report only)"
    )
    e1rm_cal.add_argument("--window-days", type=int, default=84,
                          help="look-back window before each test (default 84)")

    test = sub.add_parser("test", help="record a 3RM/5RM (or confirmed 1RM) strength test")
    test.add_argument("--status", action="store_true",
                      help="show the 3RM/5RM cadence instead of recording a test")
    test.add_argument("--exercise", help="canonical exercise id")
    test.add_argument("--kg", type=float, default=None, help="load used for the test")
    test.add_argument("--reps", type=int, default=None,
                      help="reps completed (3-5 recommended; 1 is a true 1RM and needs --max)")
    test.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    test.add_argument("--e1rm", type=float, default=None,
                      help="record this e1RM instead of the computed estimate")
    test.add_argument("--max", action="store_true",
                      help="declare a true 1RM test; requires confirmation and is rate-limited")
    test.add_argument("--yes", action="store_true",
                      help="skip the confirmation prompt (the value is printed first)")
    test.add_argument("--force", action="store_true",
                      help="allow a 1RM test inside the minimum interval")
    test.add_argument("--reason", default=None, help="optional note stored with the override")

    symptom = sub.add_parser("symptom", help="log or show a symptom reading for one region")
    symptom.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    symptom.add_argument("--region", default=None,
                         help="injury region (logging defaults to low_back; "
                              "--show defaults to all regions)")
    symptom.add_argument("--level", type=int, choices=(0, 1, 2, 3), default=None,
                         help="0 none, 1 awareness, 2 annoying, 3 limiting")
    symptom.add_argument("--settled", choices=("yes", "no", "unknown"), default=None,
                         help="did it settle within 48 hours?")
    symptom.add_argument("--note", default=None)
    symptom.add_argument("--show", action="store_true", help="list recent entries")

    exercise = sub.add_parser("exercise", help="list or edit the exercise catalogue")
    exercise_sub = exercise.add_subparsers(dest="action", required=True)
    exercise_sub.add_parser("list", help="list canonical exercises and their source")
    editor = exercise_sub.add_parser("set", help="edit or add one exercise from JSON")
    editor.add_argument("--id", required=True, help="lower_snake_case canonical id")
    editor.add_argument("--json", required=True, dest="props_json",
                        help='JSON object of properties, e.g. {"pattern":"squat"}')

    readiness = sub.add_parser("readiness", help="record a readiness day")
    readiness.add_argument("action", choices=("set", "override", "calibrate", "settings", "shadow", "preset", "context", "feedback"))
    readiness.add_argument("--weeks", type=int, default=12)
    readiness.add_argument("--name", default=None, help="readiness preset key")
    readiness.add_argument("--flags", default=None,
                           help="comma-separated context flags; empty shows current flags")
    readiness.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    readiness.add_argument("--sleep", type=int, default=None)
    readiness.add_argument("--energy", type=int, default=None)
    readiness.add_argument("--mood", type=int, default=None)
    readiness.add_argument("--soreness", type=int, default=None)
    readiness.add_argument("--stress", type=int, default=None)
    readiness.add_argument("--nutrition", type=int, default=None)
    readiness.add_argument("--hydration", type=int, default=None)
    readiness.add_argument("--hrv", dest="hrv_ms", type=float, default=None)
    readiness.add_argument("--rhr", dest="rhr_bpm", type=float, default=None)
    readiness.add_argument("--bodyweight", dest="bodyweight_kg", type=float, default=None)
    readiness.add_argument("--fat-percent", dest="fat_pct", type=float, default=None)
    readiness.add_argument("--wearable-score", dest="wearable_score", type=float,
                           default=None, help="third-party readiness score, 0-100")
    readiness.add_argument("--note", default=None)
    readiness.add_argument("--scope", default="global",
                           help="override scope: global or category:<name>")
    readiness.add_argument("--value", type=float, default=None,
                           help="override value 0.00-1.00 (same scale as the score)")
    readiness.add_argument("--reason", default=None,
                           help="why the computed score is overridden")
    readiness.add_argument("--baseline-days", type=int, default=None,
                           help="baseline window in days (athlete setting)")
    readiness.add_argument("--baseline-min-readings", type=int, default=None,
                           help="minimum baseline readings (athlete setting)")
    readiness.add_argument("--hrv-slope", type=float, default=None,
                           help="HRV ratio half-width, e.g. 0.5")
    readiness.add_argument("--rhr-slope", type=float, default=None,
                           help="RHR ratio half-width, e.g. 0.5")
    readiness.add_argument("--hrv-weight", type=float, default=None)
    readiness.add_argument("--rhr-weight", type=float, default=None)
    readiness.add_argument("--wearable-weight", type=float, default=None)
    readiness.add_argument("--setting-note", default=None)

    cardio = sub.add_parser("cardio", help="log or summarise cardio sessions")
    cardio.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    cardio.add_argument("--modality", default=None,
                        help="e.g. walk, run, bike, row, intervals, swim")
    cardio.add_argument("--minutes", type=float, default=None, help="session duration")
    cardio.add_argument("--avg-hr", type=int, default=None, help="average heart rate")
    cardio.add_argument("--max-hr", type=int, default=None, help="maximum heart rate")
    cardio.add_argument("--distance-km", type=float, default=None)
    cardio.add_argument("--srpe", type=int, default=None, help="session RPE, 1-10")
    cardio.add_argument("--note", default=None)
    cardio.add_argument("--show", action="store_true", help="show the summary")
    cardio.add_argument("--weeks", type=int, default=12,
                        help="summary window in weeks (default 12)")

    workout_parser = sub.add_parser("workout", help="inspect or finish the active live workout")
    workout_sub = workout_parser.add_subparsers(dest="action", required=True)
    workout_sub.add_parser("status", help="show the active workout")
    ws = workout_sub.add_parser("add-set", help="add a manual set to the active workout")
    ws.add_argument("--exercise", required=True)
    ws.add_argument("--load", type=float, default=None)
    ws.add_argument("--reps", type=int, default=None)
    ws.add_argument("--rir", type=int, default=None)
    ws.add_argument("--velocity", type=float, default=None)
    wu = workout_sub.add_parser("update-set", help="correct an actual set")
    wu.add_argument("--set-id", type=int, required=True)
    wu.add_argument("--load", type=float, default=None)
    wu.add_argument("--reps", type=int, default=None)
    wu.add_argument("--rir", type=int, default=None)
    wu.add_argument("--velocity", type=float, default=None)
    wr = workout_sub.add_parser("remove-set", help="remove an actual set")
    wr.add_argument("--set-id", type=int, required=True)
    we = workout_sub.add_parser("end", help="end the active workout")
    we.add_argument("--session-rpe", type=float, default=None)
    we.add_argument("--duration-min", type=float, default=None)
    we.add_argument("--not-recorded", action="store_true")
    we.add_argument("--note", default=None)
    workout_sub.add_parser("abandon", help="abandon the active workout")
    wi = workout_sub.add_parser("import", help="preview/apply the workout CSV to the active workout")
    wi.add_argument("--file", required=True)
    wi.add_argument("--apply", action="store_true")

    validate = sub.add_parser("validate", help="retrospective walk-forward model checks")
    validate.add_argument("--max-dates", type=int, default=12,
                          help="number of evaluation dates (default 12)")

    select = sub.add_parser("select", help="show shadow exercise-selection suggestions")
    select.add_argument("--date", required=True, help="YYYY-MM-DD")
    select.add_argument("--session-type", required=True,
                        choices=("squat", "hinge", "bench_squat", "bench_hinge"))
    select.add_argument("--include-different", action="store_true",
                        help="show class C (different lift/load basis) candidates")
    select.add_argument("--llm", action="store_true",
                        help="let the configured model choose from the filtered candidates")

    exposure = sub.add_parser("exposure", help="log or inspect high-intensity exposures")
    exposure_sub = exposure.add_subparsers(dest="action", required=True)
    exposure_log = exposure_sub.add_parser("log", help="record a non-test exposure")
    exposure_log.add_argument("--date", required=True)
    exposure_log.add_argument("--kind", choices=("max_attempt", "competition", "unplanned", "other"),
                              required=True)
    exposure_log.add_argument("--region", choices=("upper", "lower", "axial", "mixed", "unknown"),
                              required=True)
    exposure_log.add_argument("--exercise", default=None)
    exposure_log.add_argument("--intensity", choices=("near_max", "high", "moderate", "unknown"),
                              default="near_max")
    exposure_log.add_argument("--axial-cost", type=int, default=None)
    exposure_log.add_argument("--note", default=None)
    exposure_status = exposure_sub.add_parser("status", help="show the recovery guard")
    exposure_status.add_argument("--date", default=None)

    outcomes = sub.add_parser("outcomes", help="descriptive 4/8/12-week outcome review")
    outcomes.add_argument("--weeks", type=int, choices=(4, 8, 12), default=8)
    outcomes.add_argument("--date", default=None)
    outcomes.add_argument("--json", action="store_true")

    prospective = sub.add_parser("prospective", help="W5 read-only prospective review")
    prospective.add_argument("--weeks", type=int, choices=(4, 8, 12), default=8)
    prospective.add_argument("--date", default=None)
    prospective.add_argument("--json", action="store_true")

    volume = sub.add_parser("volume", help="show weekly hard-set volume by movement pattern")
    volume.add_argument("--weeks", type=int, default=4)
    volume.add_argument("--date", default=None, help="as-of date (default: today)")

    continuity = sub.add_parser("continuity", help="show or configure return-to-training calibration")
    continuity.add_argument("--date", default=None, help="as-of date (default: today)")
    continuity.add_argument("--allow-relax-fixed", choices=("on", "off"), default=None,
                            help="allow calibrated bands to relax the fixed reduction")

    fatigue = sub.add_parser("fatigue", help="show the strength fitness-fatigue shadow model")
    fatigue.add_argument("--date", default=None, help="as-of date (default: today)")

    measure = sub.add_parser("measure", help="log or show periodic measurements")
    measure.add_argument("--metric", default=None,
                         help="e.g. vo2max, grip_strength_kg, sit_to_stand_5_s, steps_per_day")
    measure.add_argument("--value", type=float, default=None)
    measure.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    measure.add_argument("--method", default=None,
                         help="protocol or device, e.g. 'step test' or 'hand dynamometer'")
    measure.add_argument("--note", default=None)
    measure.add_argument("--show", action="store_true", help="show the summary")

    web = sub.add_parser("web", help="serve the local web UI (127.0.0.1 only)")
    web.add_argument("--host", default="127.0.0.1",
                     help="bind address (default 127.0.0.1; no authentication)")
    web.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    web.add_argument("--open", action="store_true", help="open a browser")

    block = sub.add_parser("block", help="declare or reset the block start (week 1)")
    block.add_argument("--date", required=True, help="YYYY-MM-DD")
    block.add_argument("--force", action="store_true",
                       help="reset even if the ramp is already running")

    args = parser.parse_args(argv)
    handlers = {
        "import": _cmd_import,
        "run": _cmd_run,
        "programme": _cmd_programme,
        "review": _cmd_review,
        "calibrate": _cmd_calibrate,
        "state": _cmd_state,
        "e1rm": _cmd_e1rm,
        "test": _cmd_test,
        "symptom": _cmd_symptom,
        "cardio": _cmd_cardio,
        "measure": _cmd_measure,
        "volume": _cmd_volume,
        "continuity": _cmd_continuity,
        "fatigue": _cmd_fatigue,
        "select": _cmd_select,
        "exposure": _cmd_exposure,
        "outcomes": _cmd_outcomes,
        "prospective": _cmd_prospective,
        "validate": _cmd_validate,
        "workout": _cmd_workout,
        "exercise": _cmd_exercise,
        "block": _cmd_block,
        "readiness": _cmd_readiness,
        "web": _cmd_web,
    }
    try:
        return handlers[args.command](args)
    except UnknownSessionError as exc:
        print(f"session: {exc}")
        return 2


# --- commands --------------------------------------------------------------


def _cmd_import(args) -> int:
    store = db.Store(args.db)
    try:
        report = _import_export(store.connection)
    finally:
        store.close()
    _print_import(report)
    return 0


def _cmd_run(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        _ensure_imported(conn)

        # Readiness is required for a current/future workout: the score is part of the
        # prescription, not an optional afterthought. Historical dates stay reproducible.
        if args.date >= datetime.date.today().isoformat():
            assessment = readiness_score.compute(conn, args.date)
            if assessment.status != "ready":
                print(f"readiness required for {args.date}: {assessment.status} — "
                      f"{assessment.basis}")
                print("record it with 'strength-coach readiness set ...' (or the web form)")
                return 2

        # V0-SCOPE §4.6: re-running the same run must append no duplicate artifacts.
        existing = conn.execute(
            "SELECT prescription_id FROM prescription WHERE for_date = ? ORDER BY created_at DESC",
            (args.date,),
        ).fetchone()
        if existing is not None and not args.force:
            print(f"already prescribed for {args.date} "
                  f"(prescription {existing['prescription_id'][:8]}); use --force to regenerate")
            return 0

        sessions = queries.sessions(conn, end=args.date)
        if sessions.empty:
            print(f"no stored session on or before {args.date}")
            return 2
        session_id = str(sessions.iloc[-1]["session_id"])

        facts = build_facts(conn, session_id)
        critique = score_session(conn, session_id, facts=facts)
        if args.minimum_include_main and not args.minimum_session:
            print("--minimum-include-main requires --minimum-session")
            return 2
        if args.selection_llm and not args.apply_selection:
            print("--selection-llm requires --apply-selection")
            return 2
        if args.selection_confirm and not args.apply_selection:
            print("--selection-confirm requires --apply-selection")
            return 2
        session_type = (
            schedule_mod.next_session_type(conn, args.date)
            if args.session_type == "auto" else args.session_type
        )
        chooser = (
            agent_selection.chooser(build_client(load_settings()))
            if args.selection_llm else None
        )
        # Resolve deload before building: the engine must apply it before minimum session and
        # final validation, not after validation.
        reactive = deload_feature.reactive_decision(conn, args.date)
        scheduled = deload_feature.scheduled_decision(conn, args.date)
        deload_decision = None
        scheduled_suggestion = None
        if reactive is not None:
            # Reactive safety trigger: always applied, even when a scheduled suggestion
            # was also due.
            deload_decision = reactive
            print(f"deload applied: {reactive.reason}")
        elif scheduled is not None:
            confirmed = False
            if args.deload == "yes":
                confirmed = True
            elif args.deload == "ask" and sys.stdin.isatty():
                print(f"deload suggested: {scheduled.reason}")
                answer = input("Apply deload for this workout? [y/N] ").strip().lower()
                confirmed = answer in {"y", "yes"}
            if confirmed:
                deload_decision = scheduled
                print(f"deload applied: {scheduled.reason}")
            else:
                scheduled_suggestion = scheduled
                if args.deload == "ask" and not sys.stdin.isatty():
                    print("deload suggested; non-interactive run trains as planned "
                          "(use --deload yes to apply)")
        prescription = build_prescription(
            conn, for_date=args.date, session_type=session_type,
            apply_selection=args.apply_selection, selection_chooser=chooser,
            selection_confirmed=args.selection_confirm,
            minimum_session=args.minimum_session,
            minimum_target_minutes=args.target_minutes,
            minimum_include_main=args.minimum_include_main,
            deload_decision=deload_decision,
        )
        if scheduled_suggestion is not None:
            prescription = deload_mod.suggest(prescription, scheduled_suggestion)

        with RunTrace.start(conn, input_hash=f"{session_id}:{args.date}",
                            window_end=args.date) as trace:
            critique_id = persist_critique(conn, critique, run_id=trace.run_id)
            approved_by = "deterministic"
            if args.propose:
                if args.llm != "on":
                    print("--propose requires --llm on")
                    return 2
                prescription, approved_by = _propose(conn, trace, prescription, args)
            prescription_id = repositories.append_prescription(
                conn,
                prescription_id=_new_id(),
                run_id=trace.run_id,
                for_date=prescription.for_date,
                session_type=prescription.session_type,
                fallback_level=prescription.fallback_level,
                rule_document_version=prescription.rule_document_version,
                calibration_ids=list(prescription.calibration_ids),
                approved_by=approved_by,
                items=prescription.as_rows(),
            )
            prescription_provenance.record(conn, prescription_id, prescription)
            trace.event("artifact", {
                "critique": critique_id,
                "prescription": prescription_id,
            })
            if args.llm == "on":
                _narrate(conn, trace, critique, facts, prescription)

        _print_prescription(prescription)
        _print_critique(critique)
        pending = queries.unreviewed_sessions(conn, limit=100)
        if pending:
            print(f"\n{len(pending)} unreviewed session(s); run "
                  "'strength-coach review --pending' to catch up")
        return 0
    finally:
        store.close()


def _cmd_review(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        _ensure_imported(conn)

        if args.pending:
            sessions = queries.unreviewed_sessions(conn, limit=args.limit)
            if not sessions:
                print("no unreviewed sessions")
                return 0
            print(f"reviewing {len(sessions)} unreviewed session(s)")
            reviewed = 0
            for session_id in sessions:
                if _review_one(conn, session_id, args) == 0:
                    reviewed += 1
            if reviewed:
                _print_calibration(conn, DEFAULT_TOLERANCE)
            return 0

        if not args.session:
            print("pass --session DATE, or --pending to catch up on unreviewed sessions")
            return 2
        code = _review_one(conn, args.session, args)
        if code == 0:
            _print_calibration(conn, DEFAULT_TOLERANCE)
        return code
    finally:
        store.close()


def _review_one(conn, session_id: str, args) -> int:
    facts = build_facts(conn, session_id)
    critique = score_session(conn, session_id, facts=facts)

    print(format_session_sheet(facts, critique))
    for line in item_guide_lines():
        print(line)

    if args.scores:
        from strength_coach.eval import load_labels

        labels = load_labels(args.scores)
        if session_id not in labels.sessions:
            print(f"{args.scores} has no marks for {session_id}; skipped")
            return 2
        scores = dict(labels.sessions[session_id].scores)
        confidence = args.confidence or labels.sessions[session_id].confidence
    else:
        scores = _ask_scores(critique)
        confidence = args.confidence or _ask_confidence()

    feedback = _collect_session_feedback(args)
    stored_feedback = None
    if feedback:
        try:
            stored_feedback = session_feedback_feature.record(conn, session_id, **feedback)
        except ValueError as exc:
            print(f"session detail: {exc}")
            return 2
        if stored_feedback:
            print(_format_session_feedback(stored_feedback))

    written = record_marks(
        conn,
        session_id,
        scores,
        confidence=confidence,
        rubric_version=RUBRIC_VERSION,
        note=args.note,
    )
    if written == 0:
        print("\nno marks recorded: every item was skipped. This session is still "
              "unreviewed.")
        if stored_feedback:
            print("session detail was saved; review again to add marks.")
        return 2
    print(f"\nrecorded {written} marks for {session_id} (confidence {confidence})")
    return 0


def _collect_session_feedback(args) -> dict | None:
    """Optional session RPE/length: flags first, then a skippable prompt.

    A file-based review (`--scores`) stays non-interactive; flags still work there. The prompt
    is only for the interactive path, because these fields are useful but never required.
    """
    if args.session_rpe is not None or args.session_minutes is not None:
        return {
            key: value for key, value in {
                "srpe": args.session_rpe,
                "duration_min": args.session_minutes,
            }.items() if value is not None
        }
    if args.scores:
        return None

    print("\noptional session detail (Enter to skip)")
    srpe = _ask_optional_number("  session RPE 1-10: ", 1, 10)
    minutes = _ask_optional_number("  session length minutes: ", 1, 600)
    values = {"srpe": srpe, "duration_min": minutes}
    return {key: value for key, value in values.items() if value is not None} or None


def _ask_optional_number(prompt: str, low: float, high: float) -> float | None:
    raw = input(prompt).strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        print("  skipped (not a number)")
        return None
    if not low <= value <= high:
        print(f"  skipped (outside {low:g}-{high:g})")
        return None
    return value


def _format_session_feedback(feedback: dict) -> str:
    pieces = []
    if feedback.get("srpe") is not None:
        pieces.append(f"RPE {feedback['srpe']:g}")
    if feedback.get("duration_min") is not None:
        pieces.append(f"{feedback['duration_min']:g} min")
    return "session detail: " + ", ".join(pieces)


def _cmd_calibrate(args) -> int:
    if args.db is None and not paths.data_dir("coach.db").exists():
        print("no database yet; run 'strength-coach import' first")
        return 2
    store = db.Store(args.db)
    try:
        labels = load_marks(store.connection)
        if not labels.sessions:
            print("no marks yet; run 'strength-coach review --session DATE' first")
            return 2
        report = backtest(
            store.connection, labels,
            tolerance=args.tolerance if args.tolerance is not None else DEFAULT_TOLERANCE,
        )
        print(format_report(report))
        return 0
    finally:
        store.close()


def _cmd_state(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        if args.import_file and args.rate:
            print("use either --import or --rate, not both")
            return 2
        if args.rate:
            repositories.append_exercise_suitability(
                conn,
                exercise_id=args.rate,
                rated_on=datetime.date.today().isoformat(),
                can_do=args.can_do == "yes",
                will_do=args.will_do == "yes",
                feels_bad=args.feels_bad == "yes",
                note=args.note,
            )
            print(f"rated {args.rate}: can_do={args.can_do}, will_do={args.will_do}, "
                  f"feels_bad={args.feels_bad}")
        if args.import_file:
            if code := _import_state(conn, Path(args.import_file), force=args.force):
                return code
        _print_state(conn)
        return 0
    finally:
        store.close()


def _record_readiness(conn, on_date: str, values: dict[str, float],
                      note: str | None = None) -> int:
    return readiness_feature.record_manual(conn, on_date, values, note=note)


def _cmd_readiness(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        if args.action == "calibrate":
            from strength_coach.features import readiness_calibration

            print(readiness_calibration.report(conn))
            return 0
        if args.action == "shadow":
            print(readiness_baseline.report(conn, end=args.date))
            return 0
        args.date = args.date or datetime.date.today().isoformat()
        if args.action == "feedback":
            report = readiness_feedback.report(conn, weeks=args.weeks, on_date=args.date)
            window = report["window"]
            print(f"readiness feedback: {window['from']} to {window['to']} "
                  f"({window['weeks']} weeks)")
            print(f"events: {report['aggregate']['n_events']}")
            for event in report["events"]:
                print(f"  {event['applied_on']} -> {event['next_session_on'] or 'no next session'}"
                      f"  e1RM {event['e1rm_before']} -> {event['e1rm_after']}"
                      f"  sRPE {event['next'].get('srpe')}"
                      f"  RIR {event['next'].get('rir_adherence')}"
                      f"  flare {event['symptom_flare_7d']}")
            print(f"aggregate: {report['aggregate']}")
            for warning in report["warnings"]:
                print(f"  ! {warning}")
            print(report["note"])
            return 0
        if args.action == "preset":
            if not args.name:
                print("readiness preset: --name is required")
                return 2
            try:
                readiness_feature.record_preset(conn, args.date, args.name, note=args.note)
            except ValueError as exc:
                print(f"readiness preset: {exc}")
                return 2
            print(f"readiness preset {args.name} recorded on {args.date}")
            _print_readiness_score(readiness_score.compute(conn, args.date))
            return 0
        if args.action == "context":
            flags = [flag.strip() for flag in (args.flags or "").split(",") if flag.strip()]
            if flags:
                try:
                    readiness_feature.record_context(conn, args.date, flags, note=args.note)
                except ValueError as exc:
                    print(f"readiness context: {exc}")
                    return 2
                print(f"readiness context recorded on {args.date}: {', '.join(flags)}")
            else:
                current = queries.readiness_context(conn, args.date)
                print(f"readiness context {args.date}: {', '.join(current) or 'none'}")
            _print_readiness_score(readiness_score.compute(conn, args.date))
            return 0
        if args.action == "settings":
            effective = readiness_score.effective_settings(conn, args.date)
            supplied = {
                "baseline_days": args.baseline_days,
                "baseline_min_readings": args.baseline_min_readings,
                "hrv_slope": args.hrv_slope,
                "rhr_slope": args.rhr_slope,
                "hrv_weight": args.hrv_weight,
                "rhr_weight": args.rhr_weight,
                "wearable_weight": args.wearable_weight,
            }
            if any(value is not None for value in supplied.values()):
                values = {
                    key: value if value is not None else getattr(effective, key)
                    for key, value in supplied.items()
                }
                try:
                    repositories.append_readiness_setting(
                        conn, effective_from=args.date, note=args.setting_note, **values,
                    )
                except ValueError as exc:
                    print(f"readiness settings: {exc}")
                    return 2
                effective = readiness_score.effective_settings(conn, args.date)
                print(f"readiness settings recorded from {args.date}")
            print(f"baseline_days={effective.baseline_days} "
                  f"baseline_min_readings={effective.baseline_min_readings} "
                  f"hrv_slope={effective.hrv_slope:g} rhr_slope={effective.rhr_slope:g} "
                  f"weights hrv={effective.hrv_weight:g} rhr={effective.rhr_weight:g} "
                  f"wearable={effective.wearable_weight:g} ({effective.setting_source})")
            return 0
        args.date = args.date or datetime.date.today().isoformat()
        if args.action == "override":
            if args.value is None:
                print("readiness override: --value is required (0.00-1.00)")
                return 2
            if not args.reason:
                print("readiness override: --reason is required")
                return 2
            try:
                repositories.append_readiness_override(
                    conn, effective_on=args.date, scope=args.scope,
                    value=args.value, reason=args.reason,
                )
            except ValueError as exc:
                print(f"readiness override: {exc}")
                return 2
            print(f"readiness override {args.scope} = {args.value:.2f} on {args.date}")
            _print_readiness_score(readiness_score.compute(conn, args.date))
            return 0

        values = {
            field: getattr(args, attr)
            for field, attr in READINESS_CLI_FIELDS.items()
            if getattr(args, attr) is not None
        }
        try:
            _record_readiness(conn, args.date, values, note=args.note)
        except ValueError as exc:
            print(f"readiness: {exc}")
            return 2
        data = queries.readiness_day(conn, args.date)
        print(f"readiness {args.date}: recorded {len(values)} manual field(s)")
        if data:
            for field in (*readiness_utils.INPUT_SCORE_FIELDS, *readiness_utils.MEASURE_FIELDS):
                if data.get(field) is None:
                    continue
                source = (data.get("sources") or {}).get(field, "import")
                print(f"  {readiness_utils.FIELD_LABELS[field]:<20}"
                      f"{data[field]:>6g}  ({source})")
        print("manual values win per field; imported values fill the rest")
        _print_readiness_score(readiness_score.compute(conn, args.date))
        return 0
    finally:
        store.close()


def _print_readiness_score(assessment) -> None:
    print(f"\nreadiness score: {assessment.status}")
    if assessment.score is not None:
        print(f"  global {assessment.score:.2f} — {assessment.basis}")
    for component in assessment.components:
        print(f"  {component.field:<12} {component.value:g} -> {component.normalised:.2f}")
    for scope, row in sorted(assessment.overrides.items()):
        print(f"  override {scope:<18} {row['value']:.2f} ({row['reason']})")
    if assessment.category_scores:
        print("  categories " + ", ".join(
            f"{name}={value:.2f}" for name, value in assessment.category_scores.items()
        ))


def _cmd_programme(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        _ensure_imported(conn)
        start = args.start
        if args.remaining:
            start = datetime.date.today().isoformat()
        elif start is None:
            profile = queries.athlete_profile(conn)
            start = (profile or {}).get("block_start_date") or datetime.date.today().isoformat()
        entries = programme_feature.build_programme(
            conn, start=start, weeks=args.weeks,
            per_week=args.sessions_per_week,
            start_session_type=args.start_session_type,
        )
        print(f"programme: {args.weeks} week(s) from {start}; forecast only, "
              "recomputed on the day")
        print(f"{'date':<12}{'type':<14}{'status':<10}loads")
        for entry in entries:
            p = entry.prescription
            loads = ", ".join(
                f"{item.exercise_id}={item.load_kg:g}"
                for item in p.items if item.load_kg is not None
            ) or "no loads"
            status = "forecast" if p.executable else "not executable"
            if entry.deload_applied:
                status = "deload"
            elif entry.deload_suggestion:
                status = "suggested deload"
            print(f"{entry.on_date:<12}{entry.session_type:<14}{status:<10}{loads}")
            if entry.deload_reason:
                print(f"  reactive deload: {entry.deload_reason}")
            if entry.deload_suggestion:
                print(f"  scheduled deload suggested: {entry.deload_suggestion}")
            if p.warnings:
                print(f"  warnings: {len(p.warnings)} (the day's run will show them)")
        return 0
    finally:
        store.close()


def _cmd_web(args) -> int:
    from strength_coach.web.server import serve

    try:
        serve(args.db, host=args.host, port=args.port, open_browser=args.open)
    except OSError as exc:
        print(f"web: could not start on {args.host}:{args.port}: {exc}")
        return 2
    return 0


def _cmd_e1rm(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        if args.action == "list":
            _print_e1rm(conn)
            return 0
        if args.action == "calibrate":
            report = e1rm_calibration_feature.build(conn, window_days=args.window_days)
            _print_e1rm_calibration(report)
            return 0
        if args.kg <= 0:
            print("e1RM must be positive")
            return 2
        effective_from = args.effective_from or datetime.date.today().isoformat()
        repositories.append_e1rm_override(
            conn,
            exercise_id=args.exercise,
            e1rm_kg=args.kg,
            effective_from=effective_from,
            expires_on=args.expires_on,
            reason=args.reason,
        )
        until = f" until {args.expires_on}" if args.expires_on else ""
        print(f"e1RM override: {args.exercise} = {args.kg:g} kg from {effective_from}{until}")
        print("the next prescription uses it and cites it as e1rm_override:<id>")
        return 0
    finally:
        store.close()


def _print_e1rm(conn) -> None:
    rows = queries.e1rm_overrides(conn)
    if not rows:
        print("no e1RM overrides; prescriptions use the computed estimate")
        return
    today = datetime.date.today().isoformat()
    print(f"{'exercise':<24}{'e1RM kg':>9}{'from':>13}{'until':>13}  status")
    for row in rows:
        if row["effective_from"] > today:
            status = "future"
        elif row["expires_on"] and row["expires_on"] < today:
            status = "expired"
        else:
            status = "active"
        print(f"{row['exercise_id']:<24}{row['e1rm_kg']:>9g}"
              f"{row['effective_from']:>13}{row['expires_on'] or '-':>13}  {status}")


def _print_e1rm_calibration(report) -> None:
    if not report:
        print("no measured tests with a prior estimate; run `test` first, then calibrate")
        return
    print(f"{'exercise':<24}{'formula raw>eff':>20}{'override raw>eff':>20}"
          f"{'used':>9}{'n':>3}{'median':>8}{'95% CI':>15}  status")
    for row in report:
        formula = "-" if row.formula_raw is None else (
            f"{row.formula_raw:.1f}" if row.formula_effective is None
            else f"{row.formula_raw:.1f}>{row.formula_effective:.1f}"
        )
        override = "-" if row.override_raw is None else (
            f"{row.override_raw:.1f}>{row.override_effective:.1f}"
            if row.override_effective is not None else f"{row.override_raw:.1f}"
        )
        used = "-" if row.active_source is None else row.active_source
        ratio = "-" if row.median_ratio is None else f"{row.median_ratio:.3f}"
        ci = "-" if row.ci_low is None else f"{row.ci_low:.3f}-{row.ci_high:.3f}"
        print(f"{row.exercise_id:<24}{formula:>20}{override:>20}{used:>9}{row.n:>3}"
              f"{ratio:>8}{ci:>15}  {row.status}")
        for point in row.points:
            print(f"    {point.measured_on}  measured {point.measured_kg:g} kg"
                  f"  formula {point.predicted_kg:g} kg  ({point.ratio:.3f})")
    print("\nbounded correction: applied only when the 95% CI excludes 1.0 and the median "
          "bias is within ±10%; measured tests still override the formula.")


def _cmd_test(args) -> int:
    """Record a strength test as a measured e1RM override.

    A test is an assessment, not a training set: it is deliberately not written into
    clean_sets, so it cannot count as volume or trip the RIR rule (a maximal test is RIR 0 by
    definition). The e1RM override is the durable record, and the prescription cites it.
    """
    store = db.Store(args.db)
    try:
        conn = store.connection
        if args.status:
            from strength_coach.features import test_cadence
            report = test_cadence.status(
                conn, args.date or datetime.date.today().isoformat()
            )
            print("strength-test cadence")
            print(f"  due         {'yes' if report['due'] else 'no'}")
            print(f"  next        {report['next_scheme']} by {report['next_due']}")
            print(f"  last test   {report['last_test'] or 'none'}")
            print(f"  basis       {report['reason']}")
            guard = exposure_feature.status(conn, args.date or datetime.date.today().isoformat())
            print(f"  exposure    {guard.status} ({guard.reason})")
            if guard.next_maximal_on:
                print(f"  next max    {guard.next_maximal_on}")
            return 0
        if not args.exercise or args.kg is None or args.reps is None:
            print("--exercise, --kg and --reps are required unless --status is used")
            return 2
        if args.kg <= 0:
            print("test load must be positive")
            return 2
        if not 1 <= args.reps <= 10:
            print("reps must be between 1 and 10")
            return 2
        if args.reps == 1 and not args.max:
            print("a single-rep test is a true 1RM: re-run with --max to declare it")
            return 2

        on_date = args.date or datetime.date.today().isoformat()
        guard = exposure_feature.status(conn, on_date)
        if guard.status == "blocked":
            print(f"test blocked: {guard.reason}")
            print(f"next maximal exposure allowed on {guard.next_maximal_on}")
            return 2
        computed = e1rm_mod.epley_rir_adjusted(args.kg, args.reps, 0)
        value = float(args.e1rm) if args.e1rm is not None else computed
        if value <= 0:
            print("e1RM must be positive")
            return 2

        thresholds = prescribe_config.Thresholds.load()
        previous = queries.last_measured_override(conn, args.exercise)
        days_since = None
        if previous is not None:
            try:
                days_since = (
                    datetime.date.fromisoformat(on_date)
                    - datetime.date.fromisoformat(previous["effective_from"])
                ).days
            except ValueError:
                days_since = None

        if args.reps == 1 and days_since is not None:
            if days_since < thresholds.test_max_single_min_interval_days and not args.force:
                print(
                    f"a 1RM test for {args.exercise} was recorded {days_since} days ago; "
                    f"the minimum interval is {thresholds.test_max_single_min_interval_days} "
                    "days (use --force to override)"
                )
                return 2

        label = "1RM" if args.reps == 1 else f"{args.reps}RM"
        print(f"{label} test: {args.kg:g} kg x {args.reps} -> e1RM {computed:.1f} kg")
        if args.e1rm is not None:
            print(f"using the supplied e1RM instead: {value:.1f} kg")
            if computed > 0 and abs(value - computed) / computed > 0.15:
                print("note: that differs from the formula estimate by more than 15%")
        if days_since is not None and days_since < thresholds.test_min_interval_days:
            print(
                f"note: {args.exercise} was tested {days_since} days ago; testing more often "
                f"than every {thresholds.test_min_interval_days} days is a stimulus, not a "
                "measurement"
            )

        if not args.yes:
            answer = input("record this as the measured e1RM? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("not recorded")
                return 1

        reason = args.reason or f"{label} test: {args.kg:g} kg x {args.reps}"
        override_id = repositories.append_e1rm_override(
            conn,
            exercise_id=args.exercise,
            e1rm_kg=value,
            effective_from=on_date,
            reason=reason,
            source="measured",
        )
        exposure_id = exposure_feature.register_test(
            conn,
            override_id=override_id,
            exercise_id=args.exercise,
            performed_on=on_date,
            test_type=exposure_feature.test_type_for_reps(args.reps),
            note=reason,
        )
        print(f"recorded e1rm_override:{override_id}: {args.exercise} = {value:g} kg "
              f"from {on_date}")
        print(f"high-intensity exposure: {exposure_id} (test, no volume)")
        print("the next prescription uses it and cites the override")
        return 0
    finally:
        store.close()


def _cmd_symptom(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        config = injury_signal_mod.InjuryConfig.load()
        requested = str(args.region).strip().lower() if args.region else None
        if requested is not None and requested not in config.regions:
            known = ", ".join(sorted(config.regions)) or "none configured"
            raise SystemExit(
                f"unknown injury region {requested!r}; configured regions: {known} "
                f"(add one in config/injuries.v1.yaml)"
            )
        if args.show or args.level is None:
            # Showing is a survey: with no --region, list every region's readings.
            _print_symptoms(conn, region=requested)
            return 0

        # Logging keeps the original low_back default so the one-number habit still works.
        region = requested or "low_back"

        on_date = args.date or datetime.date.today().isoformat()
        settled = {"yes": True, "no": False, "unknown": None}.get(args.settled)
        repositories.append_symptom(
            conn,
            logged_on=on_date,
            timing="pre_session",
            region=region,
            level=args.level,
            settled_within_48h=settled,
            note=args.note,
        )
        print(f"logged {region} symptom {args.level}/3 on {on_date} (pre-session)")
        if args.level >= 2:
            if region == "low_back":
                print("that is a flare: MOD-BACK-001 will apply to the next prescription")
            else:
                print(f"that is a flare: the {region} signal will show it as active")
        elif args.level == 1 and settled is False:
            print("level 1 that did not settle is also a flare (DEC-SYMPTOM-02)")
        return 0
    finally:
        store.close()


def _print_symptoms(conn, *, region: str | None = None) -> None:
    entries = queries.symptom_entries(conn, region=region)
    if not entries:
        where = f" for {region}" if region else ""
        print(f"no symptom entries logged{where}; injury signals stay unknown until one exists")
        return
    print(f"{'date':<12}{'region':<12}{'timing':<14}{'level':>6}  {'settled':<8} note")
    for row in entries[-20:]:
        settled = "-" if row["settled_within_48h"] is None else (
            "yes" if row["settled_within_48h"] else "no"
        )
        print(f"{row['logged_on']:<12}{row['region']:<12}{row['timing']:<14}"
              f"{row['level']:>6}  "
              f"{settled:<8} {row['note'] or ''}")


def _cmd_cardio(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        logging = args.modality is not None or args.minutes is not None
        if args.show or not logging:
            _print_cardio(conn, weeks=args.weeks, on_date=args.date)
            return 0
        if not args.modality:
            raise SystemExit("--modality is required when logging a cardio session")
        if args.minutes is None:
            raise SystemExit("--minutes is required when logging a cardio session")
        on_date = args.date or datetime.date.today().isoformat()
        repositories.append_cardio(
            conn,
            performed_on=on_date,
            modality=args.modality,
            duration_s=round(float(args.minutes) * 60),
            avg_hr=args.avg_hr,
            max_hr=args.max_hr,
            distance_m=(None if args.distance_km is None else args.distance_km * 1000),
            srpe=args.srpe,
            note=args.note,
        )
        print(f"logged {args.modality} {args.minutes:g} min on {on_date}")
        summary = cardio_feature.compute(conn, weeks=args.weeks, on_date=on_date)
        print(f"last {args.weeks} weeks: {summary.total_minutes:g} min across "
              f"{summary.sessions} sessions "
              f"({summary.average_weekly_minutes:g} min/week)")
        return 0
    finally:
        store.close()


def _print_cardio(conn, *, weeks: int = 12, on_date: str | None = None) -> None:
    summary = cardio_feature.compute(conn, weeks=weeks, on_date=on_date)
    print(f"cardio, last {weeks} weeks ({summary.from_date} to {summary.to_date})")
    print(f"  sessions        {summary.sessions}")
    print(f"  total minutes   {summary.total_minutes:g}")
    print(f"  average/week    {summary.average_weekly_minutes:g}")
    if summary.average_srpe is not None:
        print(f"  average sRPE    {summary.average_srpe:g}/10")
    if summary.by_modality:
        print("  modalities      " + ", ".join(
            f"{name} x{count}" for name, count in summary.by_modality.items()
        ))
    if summary.weekly_minutes:
        print("  weekly minutes")
        for week, minutes in summary.weekly_minutes.items():
            print(f"    {week}  {minutes:g}")
    print(f"  reference       {summary.reference_min}-{summary.reference_max} min/week")
    print(f"  {summary.reference_note}")


def _cmd_exercise(args) -> int:
    if args.action == "list":
        catalog = exercise_admin.catalog()
        for row in catalog["entities"]:
            print(f"  {row['id']:<42} {row['pattern']:<22} {row['source']:<8} {row['display']}")
        return 0
    props = json.loads(args.props_json)
    result = exercise_admin.save(args.id, props)
    row = next(r for r in result["entities"] if r["id"] == args.id)
    print(f"exercise {args.id}: {row['display']} ({row['pattern']}, {row['source']})")
    return 0


def _cmd_workout(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        active = workout.active_workout(conn)
        if args.action == "status":
            print(json.dumps(active, indent=2, default=str))
            return 0
        if active is None:
            print("no active workout")
            return 2
        identifier = active["workout_id"]
        if args.action == "add-set":
            result = workout.add_set(
                conn, identifier, exercise_id=args.exercise, load_kg=args.load,
                reps=args.reps, rir=args.rir, velocity=args.velocity,
            )
        elif args.action == "update-set":
            result = workout.update_set(
                conn, identifier, args.set_id, load_kg=args.load, reps=args.reps,
                rir=args.rir, velocity=args.velocity,
            )
        elif args.action == "remove-set":
            result = workout.remove_set(conn, identifier, args.set_id)
        elif args.action == "end":
            result = workout.end(
                conn, identifier, session_rpe=args.session_rpe,
                not_recorded=args.not_recorded, duration_min=args.duration_min,
                notes=args.note,
            )
        elif args.action == "abandon":
            result = workout.abandon(conn, identifier)
        elif args.action == "import":
            text = Path(args.file).read_text(encoding="utf-8")
            imported = workout.import_csv(conn, identifier, text, apply=args.apply)
            print(json.dumps(imported["preview"], indent=2, default=str))
            if not args.apply:
                return 0
            result = imported["workout"]
        else:
            print(f"unknown workout action: {args.action}")
            return 2
        print(json.dumps(result, indent=2, default=str))
        return 0
    finally:
        store.close()


def _cmd_validate(args) -> int:
    store = db.Store(args.db)
    try:
        print(retrospective_validation.report(store.connection, max_dates=args.max_dates))
        return 0
    finally:
        store.close()


def _cmd_select(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        chooser = None
        if args.llm:
            chooser = agent_selection.chooser(build_client(load_settings()))
        rows = selection_mod.select(
            conn, None, args.date, args.session_type, chooser=chooser,
            include_different=args.include_different,
        )
    finally:
        store.close()
    print(f"exercise selection (shadow; no prescription change) {args.date} {args.session_type}")
    if not rows:
        print("no multi-variant slots on this day")
        return 0
    for row in rows:
        mark = "->" if row.changed else "="
        print(f"  {row.slot_id:<28}{row.current} {mark} {row.suggested}  "
              f"[{row.source}; class {row.comparison_class}]")
        print(f"    {row.reason}")
        for candidate in row.candidates:
            context = ""
            if candidate.history_context:
                hc = candidate.history_context
                context = (f"  own-history {hc.status}"
                           f" (ratio {hc.ratio:.2f}, n={hc.n})"
                           if hc.ratio is not None else f"  own-history {hc.status}")
            print(f"    {candidate.exercise_id:<24} {candidate.score:.3f}  "
                  f"{', '.join(candidate.reasons)}{context}")
    return 0


def _cmd_exposure(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        on_date = args.date or datetime.date.today().isoformat()
        if args.action == "log":
            exposure_id = exposure_feature.log_manual(
                conn, performed_on=on_date, kind=args.kind, region_load=args.region,
                exercise_id=args.exercise, intensity_class=args.intensity,
                axial_cost=args.axial_cost, note=args.note,
            )
            print(f"high-intensity exposure: {exposure_id}")
        report = exposure_feature.status(conn, on_date)
        print(f"status: {report.status} — {report.reason}")
        if report.next_maximal_on:
            print(f"next maximal exposure allowed on {report.next_maximal_on}")
        for row in report.exposures:
            print(f"  {row['performed_on']} {row['kind']} "
                  f"{row.get('exercise_id') or ''} {row['region_load']} "
                  f"{row['intensity_class']}")
        return 0
    finally:
        store.close()


def _cmd_outcomes(args) -> int:
    store = db.Store(args.db)
    try:
        report = outcomes_feature.report(
            store.connection, weeks=args.weeks, on_date=args.date
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
            return 0
        window = report["window"]
        print(f"outcomes: {window['from']} to {window['to']} ({window['weeks']} weeks)")
        print("\nstrength")
        for lift in report["strength"]["main_lifts"]:
            print(f"  {lift['exercise_id']:<28} {lift['first_e1rm']:>7} -> {lift['last_e1rm']:>7} kg"
                  f"  ({lift['change_kg']:+g}, n={lift['n']})")
        attendance = report["strength"]["attendance"]
        print(f"  attendance: {attendance['completed']}/{attendance['target']} "
              f"({attendance['pct']}%) — {attendance['note']}")
        print(f"  sRPE: {report['strength']['sRPE']}")
        print(f"  duration: {report['strength']['duration']}")
        print("\nlongevity")
        cardio = report["longevity"]["cardio"]
        print(f"  cardio: {cardio['average_weekly_minutes']} min/week average; "
              f"{cardio['sessions']} session(s)")
        measured = [
            key for key, row in report["longevity"]["measurements"].items()
            if row.get("latest_value") is not None
        ]
        print(f"  measurements: {', '.join(measured) or 'none measured'}")
        print("\ncoverage")
        for key, value in report["coverage"].items():
            print(f"  {key}: {value}")
        print(f"\n{report['note']}")
        return 0
    finally:
        store.close()


def _cmd_prospective(args) -> int:
    store = db.Store(args.db)
    try:
        report = prospective_feature.report(
            store.connection, weeks=args.weeks, on_date=args.date
        )
        if args.json:
            print(json.dumps(report, indent=2, default=str))
            return 0
        window = report["window"]
        print(f"prospective: {window['current_from']} to {window['current_to']} "
              f"({window['weeks']} weeks; baseline {window['baseline_from']} to "
              f"{window['baseline_to']})")
        for lift in report["strength"]["lifts"]:
            print(f"  {lift['exercise_id']:<28} {lift['status']:<8}"
                  f" change={lift['change_pct']}% n={lift['baseline_n']}/{lift['current_n']}")
        attendance = report["attendance"]
        print(f"  attendance: {attendance['completed']}/{attendance['target']} "
              f"({attendance['pct']}%)")
        print(f"  work: {report['work']['status']} ({report['work']['actual_sets']}/"
              f"{report['work']['planned_sets']})")
        print(f"  RIR: {report['rir']['adherence']} over {report['rir']['n']} sets")
        print(f"  duration: {report['duration']['median_min']} min "
              f"({report['duration']['measured_n']} measured)")
        print(f"  flags: {', '.join(f['code'] for f in report['flags']) or 'none'}")
        print(report["note"])
        return 0
    finally:
        store.close()


def _cmd_volume(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        on_date = args.date or datetime.date.today().isoformat()
        context = RuleContext.from_store(conn, end=on_date)
        report = volume_feature.compute(context.sets, on_date=on_date,
                                        config=volume_feature.VolumeConfig(
                                            window_weeks=args.weeks,
                                            targets=volume_feature.VolumeConfig.load().targets,
                                            landmarks=volume_feature.VolumeConfig.load().landmarks,
                                            apply_mrv_cap=volume_feature.VolumeConfig.load().apply_mrv_cap,
                                        ))
    finally:
        store.close()
    print(f"weekly hard sets, {report['from']} to {report['to']} (weeks {report['weeks']})")
    print(f"  {'pattern':<28}{'avg/wk':>8}{'total':>8}{'target':>12}  status")
    for row in report["patterns"]:
        target = "-" if row["target"] is None else f"{row['target'][0]:g}-{row['target'][1]:g}"
        print(f"  {row['pattern']:<28}{row['average']:>8.1f}{row['total']:>8}"
              f"{target:>12}  {row['status']}")
    heavy = heavy_spinal.compute(
        context.sets, on_date=on_date,
        config=heavy_spinal.HeavySpinalConfig(
            window_weeks=args.weeks,
            rir_max=heavy_spinal.HeavySpinalConfig.load().rir_max,
        ),
    )
    print(f"  heavy spinal sets (RIR <= {heavy['rir_max']}): {heavy['total_sets']}; "
          "context only, not in the cap")
    return 0


def _cmd_continuity(args) -> int:
    if args.allow_relax_fixed is not None:
        cfg = continuity_calibration.save_allow_relax_fixed(args.allow_relax_fixed == "on")
        print(f"allow_relax_fixed={str(cfg.allow_relax_fixed).lower()}")
    store = db.Store(args.db)
    try:
        conn = store.connection
        on_date = args.date or datetime.date.today().isoformat()
        context = RuleContext.from_store(conn, end=on_date)
        thresholds = prescribe_config.Thresholds.load()
        report = continuity_calibration.compute(
            context.sets,
            short_days=thresholds.continuity_short_days,
            medium_days=thresholds.continuity_medium_days,
            long_days=thresholds.continuity_long_days,
            medium_multiplier=thresholds.continuity_medium_multiplier,
            long_multiplier=thresholds.continuity_long_multiplier,
        )
    finally:
        store.close()
    print(f"continuity calibration as of {on_date}: {report.n_total} returns; "
          f"applied={report.applied}")
    print(f"  {'band':<8}{'n':>4}{'median':>9}{'CI':>17}{'fixed':>8}{'factor':>8}  status")
    for band in ("short", "medium", "long"):
        row = report.bands[band]
        ci = "-" if row.low is None else f"{row.low:.3f}-{row.high:.3f}"
        median = "-" if row.median is None else f"{row.median:.3f}"
        print(f"  {band:<8}{row.n:>4}{median:>9}{ci:>17}{row.fixed:>8.2f}"
              f"{row.factor:>8.3f}  {row.status}")
    print(f"  {report.note}")
    return 0


def _cmd_fatigue(args) -> int:
    store = db.Store(args.db)
    try:
        on_date = args.date or datetime.date.today().isoformat()
        models = fatigue_fitness_feature.compute(store.connection, on_date)
    finally:
        store.close()
    if not models:
        print("no e1RM observations for the strength model yet")
        return 0
    print(f"strength fitness-fatigue (shadow; no load effect) as of {on_date}")
    print(f"{'exercise':<24}{'n':>3}{'span':>6}{'R2':>7}{'backtest':>10}"
          f"{'fitness':>9}{'fatigue':>9}{'state [95% CI]':>21}  status")
    for model in models:
        r2 = "-" if model.r2 is None else f"{model.r2:.2f}"
        suffix = "" if model.unit == "kg" else "x"
        fit = "-" if model.fitness_kg is None else f"{model.fitness_kg:.1f}{suffix}"
        fat = "-" if model.fatigue_kg is None else f"{model.fatigue_kg:.1f}{suffix}"
        bt = "-" if model.backtest_mae is None else (
            f"{model.backtest_mae:.1f}/{model.backtest_naive_mae:.1f}"
        )
        state = "-" if model.state_kg is None else f"{model.state_kg:.1f}{suffix}"
        if model.state_ci_low is not None and model.state_ci_high is not None:
            state += f" [{model.state_ci_low:.1f},{model.state_ci_high:.1f}]"
        print(f"{model.exercise_id:<24}{model.n_observations:>3}{model.span_days:>6}"
              f"{r2:>7}{bt:>10}{fit:>9}{fat:>9}{state:>21}  {model.status}")
    print("\nshadow only: parameters are fitted, not validated; no prescription reads this.")
    return 0


def _cmd_measure(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        if args.show or (args.metric is None and args.value is None):
            _print_measurements(conn, metric_key=args.metric)
            return 0
        if args.metric is None:
            raise SystemExit("--metric is required (or use --show to list metrics)")
        if args.value is None:
            # A bare --metric filters the display; it does not log a value.
            _print_measurements(conn, metric_key=args.metric)
            return 0
        spec = measurements_feature.record(
            conn,
            metric_key=args.metric,
            value=args.value,
            measured_on=args.date,
            method=args.method,
            note=args.note,
        )
        unit = f" {spec.unit}" if spec.unit else ""
        print(f"logged {spec.label}: {args.value:g}{unit}")
        _print_measurements(conn, metric_key=spec.key)
        return 0
    finally:
        store.close()


def _print_measurements(conn, *, metric_key: str | None = None) -> None:
    rows = measurements_feature.summary(conn)
    if metric_key is not None:
        rows = [row for row in rows if row["key"] == metric_key]
    print("measurements")
    for row in rows:
        unit = f" {row['unit']}" if row["unit"] else ""
        if row["count"] == 0:
            print(f"  {row['key']:<22} no entries       {row['label']}")
            continue
        change = row["change"]
        trend = (
            f", {change:+g}{unit} since first"
            if change is not None and row["count"] > 1 else ""
        )
        print(f"  {row['key']:<22} {row['latest_value']:g}{unit} on {row['latest_on']}"
              f"  ({row['count']} entr{'y' if row['count'] == 1 else 'ies'}{trend})")
    recent = measurements_feature.entries(conn, metric_key=metric_key)[-10:]
    if recent:
        print("\nrecent entries")
        for entry in recent:
            method = f" · {entry['method']}" if entry.get("method") else ""
            print(f"  {entry['measured_on']}  {entry['metric_key']:<22} "
                  f"{float(entry['value']):g}{method}")


def _cmd_block(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        current = queries.athlete_profile(conn)
        if current is None:
            print("no athlete profile yet; run 'strength-coach state --import FILE' first")
            return 2
        if current["block_start_date"] and not args.force:
            print(f"the block already started on {current['block_start_date']}; "
                  "pass --force to reset (the ramp restarts at week 1)")
            return 2
        repositories.append_athlete_profile(
            conn,
            effective_from=datetime.date.today().isoformat(),
            primary_goal=current["primary_goal"],
            goal_rank=json.loads(current["goal_rank"] or "[]"),
            focus_lifts=json.loads(current["focus_lifts"] or "[]"),
            competition_date=current["competition_date"],
            sessions_per_week_target=current["sessions_per_week_target"],
            max_session_minutes=current["max_session_minutes"],
            block_start_date=args.date,
        )
        print(f"block starts {args.date}: ramp at week 1 (DEC-RAMP-02)")
        return 0
    finally:
        store.close()


def _import_state(conn, path: Path, *, force: bool) -> int:
    if not path.exists():
        print(f"state file not found: {path}")
        return 2
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"could not parse {path}: {exc}")
        return 2

    if queries.athlete_profile(conn) is not None and not force:
        print("athlete state is already recorded; pass --force to append a new version")
        return 2

    profile = raw.get("profile") or {}
    if not profile:
        print("state file has no profile section")
        return 2
    repositories.append_athlete_profile(
        conn,
        effective_from=str(profile.get("effective_from") or datetime.date.today().isoformat()),
        primary_goal=str(profile["primary_goal"]),
        goal_rank=profile.get("goal_rank") or [],
        focus_lifts=profile.get("focus_lifts") or [],
        competition_date=profile.get("competition_date"),
        sessions_per_week_target=profile.get("sessions_per_week_target"),
        max_session_minutes=profile.get("max_session_minutes"),
        block_start_date=profile.get("block_start_date"),
    )

    constraints = raw.get("constraints") or []
    for entry in constraints:
        repositories.append_athlete_constraint(
            conn,
            kind=str(entry["kind"]),
            region=str(entry["region"]),
            severity=str(entry["severity"]),
            forbidden_patterns=entry.get("forbidden_patterns") or [],
            forbidden_exercises=entry.get("forbidden_exercises") or [],
            rom_limit=entry.get("rom_limit"),
            since=entry.get("since"),
            settled_on=entry.get("settled_on"),
            evidence=entry.get("evidence"),
            source=str(entry.get("source", "user")),
        )

    suitability = raw.get("suitability") or {}
    rated_on = str(suitability.get("rated_on") or datetime.date.today().isoformat())
    exercises = suitability.get("exercises") or {}
    for exercise_id, rating in exercises.items():
        repositories.append_exercise_suitability(
            conn,
            exercise_id=str(exercise_id),
            rated_on=rated_on,
            can_do=bool(rating.get("can_do", True)),
            will_do=bool(rating.get("will_do", True)),
            feels_bad=bool(rating.get("feels_bad", False)),
            note=rating.get("note"),
            source=str(rating.get("source", "user")),
        )

    for entry in raw.get("metrics") or []:
        repositories.append_metric_definition(
            conn,
            metric_key=str(entry["metric_key"]),
            label=str(entry["label"]),
            higher_is_better=bool(entry["higher_is_better"]),
            aggregation=str(entry["aggregation"]),
            scale_min=entry.get("scale_min"),
            scale_max=entry.get("scale_max"),
            unit=entry.get("unit"),
            source=entry.get("source"),
            active_from=entry.get("active_from"),
        )

    overrides = raw.get("e1rm_overrides") or []
    for entry in overrides:
        repositories.append_e1rm_override(
            conn,
            exercise_id=str(entry["exercise_id"]),
            e1rm_kg=float(entry["e1rm_kg"]),
            effective_from=str(entry.get("effective_from")
                               or datetime.date.today().isoformat()),
            expires_on=entry.get("expires_on"),
            reason=entry.get("reason"),
            source=str(entry.get("source", "user")),
        )

    for entry in raw.get("symptoms") or []:
        repositories.append_symptom(
            conn,
            logged_on=str(entry["logged_on"]),
            timing=str(entry["timing"]),
            region=str(entry["region"]),
            level=int(entry["level"]),
            settled_within_48h=entry.get("settled_within_48h"),
            note=entry.get("note"),
        )

    readiness_count = 0
    for entry in raw.get("readiness") or []:
        day = str(entry.get("date") or entry.get("on_date") or "")
        values = {field: entry[field] for field in readiness_utils.READINESS_FIELDS
                  if field in entry}
        try:
            readiness_count += _record_readiness(
                conn, day, values, note=entry.get("note")
            )
        except ValueError as exc:
            print(f"readiness {day}: {exc}")
            return 2

    print(f"recorded: profile 1, constraints {len(constraints)}, "
          f"suitability {len(exercises)}, metrics {len(raw.get('metrics') or [])}, "
          f"readiness {readiness_count}, "
          f"e1RM overrides {len(overrides)}, symptoms {len(raw.get('symptoms') or [])}")
    return 0


def _print_state(conn) -> None:
    profile = queries.athlete_profile(conn)
    if profile is None:
        print("no athlete state recorded; run 'strength-coach state --import FILE'")
        return
    print("athlete profile")
    print(f"  primary goal        {profile['primary_goal']}")
    print(f"  goal rank           {profile['goal_rank']}")
    print(f"  focus lifts         {profile['focus_lifts']}")
    print(f"  sessions/week       {profile['sessions_per_week_target']}")
    print(f"  max session         {profile['max_session_minutes']} min")
    print(f"  block start         {profile['block_start_date'] or 'not declared'}")

    constraints = queries.athlete_constraints(conn)
    print(f"\nconstraints ({len(constraints)})")
    for rule in constraints:
        print(f"  {rule['severity']:<12} {rule['kind']:<14} {rule['region']:<10} "
              f"since {rule['since'] or '?'}  settled {rule['settled_on'] or '?'}")

    ratings = queries.exercise_suitability(conn)
    blocked = [e for e, r in ratings.items() if not r["can_do"]]
    unwelcome = [e for e, r in ratings.items() if r["can_do"] and not r["will_do"]]
    print(f"\nsuitability ({len(ratings)} exercises)")
    print(f"  cannot do           {blocked or 'none'}")
    print(f"  will not do         {unwelcome or 'none'}")

    symptoms = queries.symptom_entries(conn)
    symptom_counts: dict[str, int] = {}
    for row in symptoms:
        symptom_counts[str(row["region"])] = symptom_counts.get(str(row["region"]), 0) + 1
    print(f"\nsymptom entries ({len(symptoms)}) {symptom_counts or ''}".rstrip())

    signal = injury_signal_mod.compute(
        conn, datetime.date.today().isoformat()
    )
    print("\ninjury signal")
    print(f"  status            {signal.status}")
    print(f"  summary           {signal.summary}")
    if signal.ramp_week is not None:
        print(f"  ramp week         {signal.ramp_week}")
    for region in signal.regions:
        print(f"\n  {region.label} ({region.region})")
        print(f"    status          {region.status}")
        print(f"    summary         {region.summary}")
        print(f"    window          {region.window_days} days, "
              f"{region.required_tolerated_sessions} tolerated sessions required")
        print(f"    tolerated       {region.tolerated_sessions} of "
              f"{region.loaded_sessions} loaded sessions "
              f"({region.unverified_sessions} unverified)")
        if region.recommendation:
            print(f"    recommendation  {region.recommendation}")
        if region.linked_exercises:
            print(f"    loaded by       {', '.join(region.linked_exercises)}")
    print(f"\n  disclaimer        {signal.disclaimer}")


# --- helpers ---------------------------------------------------------------


def _ensure_imported(conn) -> None:
    existing = conn.execute("SELECT COUNT(*) AS c FROM session").fetchone()["c"]
    if existing:
        return
    if not (paths.training_log_csv().exists() and paths.readiness_csv().exists()):
        raise SystemExit(
            "no sessions in the store and no raw exports found; "
            "put them in data/raw/ or run 'strength-coach import'"
        )
    report = _import_export(conn)
    _print_import(report)


def _import_export(conn):
    training_path = paths.training_log_csv()
    readiness_path = paths.readiness_csv()
    for path in (training_path, readiness_path):
        if not Path(path).exists():
            raise SystemExit(f"missing input: {path}")
    training = io_utils.read_raw_csv(training_path)
    readiness = io_utils.read_raw_csv(readiness_path)
    return importer.import_export(
        conn,
        training,
        readiness,
        training_sha256=importer.sha256_file(training_path),
        readiness_sha256=importer.sha256_file(readiness_path),
    )


def _propose(conn, trace, prescription, args):
    """Ask for a structured proposal and decide it. Returns (prescription, approved_by).

    Every rejection path keeps the deterministic prescription: the model may propose, the
    validator decides, and a failure never leaves the athlete without a session.
    """
    settings = load_settings()
    client = build_client(settings)
    if not client.available:
        print("\n(proposal skipped: no model configured)")
        return prescription, "deterministic"

    context = RuleContext.from_store(conn, end=prescription.for_date)
    if prescription.fallback_level != "full" or context.symptom_flare:
        print("\n(proposal skipped: the session was already modified by a safety rule)")
        return prescription, "deterministic"

    allowed = proposal_mod.allowed_substitutes(conn, context, prescription)
    document = load_document()
    options = proposal_mod.menu(prescription, document)
    reps = proposal_mod.scheme_options(prescription, schemes_mod.Schemes.load())
    try:
        response = client.complete(
            proposal_mod.prompt_for(prescription, allowed, options, reps),
            system=proposal_mod.SYSTEM,
        )
    except LLMError as exc:
        print(f"\nproposal unavailable: {exc}")
        trace.finish(status="llm_failed")
        return prescription, "deterministic"

    trace.add_tokens(response.tokens)
    trace.event("llm_output", {
        "kind": "proposal", "text": response.text, "model": response.model,
    })

    try:
        parsed = proposal_mod.parse(response.text)
    except proposal_mod.ProposalError as exc:
        print(f"\nproposal rejected: {exc}")
        trace.event("policy_verdict", {"proposal": "rejected", "reasons": [str(exc)]})
        trace.finish(status="llm_downgraded")
        return prescription, "deterministic"

    thresholds = prescribe_config.Thresholds.load()
    decisions = evaluate(document, context).verdict("PRG-DP-001").details.get("decisions", {})
    outcome = proposal_mod.assess(
        conn, prescription, parsed, context=context, document=document,
        thresholds=thresholds, decisions=decisions,
    )

    print("\nproposal")
    print("  " + proposal_mod.describe(parsed))
    if parsed.summary:
        print(f"  why: {parsed.summary}")

    if not outcome.accepted:
        print("  rejected: " + "; ".join(outcome.reasons))
        trace.event("policy_verdict", {
            "proposal": "rejected", "reasons": list(outcome.reasons),
        })
        trace.finish(status="llm_downgraded")
        return prescription, "deterministic"

    essential_ids = {item.exercise_id for item in prescription.items if item.essential}
    main_change = any(
        change.action == "substitute" and change.exercise in essential_ids
        for change in parsed.changes
    )
    if main_change:
        # A main-lift swap is never applied silently, even with --yes.
        answer = input("  this replaces an essential lift; apply? [y/N] ").strip().lower()
    elif not args.yes:
        answer = input("  apply this proposal? [y/N] ").strip().lower()
    else:
        answer = "yes"
    if answer not in ("y", "yes"):
        print("  declined: keeping the deterministic prescription")
        trace.event("policy_verdict", {"proposal": "declined"})
        return prescription, "deterministic"

    trace.event("policy_verdict", {
        "proposal": "accepted",
        "changes": proposal_mod.describe(parsed),
        "main_substitution": main_change,
    })
    print("  accepted")
    return outcome.prescription, "llm+policy"


def _narrate(conn, trace, critique, facts, prescription) -> None:
    settings = load_settings()
    client = build_client(settings)
    if not client.available:
        print("\n(llm off: no model configured, see config/llm.example.toml)")
        return
    if getattr(trace, "run_id", None):
        pass
    text = explain_critique(client, critique, facts, trace)
    if text:
        print("\nnarrative\n" + text)
    else:
        trace.finish(status="llm_failed")
        return
    text = explain_prescription(client, prescription, trace)
    if text:
        print("\nprescription narrative\n" + text)


def _print_import(report) -> None:
    print(f"imported: {report.raw_rows_inserted} new raw rows, "
          f"{report.raw_rows_overlap} overlapping, "
          f"{report.clean_sets_inserted} clean sets, {report.sessions_written} sessions, "
          f"{report.readiness_days} readiness days, {report.quarantined} quarantined")
    # Import and calibration are separate steps: sessions are not labels. Without marks,
    # `calibrate` has nothing to compare, so point at review rather than implying a next run.
    print("next: review recent sessions (`strength-coach review --pending`) to create marks; "
          "rubric calibration runs after reviews, not as part of the import")


def _print_prescription(prescription) -> None:
    print(f"\nprescription {prescription.for_date}  "
          f"({prescription.session_type}, {prescription.fallback_level})")
    show_velocity = any(item.velocity_target is not None for item in prescription.items)
    header = (f"  {'exercise':<24}{'sets':>5}{'reps':>8}{'load':>9}{'rir':>5}"
              + (f"{'vel':>7}" if show_velocity else "") + "  refs")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for item in prescription.items:
        load = "-" if item.load_kg is None else f"{item.load_kg:g}"
        reps = f"{item.reps_low}-{item.reps_high}"
        velocity = ""
        if show_velocity:
            velocity = (f"{item.velocity_target:>7.2f}"
                        if item.velocity_target is not None else f"{'-':>7}")
        print(f"  {item.exercise_id:<24}{item.sets:>5}{reps:>8}{load:>9}"
              f"{item.rir_target:>5}{velocity}  {', '.join(item.rationale_refs) or '-'}")
    if prescription.issues:
        print("  issues: " + "; ".join(prescription.issues))
    stress = (prescription.notes or {}).get("recent_stress") or {}
    if stress:
        print("  recent stress (decayed hard sets; advisory)")
        for item in prescription.items:
            entry = stress.get(item.exercise_id)
            if entry is None:
                continue
            print(f"    {item.exercise_id:<24} {entry['status']:<7}"
                  f" {entry['decayed_sets']:>5.1f} sets, last {entry['last_hours']:g}h ago")
    lift_ready = (prescription.notes or {}).get("per_lift_readiness") or {}
    if lift_ready:
        print("  per-lift readiness (advisory; can only lower a load)")
        for item in prescription.items:
            entry = lift_ready.get(item.exercise_id)
            if entry is None:
                continue
            print(f"    {item.exercise_id:<24} {entry['status']:<8} {entry['score']:.2f}")
    for warning in prescription.warnings:
        print(f"  note: {warning}")

    signal = prescription.notes.get("injury_signal")
    if signal:
        print(f"  injury signal: {signal['status']} — {signal['summary']}")
        for region in (signal.get("regions") or {}).values():
            if region.get("recommendation"):
                print(f"    {region['label']}: {region['recommendation']}")
        print(f"    {signal['disclaimer']}")


def _print_critique(critique) -> None:
    composite = "-" if critique.composite is None else f"{critique.composite:.2f}"
    print(f"\ncritique {critique.session_id}: composite {composite}")
    for item in critique.items:
        if item.measurable and item.score is not None:
            print(f"  {item.key:<24}{item.score:>6.2f}   {item.detail[:60]}")
        else:
            print(f"  {item.key:<24}{'  n/a':>6}   {item.detail[:60]}")


def _print_calibration(conn, tolerance: float) -> None:
    labels = load_marks(conn)
    if not labels.sessions:
        return
    report = backtest(conn, labels, tolerance=tolerance)
    print("\n" + format_report(report))


def _ask_scores(critique) -> dict[str, float | None]:
    scores: dict[str, float | None] = {}
    print("\nenter a score for each item (enter = skip, 'q' = stop)")
    for item in critique.items:
        engine = item.score if item.measurable else None
        shown = "n/a" if engine is None else f"{engine:.2f}"
        while True:
            raw = input(f"  {item.key:<24} engine {shown:>4}  score 0-1: ").strip()
            if raw.lower() == "q":
                return scores
            if raw == "":
                scores[item.key] = None
                break
            try:
                value = float(raw)
            except ValueError:
                print("    not a number")
                continue
            if 0.0 <= value <= 1.0:
                scores[item.key] = value
                break
            print("    must be between 0 and 1")
    return scores


def _ask_confidence() -> str:
    raw = input("\nhow well do you remember this session? [high/low/unknown] (default high): ")
    value = raw.strip().lower() or "high"
    if value not in {"high", "low", "unknown"}:
        print("    unrecognised; treating as unknown")
        return "unknown"
    return value


def _new_id() -> str:
    import uuid

    return uuid.uuid4().hex


if __name__ == "__main__":
    sys.exit(main())
