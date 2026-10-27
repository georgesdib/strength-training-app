"""Baseline features: what the athlete can currently do.

Descriptive, not judgemental. It reports what is measured and labels what is estimated; the
critique layer decides whether a value is good. All functions are pure transforms over a
clean-set frame so the critique, the prescription engine and the backtest harness share one
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from strength_coach.domain import rir as rir_mod
from strength_coach.features import derived
from strength_coach.ingest import clean as clean_mod
from strength_coach.utils import dates, exercises, numeric


@dataclass
class LiftBaseline:
    """Per-lift summary. Every estimated field names its method."""

    exercise_id: str
    display: str
    sets_all_time: int = 0
    sets_window: int = 0
    working_sets_window: int = 0
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
    warmup_share: float | None = None
    readiness: dict[str, float | None] = field(default_factory=dict)
    lifts: list[LiftBaseline] = field(default_factory=list)


def prepare_sets(
    training: pd.DataFrame,
    readiness: pd.DataFrame,
    *,
    bodyweight_tolerance_days: int = 7,
) -> pd.DataFrame:
    """Clean + enrich in one call: the analysis entry point.

    Delegates to the ingest layer so there is exactly one cleaning implementation. Anything
    that needs a clean set should come through here rather than re-deriving it.
    """
    result = clean_mod.build_clean_sets(
        training, readiness, bodyweight_tolerance_days=bodyweight_tolerance_days
    )
    return derived.enrich(result.sets)


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
        working_window = derived.working_sets(window)
        row.working_sets_window = int(len(working_window))

        estimate = lift.dropna(subset=["e1rm_kg"]).sort_values("e1rm_kg", ascending=False)
        if not estimate.empty:
            best = estimate.iloc[0]
            row.best_e1rm_kg = round(float(best["e1rm_kg"]), 1)
            row.best_e1rm_method = str(best["e1rm_method"])
            row.best_e1rm_date = _iso(best["date"])

        if lift["load_kg"].notna().any():
            row.top_load_kg = float(lift["load_kg"].max())

        # Progression load, not logged load: DEC-LOAD-02 means bodyweight movements are
        # tracked on added load, so a pull-up's "working load" is the plate, not body mass.
        effort = derived.effort_sets(working_window)
        if not effort.empty:
            row.median_working_load_kg = _median(effort["progression_load_kg"])
            row.working_reps_median = _median(effort["reps"])
            row.working_rir_median = _median(effort["rir"])
        elif not working_window.empty:
            row.median_working_load_kg = _median(working_window["progression_load_kg"])
            row.working_reps_median = _median(working_window["reps"])

        measured = working_window[working_window["velocity_present"]]
        if not measured.empty:
            row.velocity_median_mps = round(float(measured["velocity_mps"].median()), 3)
            row.velocity_n = int(len(measured))

        if not effort.empty:
            window = effort["in_rir_window"].dropna()
            if len(window):
                row.rir_compliance_pct = round(100.0 * float(window.mean()), 1)

        result.append(row)
    return result


def session_stats(sets: pd.DataFrame, *, as_of: str | pd.Timestamp, window_days: int = 84) -> dict:
    """Frequency, session size, weekly tonnage and weekly weighted spinal cost."""
    as_of_ts = pd.Timestamp(as_of)
    window_start = as_of_ts - pd.Timedelta(days=window_days)
    per_session = sets.groupby("date").size()
    window_sessions = sets[sets["date"] > window_start].groupby("date").size()

    # Tonnage: added load only (ingest already excludes bodyweight mass and holds), and
    # working sets only — DEC-RIR-01 makes warm-ups separable, so counting them would
    # inflate the weekly figure with ramp-up work.
    tonnage_sets = derived.working_sets(sets).dropna(subset=["tonnage_kg"])
    weekly = tonnage_sets.groupby(
        tonnage_sets["date"].dt.to_period("W")
    )["tonnage_kg"].sum()

    taxonomy = exercises.taxonomy()
    cost = {eid: e.get("spinal_cost", 0) for eid, e in taxonomy.entities.items()}
    high = sets[
        sets["exercise_id"].map(
            lambda e: bool(taxonomy.entities.get(e, {}).get("high_fatigue_spinal", False))
        )
    ]
    weekly_cost = high.groupby(high["date"].dt.to_period("W"))["exercise_id"].apply(
        lambda s: float(sum(cost.get(e, 0) for e in s))
    )

    return {
        "sessions_all_time": int(per_session.size),
        "sessions_per_week": round(len(window_sessions) / (window_days / 7.0), 2),
        "median_sets_per_session": _median(per_session),
        "median_weekly_tonnage_kg": _median(weekly),
        "weekly_spinal_cost_median": _median(weekly_cost),
        "warmup_share": round(float((~sets["is_working_set"]).mean()), 3),
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
    for name in fields:
        values = numeric.coerce_numeric(recent[name]).dropna()
        values = values[values > 0]   # defensive: these scales have no zero bucket
        out[name.lower()] = round(float(values.mean()), 2) if not values.empty else None
    return out


def warmup_share(sets: pd.DataFrame) -> float:
    """Share of a lift's rows that are warm-ups (DEC-RIR-01). A coaching signal."""
    return rir_mod.warmup_fraction(sets["rir"]) if len(sets) else 0.0


def _median(series) -> float | None:
    clean = pd.Series(series).dropna()
    return float(clean.median()) if len(clean) else None


def _iso(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()
