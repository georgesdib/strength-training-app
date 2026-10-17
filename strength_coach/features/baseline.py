"""Baseline features: what the athlete can currently do.

This module is the answer to "learn my baseline". It is deliberately descriptive — it
reports what is measured and labels what is estimated. It does not judge (that is the
critique layer) and it contains no thresholds (those are config).

All functions are pure transforms over dataframes so they can be reused by the critique
agent, the prescription engine and the backtest harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.domain import load as load_mod
from strength_coach.utils import dates, exercises, numeric

NUMERIC_COLUMNS = ["Weight_Used", "Reps_Done", "RIR", "Avg_velocity", "Avg_rom", "TUT"]

# The modal high RIR value is excluded from effort statistics: in a real export it is used
# far more often than any other value while one mid-scale value is never used at all, which
# is the signature of a default bucket rather than a reported effort (DQ-SENT-03). It stays
# in the data; it just does not count as an effort observation.
SUSPECT_RIR = {6}
EFFORT_RIR = {0, 1, 2, 3, 5}


@dataclass
class LiftBaseline:
    """Per-lift summary. Every estimated field names its method."""

    exercise_id: str
    display: str
    sets_all_time: int = 0
    sets_window: int = 0
    sets_per_week_window: float = 0.0
    best_e1rm_kg: float | None = None
    best_e1rm_method: str | None = None
    best_e1rm_date: str | None = None
    top_load_kg: float | None = None
    median_working_load_kg: float | None = None
    working_reps_median: float | None = None
    working_rir_median: float | None = None
    velocity_median_mps: float | None = None
    velocity_n: int = 0
    rir_compliance_pct: float | None = None
    last_trained: str | None = None


@dataclass
class BaselineReport:
    """Collects the full baseline. Rendered by tools/baseline.py."""

    as_of: str
    window_days: int
    bodyweight_kg: float | None = None
    bodyweight_date: str | None = None
    sessions_per_week: float | None = None
    sessions_all_time: int = 0
    median_sets_per_session: float | None = None
    median_weekly_tonnage_kg: float | None = None
    weekly_spinal_cost_median: float | None = None
    readiness: dict[str, float | None] = field(default_factory=dict)
    lifts: list[LiftBaseline] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# preparation
# --------------------------------------------------------------------------- #
def prepare_sets(
    training: pd.DataFrame,
    readiness: pd.DataFrame,
    *,
    bodyweight_tolerance_days: int = 7,
) -> pd.DataFrame:
    """Turn the raw log into per-set rows with date, canonical id and resolved load.

    This is the light path used for analysis. Full cleaning (flags, quarantine,
    session reconstruction) belongs to `ingest`; everything added here is derivable and
    reproducible, so the baseline never depends on a stored artifact.
    """
    frame = training.copy()
    frame["date"] = dates.parse_dates(frame["Date"])
    frame = frame[frame["date"].notna()].copy()
    frame = numeric.coerce_frame(frame, NUMERIC_COLUMNS)

    taxonomy = exercises.taxonomy()
    frame["exercise_id"] = frame["Exercise"].map(exercises.canonical_id)

    frame = attach_bodyweight(frame, readiness, tolerance_days=bodyweight_tolerance_days)

    props = {eid: dict(taxonomy.entities.get(eid, {})) for eid in frame["exercise_id"].dropna().unique()}
    is_bw = frame["exercise_id"].map(lambda e: bool(props.get(e, {}).get("bodyweight_type", False)))
    is_time = frame["exercise_id"].map(lambda e: bool(props.get(e, {}).get("time_based", False)))

    basis: list[str] = []
    external: list[float | None] = []
    total: list[float | None] = []
    for weight, bodyweight, bw_type, time_based in zip(
        frame["Weight_Used"], frame["bodyweight_kg"], is_bw, is_time, strict=True
    ):
        resolved = load_mod.resolve_load_basis(
            None if pd.isna(weight) else float(weight),
            bodyweight_kg=None if pd.isna(bodyweight) else float(bodyweight),
            is_bodyweight_type=bool(bw_type),
            is_time_based=bool(time_based),
        )
        basis.append(resolved.basis)
        external.append(resolved.external_load_kg)
        total.append(resolved.total_load_kg)

    frame["load_basis"] = basis
    frame["external_load_kg"] = pd.Series(external, index=frame.index, dtype="float64")
    frame["total_load_kg"] = pd.Series(total, index=frame.index, dtype="float64")

    # e1RM is only meaningful for movements that are actually loaded to a 1RM attempt.
    # For back extensions, planks and assistance work the formula happily produces a
    # number (bodyweight x reps) that is not a maximal strength estimate at all, so those
    # rows get a null e1RM rather than a plausible-looking lie.
    frame["e1rm_applicable"] = frame["exercise_id"].map(
        lambda e: _e1rm_applicable(props.get(e, {}))
    )

    # e1RM is computed on total mass when the basis implies one, never on a bare number
    # whose meaning is ambiguous.
    frame["e1rm_load_kg"] = frame["total_load_kg"].where(
        frame["load_basis"].isin(["external", "bodyweight_total", "added"]),
        frame["Weight_Used"],
    )
    frame = add_e1rm(frame)
    return frame


def _e1rm_applicable(entity_props: dict) -> bool:
    """Whether an e1RM is a meaningful quantity for this exercise.

    Explicit config wins; otherwise fall back to a structural rule: a movement supports
    an e1RM when it is loadable, not time-based, and does not carry bodyweight in the
    load column.
    """
    if "e1rm_applicable" in entity_props:
        return bool(entity_props["e1rm_applicable"])
    return bool(
        entity_props.get("loadable", True)
        and not entity_props.get("time_based", False)
        and not entity_props.get("bodyweight_type", False)
    )


def attach_bodyweight(
    sets: pd.DataFrame,
    readiness: pd.DataFrame,
    *,
    tolerance_days: int = 7,
) -> pd.DataFrame:
    """Nearest bodyweight within a tolerance window, via as-of join.

    Bodyweight is needed to disambiguate bodyweight-style loads (DQ-BW-01). A nearest
    join within +/-7 days is used because weighing is sporadic (18% of readiness rows
    have no weight) but body mass is stable over a week.
    """
    readiness = readiness.copy()
    readiness["date"] = dates.parse_dates(readiness["Date"])
    weight = numeric.coerce_numeric(readiness["Weight"])
    body = pd.DataFrame({"date": readiness["date"], "bodyweight_kg": weight})
    body = body.dropna().drop_duplicates("date", keep="last").sort_values("date")

    left = sets.sort_values("date")
    merged = pd.merge_asof(
        left,
        body,
        on="date",
        direction="nearest",
        tolerance=pd.Timedelta(days=tolerance_days),
    )
    return merged.sort_index()


def add_e1rm(frame: pd.DataFrame) -> pd.DataFrame:
    """Vectorised e1RM. Mirrors domain.e1rm rules exactly, including the rep caps."""
    out = frame.copy()
    load = out["e1rm_load_kg"]
    reps = out["Reps_Done"]
    rir = out["RIR"]

    rir_usable = rir.between(0, 5)          # RIR 6 excluded (DQ-SENT-03)
    valid = (
        load.notna() & (load > 0)
        & reps.notna() & (reps > 0) & (reps <= e1rm_mod.MAX_USABLE_REPS)
        & out["e1rm_applicable"].fillna(False).astype(bool)
    )

    plain = load * (1.0 + reps / e1rm_mod.EPLEY_DIVISOR)
    adjusted = load * (1.0 + (reps + rir) / e1rm_mod.EPLEY_DIVISOR)

    out["e1rm_kg"] = np.where(valid, np.where(rir_usable, adjusted, plain), np.nan)
    out["e1rm_method"] = np.where(valid & rir_usable, "epley_plus_rir", np.where(valid, "epley", None))
    out["e1rm_quality"] = np.where(
        valid, np.where(reps <= e1rm_mod.MAX_RELIABLE_REPS, "ok", "degraded"), None
    )
    return out


# --------------------------------------------------------------------------- #
# summaries
# --------------------------------------------------------------------------- #
def lift_baselines(
    sets: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp,
    window_days: int = 84,
    exercise_ids: list[str] | None = None,
) -> list[LiftBaseline]:
    """Summarise each lift over all time and over a recent window."""
    as_of_ts = pd.Timestamp(as_of)
    window_start = as_of_ts - pd.Timedelta(days=window_days)
    taxonomy = exercises.taxonomy()
    ids = exercise_ids or sorted(sets["exercise_id"].dropna().unique())

    result: list[LiftBaseline] = []
    for exercise_id in ids:
        lift = sets[sets["exercise_id"] == exercise_id]
        if lift.empty:
            continue
        entity = taxonomy.entities.get(exercise_id, {})
        row = LiftBaseline(
            exercise_id=exercise_id,
            display=str(entity.get("display", exercise_id)),
            sets_all_time=int(len(lift)),
            last_trained=_iso(lift["date"].max()),
        )

        window = lift[lift["date"] > window_start]
        row.sets_window = int(len(window))
        row.sets_per_week_window = round(len(window) / (window_days / 7.0), 2)

        estimate = lift.dropna(subset=["e1rm_kg"]).sort_values("e1rm_kg", ascending=False)
        if not estimate.empty:
            best = estimate.iloc[0]
            row.best_e1rm_kg = round(float(best["e1rm_kg"]), 1)
            row.best_e1rm_method = str(best["e1rm_method"])
            row.best_e1rm_date = _iso(best["date"])

        if lift["Weight_Used"].notna().any():
            row.top_load_kg = float(lift["Weight_Used"].max())

        effort = window[window["RIR"].isin(EFFORT_RIR)]
        if not effort.empty:
            row.median_working_load_kg = float(effort["Weight_Used"].median())
            row.working_reps_median = float(effort["Reps_Done"].median())
            row.working_rir_median = float(effort["RIR"].median())
        elif not window.empty:
            row.median_working_load_kg = float(window["Weight_Used"].median())
            row.working_reps_median = float(window["Reps_Done"].median())

        measured = window[window["Avg_velocity"] > 0]
        if not measured.empty:
            row.velocity_median_mps = round(float(measured["Avg_velocity"].median()), 3)
            row.velocity_n = int(len(measured))

        if not effort.empty:
            compliant = int(effort["RIR"].isin([2, 3]).sum())
            row.rir_compliance_pct = round(100.0 * compliant / len(effort), 1)

        result.append(row)
    return result


def session_stats(sets: pd.DataFrame, *, as_of: str | pd.Timestamp, window_days: int = 84) -> dict:
    """Frequency, session size and weekly load summaries."""
    as_of_ts = pd.Timestamp(as_of)
    window_start = as_of_ts - pd.Timedelta(days=window_days)
    per_session = sets.groupby("date").size()
    window_sessions = sets[sets["date"] > window_start].groupby("date").size()

    # Tonnage counts ADDED external load only. Bodyweight mass is deliberately excluded:
    # including it would let a pull-up session out-tonnage a deadlift session and make
    # week-on-week comparisons meaningless.
    rep_based = sets[sets["Reps_Done"].notna() & sets["external_load_kg"].notna()]
    per_set_tonnage = rep_based["external_load_kg"] * rep_based["Reps_Done"]
    weekly = per_set_tonnage.groupby(rep_based["date"].dt.to_period("W")).sum()

    taxonomy = exercises.taxonomy()
    cost_map = {eid: e.get("spinal_cost", 0) for eid, e in taxonomy.entities.items()}
    high = sets[sets["exercise_id"].map(
        lambda e: bool(taxonomy.entities.get(e, {}).get("high_fatigue_spinal", False))
    )]
    weekly_cost = high.groupby(high["date"].dt.to_period("W"))["exercise_id"].apply(
        lambda s: float(sum(cost_map.get(e, 0) for e in s))
    )

    return {
        "sessions_all_time": int(per_session.size),
        "sessions_per_week": round(len(window_sessions) / (window_days / 7.0), 2),
        "median_sets_per_session": float(per_session.median()) if not per_session.empty else None,
        "median_weekly_tonnage_kg": float(weekly.median()) if not weekly.empty else None,
        "weekly_spinal_cost_median": float(weekly_cost.median()) if not weekly_cost.empty else None,
    }


def readiness_summary(
    readiness: pd.DataFrame,
    *,
    as_of: str | pd.Timestamp,
    days: int = 28,
) -> dict[str, float | None]:
    """Mean wellness over a recent window. Reminder: 1-5, HIGHER IS BETTER."""
    frame = readiness.copy()
    frame["date"] = dates.parse_dates(frame["Date"])
    recent = frame[frame["date"] > pd.Timestamp(as_of) - pd.Timedelta(days=days)]
    fields = ["Sleep", "Energy", "Mood", "Soreness", "Stress", "Nutrition", "Hydration"]
    out: dict[str, float | None] = {}
    for field_name in fields:
        values = numeric.coerce_numeric(recent[field_name]).dropna()
        values = values[values > 0]   # defensive: these scales have no zero bucket
        out[field_name.lower()] = round(float(values.mean()), 2) if not values.empty else None
    return out


def _iso(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()
