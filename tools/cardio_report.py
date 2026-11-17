#!/usr/bin/env python
"""Report activity coverage and cardio minutes from the canonical corpus.

    python tools/cardio_report.py --db data/coach.db
    python tools/cardio_report.py --db data/coach.db --since 2026-01-01 --weeks 12

Read-only. Every figure names the tier that produced it; unclassified time is its own quantity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.features import cardio_metrics  # noqa: E402
from strength_coach.store import db  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--since", default=None, help="ISO date; ignore workouts before it")
    parser.add_argument("--weeks", type=int, default=104, help="how many ISO weeks to include")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    try:
        payload = cardio_metrics.report(conn, since=args.since, weeks_limit=args.weeks)
    finally:
        conn.close()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
