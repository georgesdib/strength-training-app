#!/usr/bin/env python
"""Report whether per-set heart-rate recovery is worth revisiting (read-only).

    python tools/hr_recovery_probe.py --db data/coach.db

Why this exists
---------------
It decides with measurement whether per-set heart-rate recovery deserves product work, and it is
the command the Today review card points at. The metric itself lives in one place,
`strength_coach.features.hr_recovery`, so this CLI and the card cannot disagree; the module also
owns the derivation the History screen displays per set.

What it is not
--------------
Not a feature, an endpoint or a migration. Nothing imports this CLI, no table is written, and the
database is opened read-only through a `file:...?mode=ro` URI. It reads like a throwaway probe on
purpose: delete it once the question is settled.

Privacy
-------
Heart rate is health data. The report is aggregates only -- counts, medians, standard deviations,
correlations and verdicts. No sample, timestamp or session identifier is printed, so the output is
safe to paste into an issue or a commit message. Run it on the host that holds the database rather
than copying the database somewhere else.

Decision rule (fixed before the first run, so a re-run cannot be reinterpreted afterwards)
-----------------------------------------------------------------------------------------
* coverage >= 0.70 -- both endpoints exist for most sets, else the idea is unbuildable;
* within-session SD < between-session SD -- else set-to-set noise *is* the metric;
* |corr(delta, load)| <= 0.40 -- else the metric re-encodes how hard the set was, which the
  prescription already knows.

Baseline, 2026-11-22 (4 sessions, 71 set completions, 64 matched): coverage 0.901,
within-SD 12.8 bpm vs between-SD 7.1 bpm, corr(delta, load) +0.283. Verdict: not worth pursuing.
Re-run once the review card has 15 watch sessions to read from.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.features import hr_recovery  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", required=True, help="path to coach.db; opened read-only")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        report = hr_recovery.report(conn)
    finally:
        conn.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
