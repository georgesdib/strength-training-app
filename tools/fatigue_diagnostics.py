"""Run the Phase-1 fatigue diagnostics against the local database."""

from __future__ import annotations

import argparse
import json

from strength_coach.eval import fatigue_diagnostics
from strength_coach.store import db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    parser.add_argument("--lift", action="append", default=None)
    parser.add_argument("--max-observations", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    store = db.Store(args.db)
    try:
        report = fatigue_diagnostics.diagnose(
            store.connection,
            lifts=tuple(args.lift) if args.lift else fatigue_diagnostics.PRIMARY_LIFTS,
            max_observations=args.max_observations,
        )
    finally:
        store.close()
    print(json.dumps(report, indent=2) if args.json
          else fatigue_diagnostics.format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
