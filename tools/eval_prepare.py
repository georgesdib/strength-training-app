#!/usr/bin/env python
"""Print a labelling sheet for chosen sessions and write a skeleton label file.

This is the side-by-side view: the session as performed, then what the rubric scored. The human
mark goes into a separate YAML file so the comparison is against a judgement made outside the
engine, not a copy of its output.

    python tools/eval_prepare.py --session 2026-10-05 --session 2023-12-13 \
        --out private/eval/labelled.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.critique import build_facts, score_session  # noqa: E402
from strength_coach.eval.labels import ITEM_KEYS, LabelError, write_template  # noqa: E402
from strength_coach.store import db  # noqa: E402
from strength_coach.utils import paths  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", action="append", required=True,
                        help="session id (a date); repeat for several")
    parser.add_argument("--out", default=str(Path("private") / "eval" / "labelled.yaml"))
    parser.add_argument("--force", action="store_true", help="overwrite an existing label file")
    parser.add_argument("--db", default=None, help="database path (default: data/coach.db)")
    args = parser.parse_args(argv)

    if args.db is None and not paths.data_dir("coach.db").exists():
        print("no database yet; run an import first (python tools/import_export.py)")
        return 2

    store = db.Store(args.db)
    try:
        for session_id in args.session:
            _print_sheet(store.connection, session_id)
        try:
            path = write_template(args.out, args.session, overwrite=args.force)
        except LabelError as exc:
            print(f"\n{exc}")
            return 1
        print(f"\nwrote {path}")
        print("fill in the scores (0, 0.25, 0.5, 0.75, 1) and run tools/backtest.py")
    finally:
        store.close()
    return 0


def _print_sheet(conn, session_id: str) -> None:
    facts = build_facts(conn, session_id)
    critique = score_session(conn, session_id, facts=facts)

    print("\n" + "=" * 78)
    print(f"session {facts.session_id}  ({facts.occurred_on}, day {facts.day}, "
          f"label {facts.workout_label or 'none'})")
    print("=" * 78)

    working = facts.sets[facts.sets["is_working_set"]]
    print(f"working sets: {len(working)}   all sets: {len(facts.sets)}")
    print()
    header = f"{'exercise':<24}{'sets':>5}{'reps':>8}{'load kg':>14}{'rir':>10}"
    print(header)
    print("-" * len(header))
    for exercise_id, group in working.groupby("exercise_id"):
        reps = _range(group["reps"])
        loads = _range(group["load_kg"])
        rir = sorted({int(v) for v in group["rir"].dropna()})
        print(f"{exercise_id:<24}{len(group):>5}{reps:>8}{loads:>14}{str(rir):>10}")

    print("\nengine scores")
    print("-" * 60)
    for item in critique.items:
        if item.measurable and item.score is not None:
            print(f"  {item.key:<24}{item.score:>6.2f}   {item.detail[:60]}")
        else:
            print(f"  {item.key:<24}{'  n/a':>6}   {item.detail[:60]}")
    print(f"\n  composite {critique.composite:.2f}" if critique.composite is not None else "")
    print(f"\n  comments field: {', '.join(ITEM_KEYS)}")


def _range(values) -> str:
    clean = values.dropna()
    if clean.empty:
        return "-"
    low, high = clean.min(), clean.max()
    if low == high:
        return f"{low:g}"
    return f"{low:g}-{high:g}"


if __name__ == "__main__":
    raise SystemExit(main())
