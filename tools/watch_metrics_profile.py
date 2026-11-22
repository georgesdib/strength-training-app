#!/usr/bin/env python
"""WP1 analysis for the watch motion metrics plan — read-only aggregates.

Specification: portfolio docs/plans/WATCH-MOTION-METRICS.md section 15.

This tool answers one question before any watch work starts: is there enough
history, and enough resolution in it, for tempo and device velocity to be worth
building? It emits aggregates only. No set-level row is ever printed, so the
output can be pasted into a decision record without leaking a training log.

    python tools/watch_metrics_profile.py
    python tools/watch_metrics_profile.py --section o2
    python tools/watch_metrics_profile.py --db data/coach.db --months 12

The database is opened read-only and the connection is put in query_only mode;
the tool cannot write even if a later edit tries to.

Eligibility is not re-implemented here. Section 15 requires that the study
population match the population production actually calibrates from, so every
band and exclusion number comes from features.vbt_calibration itself.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.features import derived, vbt_calibration  # noqa: E402
from strength_coach.store import db as db_mod  # noqa: E402
from strength_coach.store import queries  # noqa: E402
from strength_coach.utils import exercises, reporting, stats  # noqa: E402

SECTIONS = ("o0", "o1", "o2", "o3", "o4", "o5")

# The noise grid for O4, as a fraction of a group's median velocity.
NOISE_GRID = (0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15)
NOISE_DRAWS = 60
NOISE_SEED = 20261122


@dataclass
class Context:
    sets: pd.DataFrame
    reps: pd.DataFrame
    family_of: dict[str, str | None]
    conn: sqlite3.Connection


# --- loading ---------------------------------------------------------------


def open_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    # The store's queries build dicts from rows; read-only has no other difference.
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA query_only = ON")
    if conn.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise SystemExit("refusing to run: connection is not read-only")
    return conn


def load_context(conn: sqlite3.Connection) -> Context:
    sets = derived.enrich(queries.clean_sets(conn))
    sets["date"] = pd.to_datetime(sets["date"], errors="coerce")
    family_of = {
        eid: entity.get("vbt_family")
        for eid, entity in exercises.taxonomy().entities.items()
    }
    reps = pd.read_sql_query(
        "SELECT clean_set_id, rep_index, velocity_mps FROM clean_rep", conn
    )
    return Context(sets=sets, reps=reps, family_of=family_of, conn=conn)


def with_family(frame: pd.DataFrame, family_of: dict[str, str | None]) -> pd.DataFrame:
    out = frame.copy()
    out["family"] = out["exercise_id"].map(lambda e: family_of.get(e))
    return out


def pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else float("nan")


# --- O0: population rate of the fields that already exist -------------------


def o0_field_population(ctx: Context) -> pd.DataFrame:
    work = with_family(ctx.sets, ctx.family_of)
    work = work[work["is_working_set"].astype(bool)]
    rows = []
    for family, group in work.groupby(work["family"].fillna("(none)"), dropna=False):
        n = len(group)
        rows.append(
            {
                "family": family,
                "sets": n,
                "velocity%": pct(int(group["velocity_present"].sum()), n),
                "tut%": pct(int(group["tut_s"].notna().sum()), n),
                "rom%": pct(int(group["rom_mm"].notna().sum()), n),
                "form%": pct(int(group["form_score"].notna().sum()), n),
            }
        )
    table = pd.DataFrame(rows).sort_values("sets", ascending=False)
    power = ctx.conn.execute(
        "SELECT COUNT(*), SUM(power_w IS NOT NULL) FROM clean_set"
    ).fetchone()
    print(reporting.section("O0  EXISTING-FIELD POPULATION (working sets)"))
    print(reporting.format_table(table))
    print()
    print(
        f"power_w populated on {int(power[1] or 0)} of {int(power[0])} clean sets "
        "(set-level column, not in the domain frame)"
    )
    print(
        "reading: velocity% is the historical base for velocity targets; tut%/rom% "
        "are the historical base for tempo."
    )
    return table


# --- O1: per-rep coverage ---------------------------------------------------


def complete_rep_sets(ctx: Context) -> pd.DataFrame:
    """One row per set that has rep detail, with a completeness flag."""
    ids = set(ctx.sets["set_id"].tolist())
    reps = ctx.reps[ctx.reps["clean_set_id"].isin(ids)]
    reps = reps.sort_values(["clean_set_id", "rep_index"])
    agg = reps.groupby("clean_set_id", sort=False).agg(
        rep_rows=("rep_index", "size"),
        v_first=("velocity_mps", "first"),
        v_last=("velocity_mps", "last"),
        v_min=("velocity_mps", "min"),
    )
    merged = ctx.sets.merge(agg, left_on="set_id", right_index=True, how="inner")
    merged["complete"] = (
        merged["rep_rows"].eq(merged["reps"])
        & merged["reps"].fillna(0).ge(2)
        & merged["v_first"].gt(0)
        & merged["v_min"].gt(0)
    )
    return merged


def o1_rep_coverage(ctx: Context, quarters: int) -> pd.DataFrame:
    work = with_family(ctx.sets, ctx.family_of)
    work = work[work["is_working_set"].astype(bool)].copy()
    work["quarter"] = pd.PeriodIndex(work["date"], freq="Q").astype(str)
    recent = sorted(work["quarter"].dropna().unique())[-quarters:]

    complete = complete_rep_sets(ctx)
    complete_ids = set(complete.loc[complete["complete"], "set_id"].tolist())
    any_rep_ids = set(ctx.reps["clean_set_id"].tolist())

    rows = []
    for family, group in work.groupby(work["family"].fillna("(none)"), dropna=False):
        ids = group["set_id"]
        n = len(group)
        rows.append(
            {
                "family": family,
                "sets": n,
                "any-rep%": pct(int(ids.isin(any_rep_ids).sum()), n),
                "complete%": pct(int(ids.isin(complete_ids).sum()), n),
            }
        )
    table = pd.DataFrame(rows).sort_values("sets", ascending=False)

    recent_frame = work[work["quarter"].isin(recent)].copy()
    recent_frame["complete"] = recent_frame["set_id"].isin(complete_ids)
    by_quarter = (
        recent_frame.groupby(["quarter", "family"], dropna=False)
        .agg(sets=("set_id", "size"), complete=("complete", "sum"))
        .reset_index()
    )

    print(reporting.section("O1  PER-REP COVERAGE (working sets)"))
    print(reporting.format_table(table))
    print()
    print(f"complete per-rep sets in the last {len(recent)} quarters:")
    print(reporting.format_table(by_quarter))
    print(
        "reading: fewer than 50 complete sets per family means the loss "
        "distribution must come from the study, not history."
    )
    return table


# --- O2: the velocity-loss distribution (the G2 target) --------------------


def o2_loss_distribution(ctx: Context) -> tuple[pd.DataFrame, dict]:
    complete = complete_rep_sets(ctx)
    complete = complete[complete["complete"]].copy()
    complete["loss_pct"] = (complete["v_first"] - complete["v_last"]) / complete["v_first"] * 100
    grouped = with_family(complete, ctx.family_of)
    rows = []
    for family, group in grouped.groupby(grouped["family"].fillna("(none)"), dropna=False):
        values = group["loss_pct"].to_numpy(dtype="float64")
        rows.append(
            {
                "family": family,
                "sets": values.size,
                "median": round(float(np.median(values)), 1),
                "p25": round(float(np.percentile(values, 25)), 1),
                "p75": round(float(np.percentile(values, 75)), 1),
                "p90": round(float(np.percentile(values, 90)), 1),
                ">10%": pct(int((values > 10).sum()), values.size),
                ">20%": pct(int((values > 20).sum()), values.size),
                ">30%": pct(int((values > 30).sum()), values.size),
            }
        )
    table = pd.DataFrame(rows).sort_values("sets", ascending=False)
    print(reporting.section("O2  WITHIN-SET VELOCITY LOSS  (v1 -> vn, percent of v1)"))
    if table.empty:
        print("no complete per-rep sets — O2 needs manual per-rep entry to exist")
        return table, {"sets": 0}
    print(reporting.format_table(table))
    print()
    print("families with fewer than 5 sets are noise, not evidence.")
    values = complete["loss_pct"].to_numpy(dtype="float64")
    summary = {
        "sets": int(values.size),
        "median": round(float(np.median(values)), 1),
        "increasing": pct(int((values < 0).sum()), values.size),
        "suspect": int((np.abs(values) > 100).sum()),
    }
    print()
    print(
        f"pooled: {summary['sets']} complete sets, median loss {summary['median']:.1f}%, "
        f"{summary['increasing']}% of sets got faster ({summary['suspect']} beyond +/-100%)"
    )
    print(
        "reading: under 8% -> wrist velocity cannot resolve it; 10-25% -> worth "
        "pursuing if O4's tolerable error is at least 5-8%."
    )
    return table, summary


# --- O3: band width --------------------------------------------------------


def target_frame(result: vbt_calibration.CalibrationResult) -> pd.DataFrame:
    rows = []
    for target in result.targets:
        if not target.velocity_median or target.velocity_low is None:
            continue
        width = float(target.velocity_high) - float(target.velocity_low)
        rows.append(
            {
                "family": target.vbt_family or "(none)",
                "exercise": target.exercise_id,
                "scope": target.scope,
                "reps": target.rep_count,
                "rir": f"{target.rir_band[0]}-{target.rir_band[1]}",
                "n": target.n_sets,
                "median": round(float(target.velocity_median), 3),
                "mad": round(float(target.velocity_mad), 3) if target.velocity_mad else None,
                "low": round(float(target.velocity_low), 3),
                "high": round(float(target.velocity_high), 3),
                "width_pct": round(100.0 * width / float(target.velocity_median), 1),
            }
        )
    return pd.DataFrame(rows)


def o3_band_widths(
    targets: pd.DataFrame, result: vbt_calibration.CalibrationResult
) -> pd.DataFrame:
    print(reporting.section("O3  CALIBRATION BAND WIDTH (production eligibility)"))
    if targets.empty:
        print("no calibration targets — the lift/family sample is too thin")
        return targets
    # A family target is emitted once per member exercise with identical statistics;
    # show it once.
    shown = targets.drop_duplicates(
        subset=["family", "scope", "reps", "median", "low", "high", "n"]
    )
    print(reporting.format_table(shown.sort_values(["family", "reps"])))
    print()
    print("exclusions, production definition:")
    for reason, count in sorted(result.excluded.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:22s} {count}")
    print(
        "reading: width_pct is the error the band already absorbs. A band at 10 "
        "percent tolerates roughly a third of that as measurement error."
    )
    return targets


# --- O4: error budget ------------------------------------------------------


EDGE_LIMIT = 0.10  # band edge may move at most this fraction of the band width


def tolerable_noise(
    *, median: float, mad: float, n_sets: int, rng: np.random.Generator
) -> dict:
    """Smallest relative noise that moves a band edge by more than 10% of its width.

    Edge movement, not per-set membership flips, is what G3 asks: a recomputed
    target must stay put. Membership flips are dominated by sets sitting on the
    boundary and say nothing about the target's stability.
    """
    spread = max(float(mad), float(median) * 0.05)
    base = rng.normal(float(median), spread, int(n_sets))
    low0, high0 = stats.robust_band(base, k=2.0, min_relative_spread=0.05)
    width0 = float(high0) - float(low0)
    inside0 = (base >= low0) & (base <= high0)

    rows = []
    for relative in NOISE_GRID:
        shift = 0.0
        flips = 0.0
        for _ in range(NOISE_DRAWS):
            measured = base + rng.normal(0.0, float(median) * relative, int(n_sets))
            low1, high1 = stats.robust_band(measured, k=2.0, min_relative_spread=0.05)
            shift += max(abs(float(low1) - low0), abs(float(high1) - high0)) / width0
            inside1 = (measured >= low1) & (measured <= high1)
            flips += float(np.mean(inside0 != inside1))
        rows.append((relative, shift / NOISE_DRAWS, flips / NOISE_DRAWS))

    for relative, shift, flips in rows:
        if shift > EDGE_LIMIT:
            return {
                "relative": relative,
                "edge_shift": shift,
                "flip": flips,
            }
    relative, shift, flips = rows[-1]
    return {"relative": None, "edge_shift": shift, "flip": flips}


MIN_GROUP = 24


def o4_error_budget(targets: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    if targets.empty:
        print(reporting.section("O4  ERROR BUDGET (band-edge stability)"))
        print("no targets — O4 cannot run")
        return pd.DataFrame(), {"groups": 0}
    rng = np.random.default_rng(NOISE_SEED)
    rows = []
    lift_targets = targets[
        targets["scope"].eq("lift")
        & targets["mad"].notna()
        & targets["n"].ge(MIN_GROUP)
    ]
    for _, row in lift_targets.iterrows():
        outcome = tolerable_noise(
            median=float(row["median"]),
            mad=float(row["mad"]),
            n_sets=int(row["n"]),
            rng=rng,
        )
        relative = outcome["relative"]
        rows.append(
            {
                "family": row["family"],
                "exercise": row["exercise"],
                "reps": int(row["reps"]),
                "n": int(row["n"]),
                "median": row["median"],
                "tolerable%": round(relative * 100, 1) if relative is not None else None,
                "tolerable_mps": (
                    round(float(row["median"]) * relative, 3)
                    if relative is not None
                    else None
                ),
                "edge_shift%": round(outcome["edge_shift"] * 100, 1),
                "flip%": round(outcome["flip"] * 100, 1),
            }
        )
    table = pd.DataFrame(rows)
    print(reporting.section("O4  ERROR BUDGET (band-edge stability)"))
    if table.empty:
        print(f"no lift-scope targets with n >= {MIN_GROUP} and a usable MAD — O4 cannot run yet")
        return table, {"groups": 0}
    print(reporting.format_table(table.sort_values(["family", "reps"])))
    floored = table["tolerable_mps"].dropna()
    summary = {"groups": int(len(floored))}
    if not floored.empty:
        summary["median_mps"] = round(float(floored.median()), 3)
        summary["median_pct"] = round(float(floored.median() / table["median"].median()) * 100, 1)
        print()
        print(
            f"qualifying targets: {int(floored.size)}; median tolerable error "
            f"{summary['median_mps']:.3f} m/s ({summary['median_pct']:.1f}% of median velocity)"
        )
    print(
        "reading: tolerable_mps is the measurement error that keeps the band edge "
        "within 10% of its width. Under 0.02 m/s, a wrist sensor is unlikely to "
        "pass; above 0.05 m/s the velocity track is worth the study."
    )
    return table, summary


# --- O5: calendar reality --------------------------------------------------


def o5_calendar(ctx: Context, months: int) -> pd.DataFrame:
    work = with_family(ctx.sets, ctx.family_of)
    work = work[work["is_working_set"].astype(bool)].copy()
    work["month"] = pd.PeriodIndex(work["date"], freq="M")
    recent = sorted(work["month"].dropna().unique())[-months:]
    window = work[work["month"].isin(recent)].copy()

    complete = complete_rep_sets(ctx)
    complete_ids = set(complete.loc[complete["complete"], "set_id"].tolist())
    window["velocity"] = window["velocity_present"].astype(bool)
    window["complete"] = window["set_id"].isin(complete_ids)

    rows = []
    for family, group in window.groupby(window["family"].fillna("(none)"), dropna=False):
        span = max(1, int(group["month"].nunique()))
        rows.append(
            {
                "family": family,
                "months": span,
                "sets/mo": round(len(group) / span, 1),
                "velocity/mo": round(int(group["velocity"].sum()) / span, 1),
                "complete/mo": round(int(group["complete"].sum()) / span, 1),
            }
        )
    table = pd.DataFrame(rows).sort_values("velocity/mo", ascending=False)
    print(reporting.section(f"O5  CALENDAR REALITY (last {len(recent)} months)"))
    print(reporting.format_table(table))
    print(
        "reading: under 12 velocity sets per family per month means a long "
        "calibration runway; limit v1 to the four main lifts."
    )
    return table


# --- decision summary ------------------------------------------------------


MIN_LOSS_SETS = 50


def decision_summary(o1: pd.DataFrame, o2: dict, o4: dict) -> None:
    print(reporting.section("DECISION SUMMARY (plan section 15.2)"))
    sets = int(o2.get("sets", 0))
    if sets >= MIN_LOSS_SETS:
        median = float(o2["median"])
        print(f"O2 pooled median loss: {median:.1f}% over {sets} complete sets")
        if median < 8:
            print("  -> below 8%: retire the velocity track, ship tempo only")
        elif median <= 25:
            print("  -> 10-25%: velocity is worth pursuing if O4 allows 5-8%")
        else:
            print("  -> above 25%: large effect, but confirm it on the study")
    else:
        print(
            f"O2 has only {sets} complete per-rep sets (need {MIN_LOSS_SETS}): "
            "no verdict. The loss distribution must come from the study."
        )
    if o4.get("groups"):
        median = float(o4["median_mps"])
        print(
            f"O4 median tolerable error across {o4['groups']} qualifying targets: "
            f"{median:.3f} m/s ({o4['median_pct']:.1f}%)"
        )
        if median < 0.02:
            print("  -> below 0.02 m/s: a wrist sensor is unlikely to pass; keep velocity exploratory")
        elif median < 0.05:
            print("  -> 0.02-0.05 m/s: velocity is marginal; expect trend use, not absolute targets")
        else:
            print("  -> above 0.05 m/s: the velocity track is worth the study")
    if not o1.empty:
        estimate = float((o1["sets"] * o1["complete%"] / 100).fillna(0).sum())
        print(f"O1 complete per-rep sets overall: about {estimate:.0f}")
        if estimate < 50:
            print("  -> under 50: take the loss distribution from the study")
    print()
    print(
        "No number here decides anything on its own; the gates in section 10 do, "
        "and they need the study. These aggregates only decide whether the study "
        "is worth running."
    )


# --- entry point -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="database path (read-only)")
    parser.add_argument(
        "--section",
        choices=(*SECTIONS, "all"),
        default="all",
        help="run one section",
    )
    parser.add_argument("--quarters", type=int, default=4, help="O1 recent quarters")
    parser.add_argument("--months", type=int, default=12, help="O5 recent months")
    args = parser.parse_args(argv)

    path = args.db or db_mod.default_db_path()
    conn = open_readonly(path)
    try:
        ctx = load_context(conn)
        if ctx.sets.empty:
            print("no clean sets — nothing to analyse")
            return 2
        print(f"database: {path}")
        print(
            f"clean sets: {len(ctx.sets)}  working: "
            f"{int(ctx.sets['is_working_set'].astype(bool).sum())}  "
            f"rep rows: {len(ctx.reps)}"
        )

        def selected(key: str) -> bool:
            return args.section in ("all", key)

        o1 = pd.DataFrame()
        o2: dict = {}
        o4: dict = {}
        targets = pd.DataFrame()
        result = None
        if selected("o3") or selected("o4"):
            result = vbt_calibration.calibrate(ctx.sets)
            targets = target_frame(result)

        if selected("o0"):
            o0_field_population(ctx)
        if selected("o1"):
            o1 = o1_rep_coverage(ctx, args.quarters)
        if selected("o2"):
            _, o2 = o2_loss_distribution(ctx)
        if selected("o3") and result is not None:
            o3_band_widths(targets, result)
        if selected("o4"):
            _, o4 = o4_error_budget(targets)
        if selected("o5"):
            o5_calendar(ctx, args.months)
        if selected("o2") and selected("o4"):
            decision_summary(o1, o2, o4)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
