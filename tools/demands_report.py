#!/usr/bin/env python
"""Report demand-catalogue coverage over the exercise ids the programme can prescribe.

    python tools/demands_report.py          # human table
    python tools/demands_report.py --json   # machine-readable, for docs/tests

Coverage is reported against the ids reachable from the shipped templates and their configured
selection candidates: an id outside that set is never shown in the programme, so rating it is
not a priority. The rate is computed per dimension because the dimensions are independent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.features import demands  # noqa: E402
from strength_coach.prescribe.demand_scope import reachable_ids  # noqa: E402


def report() -> dict:
    catalogue = demands.load()
    coverage = catalogue.coverage(reachable_ids())
    coverage["unrated_ids"] = [
        exercise_id for exercise_id in reachable_ids()
        if not any(catalogue.rated(exercise_id, dimension) for dimension in demands.DIMENSIONS)
    ]
    coverage["source"] = str(catalogue.source_path)
    return coverage


def render(data: dict) -> str:
    lines = [
        f"demand catalogue: {data['rated_exercises']}/{data['total']} exercises rated "
        f"(digest {data['digest'] or 'none'}, reviewed {data['reviewed_on'] or 'never'})",
        f"  {'dimension':<18}{'rated':>6}{'unknown':>9}{'rate':>8}{'supported':>11}{'provisional':>13}",
    ]
    for dimension, row in data["per_dimension"].items():
        lines.append(
            f"  {dimension:<18}{row['rated']:>6}{row['unknown']:>9}"
            f"{row['unknown_rate'] * 100:>7.1f}%{row['supported']:>11}{row['provisional']:>13}"
        )
    if data["unrated_ids"]:
        lines.append("  unrated: " + ", ".join(data["unrated_ids"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    data = report()
    print(json.dumps(data, indent=2, sort_keys=True) if args.json else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
