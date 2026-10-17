#!/usr/bin/env python
"""Print the athlete's current strength baseline from the raw CSVs.

    python tools/baseline.py                      # defaults to the latest date in the log
    python tools/baseline.py --as-of 2025-06-10 --window-days 84

Everything is computed by `strength_coach.features.baseline`; this file only formats.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.features import baseline  # noqa: E402
from strength_coach.utils import io_utils, reporting  # noqa: E402

# The constitution's primary compounds plus the lifts we track for context.
TRACKED = [
    "ssb_squat",
    "competition_squat",
    "bench_press",
    "bench_press_narrow",
    "bench_press_pause",
    "trap_bar_deadlift",
    "conventional_deadlift",
    "back_extension",
    "hyperextension",
    "rdl",
    "rack_pull",
    "good_morning",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=None,
                        help="YYYY-MM-DD; defaults to the most recent date in the log")
    parser.add_argument("--window-days", type=int, default=84)
    args = parser.parse_args(argv)

    training = io_utils.read_training_log()
    readiness = io_utils.read_readiness()

    if args.as_of is None:
        from strength_coach.utils import dates

        parsed = dates.parse_dates(training["Date"])
        args.as_of = parsed.max().date().isoformat()

    sets = baseline.prepare_sets(training, readiness)
    stats = baseline.session_stats(sets, as_of=args.as_of, window_days=args.window_days)
    wellness = baseline.readiness_summary(readiness, as_of=args.as_of, days=28)
    lifts = baseline.lift_baselines(
        sets, as_of=args.as_of, window_days=args.window_days, exercise_ids=TRACKED
    )

    latest_bw = _latest_bodyweight(readiness)

    print(reporting.section(f"BASELINE as of {args.as_of} (window {args.window_days}d)"))
    print(f"bodyweight: {latest_bw[0]} kg on {latest_bw[1]}")
    print(f"sessions/week (window): {stats['sessions_per_week']} | "
          f"median sets/session: {stats['median_sets_per_session']}")
    print(f"median weekly tonnage (added load): {stats['median_weekly_tonnage_kg']:.0f} kg"
          if stats["median_weekly_tonnage_kg"] else "median weekly tonnage: n/a")
    print(f"median weekly weighted spinal cost: {stats['weekly_spinal_cost_median']}")
    print(f"wellness 28d mean (1-5, higher better): {wellness}")

    print(reporting.section("TRACKED LIFTS"))
    header = (
        f"{'lift':26s}{'sets':>6s}{'/wk':>6s}{'best e1RM':>10s}{'method':>16s}"
        f"{'top':>7s}{'work':>7s}{'reps':>6s}{'RIR':>5s}{'vel':>6s}{'RIR%':>6s}{'last':>12s}"
    )
    print(header)
    for lift in lifts:
        print(
            f"{lift.display[:26]:26s}"
            f"{lift.sets_all_time:>6d}"
            f"{lift.sets_per_week_window:>6.2f}"
            f"{_fmt(lift.best_e1rm_kg, 1):>10s}"
            f"{(lift.best_e1rm_method or '-')[:16]:>16s}"
            f"{_fmt(lift.top_load_kg, 1):>7s}"
            f"{_fmt(lift.median_working_load_kg, 1):>7s}"
            f"{_fmt(lift.working_reps_median, 0):>6s}"
            f"{_fmt(lift.working_rir_median, 1):>5s}"
            f"{_fmt(lift.velocity_median_mps, 3):>6s}"
            f"{_fmt(lift.rir_compliance_pct, 0):>6s}"
            f"{(lift.last_trained or '-')[:12]:>12s}"
        )

    print("\ncolumn notes: 'work' = median load on sets with a usable RIR; "
          "'RIR%' = share of effort sets inside RIR 2-3; 'vel' = median measured velocity.")
    return 0


def _fmt(value, digits: int) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _latest_bodyweight(readiness) -> tuple[float | None, str | None]:
    from strength_coach.utils import dates, numeric

    frame = readiness.copy()
    frame["date"] = dates.parse_dates(frame["Date"])
    weight = numeric.coerce_numeric(frame["Weight"])
    valid = frame.assign(weight=weight).dropna(subset=["weight"])
    valid = valid[valid["weight"] > 0]
    if valid.empty:
        return None, None
    last = valid.sort_values("date").iloc[-1]
    return float(last["weight"]), last["date"].date().isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
