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
import sys
from pathlib import Path

from strength_coach import __version__
from strength_coach.agents import (
    build_client,
    explain_critique,
    explain_prescription,
    load_settings,
)
from strength_coach.critique import UnknownSessionError, build_facts, score_session
from strength_coach.critique import persist as persist_critique
from strength_coach.critique.rubric import RUBRIC_VERSION
from strength_coach.eval import backtest, load_marks, record_marks
from strength_coach.eval.report import format_report, format_session_sheet, item_guide_lines
from strength_coach.prescribe import build_prescription
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
    run.add_argument("--llm", choices=("on", "off"), default="off",
                     help="ask the configured model for a narrative (default: off)")
    run.add_argument("--force", action="store_true",
                     help="regenerate even if this date was already prescribed")

    review = sub.add_parser("review", help="mark a session and update calibration")
    review.add_argument("--session", required=True)
    review.add_argument("--scores", default=None, help="read marks from a YAML file")
    review.add_argument("--confidence", choices=("high", "low", "unknown"), default=None)
    review.add_argument("--note", default=None)

    calibrate = sub.add_parser("calibrate", help="report agreement between rubric and marks")
    calibrate.add_argument("--tolerance", type=float, default=None)

    args = parser.parse_args(argv)
    handlers = {
        "import": _cmd_import,
        "run": _cmd_run,
        "review": _cmd_review,
        "calibrate": _cmd_calibrate,
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
        prescription = build_prescription(conn, for_date=args.date)

        with RunTrace.start(conn, input_hash=f"{session_id}:{args.date}",
                            window_end=args.date) as trace:
            critique_id = persist_critique(conn, critique, run_id=trace.run_id)
            prescription_id = repositories.append_prescription(
                conn,
                prescription_id=_new_id(),
                run_id=trace.run_id,
                for_date=prescription.for_date,
                session_day=prescription.session_day,
                fallback_level=prescription.fallback_level,
                rule_document_version=prescription.rule_document_version,
                calibration_ids=[],
                approved_by="deterministic",
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
