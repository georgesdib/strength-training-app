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

from strength_coach.eval import LabelError, backtest, load_labels  # noqa: E402
from strength_coach.prescribe import build_prescription  # noqa: E402
from strength_coach.store import db  # noqa: E402
from strength_coach.utils import paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", default=str(Path("private") / "eval" / "labelled.yaml"))
    parser.add_argument("--tolerance", type=float, default=None,
                        help="absolute difference treated as agreement (default: from labels)")
    parser.add_argument("--prescriptions", action="store_true",
                        help="also replay the Day B prescription for each session date")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    try:
        labels = load_labels(args.labels)
    except LabelError as exc:
        print(f"labels: {exc}")
        return 2

    if args.db is None and not paths.data_dir("coach.db").exists():
        print("no database yet; run an import first")
        return 2

    store = db.Store(args.db)
    try:
        report = backtest(store.connection, labels, tolerance=args.tolerance)
        _print_report(report)
        if args.prescriptions:
            _print_prescriptions(store.connection, labels)
    finally:
        store.close()
    return 0


def _print_report(report) -> None:
    print(f"tolerance: +/-{report.tolerance:g}")
    print()
    header = f"{'session':<14}{'compared':>10}{'agreement':>11}{'mae':>8}  disagreements"
    print(header)
    print("-" * (len(header) + 20))
    for session in report.sessions:
        compared = len(session.comparable_items)
        agreement = "-" if session.agreement_rate is None else f"{session.agreement_rate:.0%}"
        mae = "-" if session.mean_abs_error is None else f"{session.mean_abs_error:.2f}"
        print(f"{session.session_id:<14}{compared:>10}{agreement:>11}{mae:>8}  "
              f"{', '.join(session.disagreements) or '-'}")

    overall = report.agreement_rate
    print()
    print(f"overall: {len(report.comparable_items)} comparable items, "
          f"agreement {'-' if overall is None else f'{overall:.0%}'}, "
          f"mean absolute error {'-' if report.mean_abs_error is None else f'{report.mean_abs_error:.2f}'}")

    print("\nper item")
    print(f"  {'item':<24}{'n':>4}{'agreement':>11}{'mae':>8}")
    for key, stats in report.per_item.items():
        agreement = "-" if stats["agreement"] is None else f"{stats['agreement']:.0%}"
        mae = "-" if stats["mae"] is None else f"{stats['mae']:.2f}"
        print(f"  {key:<24}{stats['n']:>4}{agreement:>11}{mae:>8}")


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
