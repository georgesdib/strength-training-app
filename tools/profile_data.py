#!/usr/bin/env python
"""Regenerate every number in docs/EVIDENCE.md from the raw CSVs.

This is not analysis code: it computes nothing that `strength_coach.utils` does not
already provide. Its only job is to prove the evidence is reproducible.

    python tools/profile_data.py
    python tools/profile_data.py --section main_lifts
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.utils import (  # noqa: E402
    dates,
    exercises,
    io_utils,
    numeric,
    paths,
    reporting,
    stats,
)

NUMERIC_COLUMNS = ["Weight_Used", "Reps_Done", "RIR", "Avg_velocity", "Avg_rom", "TUT", "ExertionLoad"]


def load_training() -> pd.DataFrame:
    frame = io_utils.read_training_log()
    frame["source_row"] = io_utils.source_row_ids(frame)
    frame["date"] = dates.parse_dates(frame["Date"])
    # Date-scoped identity (DEC-TRAPBAR-02): "Competition Deadlift" was sumo before the
    # switch and trap bar after it, so a plain name map would merge two lifts.
    day_strings = frame["date"].dt.strftime("%Y-%m-%d")
    frame["exercise_id"] = [
        exercises.canonical_id(name, day)
        for name, day in zip(frame["Exercise"], day_strings, strict=True)
    ]
    return numeric.coerce_frame(frame, NUMERIC_COLUMNS)


def load_readiness() -> pd.DataFrame:
    frame = io_utils.read_readiness()
    frame["source_row"] = io_utils.source_row_ids(frame)
    frame["date"] = dates.parse_dates(frame["Date"])
    frame = numeric.coerce_frame(
        frame, [c for c in frame.columns if c not in {"Date", "date", "source_row"}]
    )
    # 0 means "missing" for these fields, so applying the sentinel map is required before
    # any summary (otherwise bodyweight averages are dragged towards zero).
    return numeric.apply_zero_sentinels(frame)


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #
def section_shape(training: pd.DataFrame, readiness: pd.DataFrame) -> None:
    print(reporting.section("SHAPE AND SPAN"))
    print(f"training rows={len(training)} distinct_dates={training['date'].nunique()} "
          f"null_date_rows={int(training['date'].isna().sum())}")
    print(f"readiness rows={len(readiness)} distinct_dates={readiness['date'].nunique()}")
    print(f"training range {training['date'].min().date()} -> {training['date'].max().date()}")
    overlap = set(training["date"].dropna().dt.date) & set(readiness["date"].dropna().dt.date)
    print(f"overlap days: {len(overlap)} / {training['date'].nunique()}")
    print(f"chronologically ordered: {training['date'].dropna().is_monotonic_increasing}")


def section_cadence(training: pd.DataFrame) -> None:
    print(reporting.section("SESSIONS PER ISO WEEK"))
    valid = training.dropna(subset=["date"])
    per_week = valid.groupby(valid["date"].dt.strftime("%G-W%V"))["date"].nunique()
    table = reporting.with_percent(reporting.count_table(per_week, label="sessions_in_week"))
    print(reporting.format_table(table))
    sets_per_session = valid.groupby("date").size()
    print(f"sets/session: {stats.describe(sets_per_session)}")


def section_main_lifts(training: pd.DataFrame) -> None:
    print(reporting.section("MAIN LIFTS BY YEAR"))
    ids = ["ssb_squat", "competition_squat", "bench_press", "bench_press_narrow",
           "trap_bar_deadlift", "sumo_deadlift", "back_extension", "hyperextension", "rdl",
           "rack_pull", "good_morning"]
    years = sorted(training["date"].dt.year.dropna().unique())
    header = f"{'exercise_id':24s}" + "".join(f"{int(y):>7d}" for y in years)
    print(header)
    for exercise_id in ids:
        subset = training[training["exercise_id"] == exercise_id]
        counts = [int((subset["date"].dt.year == y).sum()) for y in years]
        print(f"{exercise_id:24s}" + "".join(f"{c:>7d}" for c in counts))
    unmatched = exercises.taxonomy().unmatched(training["Exercise"].unique())
    print(f"\nunresolved names: {len(unmatched)}")
    if unmatched:
        print("  " + ", ".join(unmatched))


def section_telemetry(training: pd.DataFrame) -> None:
    print(reporting.section("TELEMETRY COVERAGE"))
    present = training["Avg_velocity"] > 0
    print(f"rows with velocity>0: {int(present.sum())} of {len(training)}")
    print(f"velocity==0 but TUT>0:     {int(((training['Avg_velocity'] == 0) & (training['TUT'] > 0)).sum())}")
    print(f"velocity==0 but Avg_rom>0: {int(((training['Avg_velocity'] == 0) & (training['Avg_rom'] > 0)).sum())}")
    print("\nper main lift:")
    for exercise_id in ["bench_press", "competition_squat", "trap_bar_deadlift",
                        "ssb_squat", "bench_press_narrow"]:
        subset = training[training["exercise_id"] == exercise_id]
        clean = subset[(subset["Avg_velocity"] > 0) & subset["RIR"].isin([2, 3])
                       & subset["Reps_Done"].between(1, 8)]
        print(f"  {exercise_id:24s} sets={len(subset):4d} "
              f"velocity={int((subset['Avg_velocity'] > 0).sum()):4d} "
              f"clean_vbt={len(clean):4d}")


def section_rir(training: pd.DataFrame) -> None:
    print(reporting.section("RIR DISTRIBUTION"))
    # Null-date rows are quarantined (DQ-NULLDATE-01) and carry a suspect RIR, so
    # including them would fabricate violations. Analysis excludes them.
    dated = training.dropna(subset=["date"])
    print(f"(excluding {len(training) - len(dated)} quarantined null-date rows)")
    print(reporting.format_table(reporting.count_table(training["RIR"], label="RIR")))
    print("\nmain-lift sets at RIR 0/1 (potential hard-rule violations, dated rows only):")
    for exercise_id in ["ssb_squat", "competition_squat", "bench_press", "trap_bar_deadlift"]:
        subset = dated[dated["exercise_id"] == exercise_id]
        bad = int(subset["RIR"].isin([0, 1]).sum())
        print(f"  {exercise_id:24s} {bad:4d} of {len(subset):4d}")


def section_bodyweight(training: pd.DataFrame, readiness: pd.DataFrame) -> None:
    print(reporting.section("BODYWEIGHT LOAD CONVENTION"))
    weight = readiness["Weight"].dropna()
    print(f"readiness bodyweight non-null range: {weight.min():.1f} - {weight.max():.1f} kg "
          f"(median {weight.median():.1f})")
    for exercise_id in ["ab_wheel", "pull_up", "plank", "hyperextension", "hanging_leg_raise"]:
        subset = training[training["exercise_id"] == exercise_id]
        if subset.empty:
            continue
        loads = subset["Weight_Used"].dropna()
        print(f"  {exercise_id:20s} sets={len(subset):4d} zeros={int((loads == 0).sum()):4d} "
              f"max={loads.max():7.1f} median={loads.median():7.1f}")


def section_duplicates(training: pd.DataFrame, readiness: pd.DataFrame) -> None:
    print(reporting.section("DUPLICATE SEMANTICS"))
    keys = ["Date", "Workout", "Exercise", "Weight_Used", "Reps_Done", "RIR",
            "Avg_velocity", "Avg_rom", "TUT"]
    sizes = training.groupby(keys).size()
    print("identical-set group sizes (training):")
    print(reporting.format_table(reporting.count_table(sizes, label="copies")))
    print("\nreadiness duplicate diagnostics:")
    print(f"  rows={len(readiness)} dates={readiness['Date'].nunique()} "
          f"exact_full_row_dupes={int(readiness.duplicated(keep=False).sum())}")
    per_date = readiness.groupby("Date").nunique()
    print(f"  dates with >1 row: {int((readiness['Date'].value_counts() > 1).sum())}")
    print(f"  dates with conflicting rows: {int((per_date.max(axis=1) > 1).sum())}")


def section_spinal(training: pd.DataFrame) -> None:
    print(reporting.section("SPINAL EXPOSURE"))
    high = training[training["exercise_id"].map(
        lambda e: bool(exercises.taxonomy().resolve(e) and exercises.taxonomy().resolve(e).is_high_fatigue_spinal)
    )]
    per_date = high.groupby("date")["exercise_id"].nunique()
    per_week = high.groupby(high["date"].dt.strftime("%G-W%V"))["exercise_id"].nunique()
    print("distinct high-fatigue exercises per DATE:")
    print(reporting.format_table(reporting.count_table(per_date, label="distinct")))
    print("\ndistinct high-fatigue exercises per WEEK:")
    print(reporting.format_table(reporting.count_table(per_week, label="distinct")))
    print(f"weeks with >=3: {int((per_week >= 3).sum())} of {len(per_week)}")


def section_rotation(training: pd.DataFrame) -> None:
    print(reporting.section("EXERCISE ROTATION"))
    valid = training.dropna(subset=["date"])
    per_session = valid.groupby("date")["exercise_id"].nunique()
    print(f"distinct exercises per session: {stats.describe(per_session)}")
    sessions = valid.groupby("date")["exercise_id"].apply(lambda s: set(s)).sort_index()
    values = list(sessions)
    carry: list[float] = []
    for i in range(len(values) - 1):
        upcoming = set().union(*values[i + 1: min(i + 4, len(values))])
        if values[i]:
            carry.append(len(values[i] & upcoming) / len(values[i]))
    print(f"mean fraction of a session's exercises reappearing within 3 sessions: "
          f"{stats.median(carry):.2f}")


SECTIONS = {
    "shape": (section_shape, True),
    "cadence": (section_cadence, False),
    "main_lifts": (section_main_lifts, False),
    "telemetry": (section_telemetry, False),
    "rir": (section_rir, False),
    "bodyweight": (section_bodyweight, True),
    "duplicates": (section_duplicates, True),
    "spinal": (section_spinal, False),
    "rotation": (section_rotation, False),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", choices=sorted(SECTIONS), default=None)
    parser.add_argument("--training-csv", default=None)
    parser.add_argument("--readiness-csv", default=None)
    args = parser.parse_args(argv)

    training = load_training() if not args.training_csv else _load(io_utils.read_training_log(args.training_csv))
    readiness = load_readiness() if not args.readiness_csv else _load(io_utils.read_readiness(args.readiness_csv))
    print(f"taxonomy: {exercises.taxonomy().version}  ({paths.taxonomy_yaml()})")

    for name, (function, needs_both) in SECTIONS.items():
        if args.section and name != args.section:
            continue
        function(training, readiness) if needs_both else function(training)
    return 0


def _load(frame: pd.DataFrame) -> pd.DataFrame:
    frame["date"] = dates.parse_dates(frame["Date"])
    return numeric.coerce_frame(frame, [c for c in NUMERIC_COLUMNS if c in frame.columns])


if __name__ == "__main__":
    raise SystemExit(main())
