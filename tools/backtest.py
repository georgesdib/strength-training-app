#!/usr/bin/env python
"""Compare the rubric against a hand-marked set.

    python tools/backtest.py                                  # private/eval/labelled.yaml
    python tools/backtest.py --labels path/to/labels.yaml
    python tools/backtest.py --prescriptions                  # also replay the day's prescription

Agreement is reported per session and per rubric item, so a systematically wrong line shows up
instead of hiding inside an average.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.eval import LabelError, backtest, load_labels, load_marks  # noqa: E402
from strength_coach.eval.report import format_report  # noqa: E402
from strength_coach.prescribe import build_prescription  # noqa: E402
from strength_coach.store import db  # noqa: E402
from strength_coach.utils import paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", default=None,
                        help="read marks from a YAML file instead of the database")
    parser.add_argument("--tolerance", type=float, default=None,
                        help="absolute difference treated as agreement (default: from labels)")
    parser.add_argument("--prescriptions", action="store_true",
                        help="also replay the Day B prescription for each session date")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    if args.labels is not None:
        try:
            labels = load_labels(args.labels)
        except LabelError as exc:
            print(f"labels: {exc}")
            return 2
        store = db.Store(args.db)
    else:
        if args.db is None and not paths.data_dir("coach.db").exists():
            print("no database yet; run tools/import_export.py first")
            return 2
        store = db.Store(args.db)
        labels = load_marks(store.connection)
        if not labels.sessions:
            print("no marks yet; review a session first (strength-coach review --session DATE)")
            store.close()
            return 2

    try:
        report = backtest(store.connection, labels, tolerance=args.tolerance)
        print(format_report(report))
        if args.prescriptions:
            _print_prescriptions(store.connection, labels)
    finally:
        store.close()
    return 0


def _print_prescriptions(conn, labels) -> None:
    print("\nprescriptions replayed as of each session date")
    for session_id in labels.sessions:
        prescription = build_prescription(conn, for_date=session_id)
        status = "executable" if prescription.executable else "NOT executable"
        print(f"  {session_id}: {status}")
        for issue in prescription.issues:
            print(f"      {issue}")


if __name__ == "__main__":
    raise SystemExit(main())
