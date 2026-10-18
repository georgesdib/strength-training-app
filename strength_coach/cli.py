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

from strength_coach import __version__
from strength_coach.agents import (
    LLMError,
    build_client,
    explain_critique,
    explain_prescription,
    load_settings,
)
from strength_coach.agents import proposal as proposal_mod
from strength_coach.critique import UnknownSessionError, build_facts, score_session
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.critique import persist as persist_critique
from strength_coach.critique.rubric import RUBRIC_VERSION
from strength_coach.eval import backtest, load_marks, record_marks
from strength_coach.eval.report import format_report, format_session_sheet, item_guide_lines
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe import config as prescribe_config
from strength_coach.prescribe import schemes as schemes_mod
from strength_coach.rules import RuleContext, evaluate, load_document
from strength_coach.store import db, importer, queries, repositories
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
    run.add_argument("--day", choices=("A", "B", "C"), default="B",
                     help="which programme day to prescribe (default: B)")
    run.add_argument("--llm", choices=("on", "off"), default="off",
                     help="ask the configured model for a narrative (default: off)")
    run.add_argument("--force", action="store_true",
                     help="regenerate even if this date was already prescribed")
    run.add_argument("--propose", action="store_true",
                     help="ask the model for a structural proposal (requires --llm on)")
    run.add_argument("--yes", action="store_true",
                     help="apply an accepted proposal without asking")

    review = sub.add_parser("review", help="mark a session and update calibration")
    review.add_argument("--session", required=True)
    review.add_argument("--scores", default=None, help="read marks from a YAML file")
    review.add_argument("--confidence", choices=("high", "low", "unknown"), default=None)
    review.add_argument("--note", default=None)

    calibrate = sub.add_parser("calibrate", help="report agreement between rubric and marks")
    calibrate.add_argument("--tolerance", type=float, default=None)

    state = sub.add_parser("state", help="show or import athlete state (goals, limits, suitability)")
    state.add_argument("--import", dest="import_file", default=None,
                       help="YAML file of athlete state to record")
    state.add_argument("--force", action="store_true",
                       help="append a new version even if state is already recorded")

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

    test = sub.add_parser("test", help="record a 3RM/5RM (or confirmed 1RM) strength test")
    test.add_argument("--exercise", required=True, help="canonical exercise id")
    test.add_argument("--kg", type=float, required=True, help="load used for the test")
    test.add_argument("--reps", type=int, required=True,
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

    symptom = sub.add_parser("symptom", help="log or show the pre-session back symptom")
    symptom.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    symptom.add_argument("--level", type=int, choices=(0, 1, 2, 3), default=None,
                         help="0 none, 1 awareness, 2 annoying, 3 limiting")
    symptom.add_argument("--settled", choices=("yes", "no", "unknown"), default=None,
                         help="did it settle within 48 hours?")
    symptom.add_argument("--note", default=None)
    symptom.add_argument("--show", action="store_true", help="list recent entries")

    block = sub.add_parser("block", help="declare or reset the block start (week 1)")
    block.add_argument("--date", required=True, help="YYYY-MM-DD")
    block.add_argument("--force", action="store_true",
                       help="reset even if the ramp is already running")

    args = parser.parse_args(argv)
    handlers = {
        "import": _cmd_import,
        "run": _cmd_run,
        "review": _cmd_review,
        "calibrate": _cmd_calibrate,
        "state": _cmd_state,
        "e1rm": _cmd_e1rm,
        "test": _cmd_test,
        "symptom": _cmd_symptom,
        "block": _cmd_block,
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
        prescription = build_prescription(conn, for_date=args.date, session_day=args.day)

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
                session_day=prescription.session_day,
                fallback_level=prescription.fallback_level,
                rule_document_version=prescription.rule_document_version,
                # VBT targets are deferred to v0.1 (DEC-VBT-01), so no calibration is cited.
                calibration_ids=[],
                approved_by=approved_by,
                items=prescription.as_rows(),
            )
            trace.event("artifact", {
                "critique": critique_id,
                "prescription": prescription_id,
            })
            if args.llm == "on":
                _narrate(conn, trace, critique, facts, prescription)

        _print_prescription(prescription)
        _print_critique(critique)
        return 0
    finally:
        store.close()


def _cmd_review(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        _ensure_imported(conn)
        facts = build_facts(conn, args.session)
        critique = score_session(conn, args.session, facts=facts)

        print(format_session_sheet(facts, critique))
        for line in item_guide_lines():
            print(line)

        if args.scores:
            from strength_coach.eval import load_labels

            labels = load_labels(args.scores)
            if args.session not in labels.sessions:
                print(f"{args.scores} has no marks for {args.session}")
                return 2
            scores = dict(labels.sessions[args.session].scores)
            confidence = args.confidence or labels.sessions[args.session].confidence
        else:
            scores = _ask_scores(critique)
            confidence = args.confidence or _ask_confidence()

        written = record_marks(
            conn,
            args.session,
            scores,
            confidence=confidence,
            rubric_version=RUBRIC_VERSION,
            note=args.note,
        )
        print(f"\nrecorded {written} marks for {args.session} (confidence {confidence})")
        _print_calibration(conn, DEFAULT_TOLERANCE)
        return 0
    finally:
        store.close()


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
        if args.import_file:
            if code := _import_state(conn, Path(args.import_file), force=args.force):
                return code
        _print_state(conn)
        return 0
    finally:
        store.close()


def _cmd_e1rm(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        if args.action == "list":
            _print_e1rm(conn)
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


def _cmd_test(args) -> int:
    """Record a strength test as a measured e1RM override.

    A test is an assessment, not a training set: it is deliberately not written into
    clean_sets, so it cannot count as volume or trip the RIR rule (a maximal test is RIR 0 by
    definition). The e1RM override is the durable record, and the prescription cites it.
    """
    store = db.Store(args.db)
    try:
        conn = store.connection
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
        print(f"recorded e1rm_override:{override_id}: {args.exercise} = {value:g} kg "
              f"from {on_date}")
        print("the next prescription uses it and cites the override")
        return 0
    finally:
        store.close()


def _cmd_symptom(args) -> int:
    store = db.Store(args.db)
    try:
        conn = store.connection
        if args.show or args.level is None:
            _print_symptoms(conn)
            return 0

        on_date = args.date or datetime.date.today().isoformat()
        settled = {"yes": True, "no": False, "unknown": None}.get(args.settled)
        repositories.append_symptom(
            conn,
            logged_on=on_date,
            timing="pre_session",
            region="low_back",
            level=args.level,
            settled_within_48h=settled,
            note=args.note,
        )
        print(f"logged back symptom {args.level}/3 on {on_date} (pre-session)")
        if args.level >= 2:
            print("that is a flare: MOD-BACK-001 will apply to the next prescription")
        elif args.level == 1 and settled is False:
            print("level 1 that did not settle is also a flare (DEC-SYMPTOM-02)")
        return 0
    finally:
        store.close()


def _print_symptoms(conn) -> None:
    entries = queries.symptom_entries(conn)
    if not entries:
        print("no symptom entries logged; back rules stay unknown until one exists")
        return
    print(f"{'date':<12}{'timing':<14}{'level':>6}  {'settled':<8} note")
    for row in entries[-20:]:
        settled = "-" if row["settled_within_48h"] is None else (
            "yes" if row["settled_within_48h"] else "no"
        )
        print(f"{row['logged_on']:<12}{row['timing']:<14}{row['level']:>6}  "
              f"{settled:<8} {row['note'] or ''}")


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

    print(f"recorded: profile 1, constraints {len(constraints)}, "
          f"suitability {len(exercises)}, metrics {len(raw.get('metrics') or [])}, "
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
    print(f"\nsymptom entries ({len(symptoms)})")


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

    if not args.yes:
        answer = input("  apply this proposal? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("  declined: keeping the deterministic prescription")
            trace.event("policy_verdict", {"proposal": "declined"})
            return prescription, "deterministic"

    trace.event("policy_verdict", {
        "proposal": "accepted", "changes": proposal_mod.describe(parsed),
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
    print(f"imported: {report.raw_rows_inserted} raw rows, "
          f"{report.clean_sets_inserted} clean sets, {report.sessions_written} sessions, "
          f"{report.readiness_days} readiness days, {report.quarantined} quarantined")


def _print_prescription(prescription) -> None:
    print(f"\nprescription {prescription.for_date}  "
          f"(day {prescription.session_day}, {prescription.fallback_level})")
    header = f"  {'exercise':<24}{'sets':>5}{'reps':>8}{'load':>9}{'rir':>5}  refs"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for item in prescription.items:
        load = "-" if item.load_kg is None else f"{item.load_kg:g}"
        reps = f"{item.reps_low}-{item.reps_high}"
        print(f"  {item.exercise_id:<24}{item.sets:>5}{reps:>8}{load:>9}"
              f"{item.rir_target:>5}  {', '.join(item.rationale_refs) or '-'}")
    if prescription.issues:
        print("  issues: " + "; ".join(prescription.issues))
    for warning in prescription.warnings:
        print(f"  note: {warning}")


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
