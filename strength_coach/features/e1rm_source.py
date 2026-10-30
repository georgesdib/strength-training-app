"""Pure prescription load-base selection.

The prescription engine's e1RM selector is extracted here so monitoring code can describe the
load base without importing the engine. This module intentionally has no store or prescribe
imports: the caller supplies the enriched set frame, any override, the calibration factor and
the decay function.

The selector semantics are preserved exactly from the engine. A manual override wins; otherwise
one of best_usable, median or most_recent selects an age-decayed set in the window. The median
uses the shorter robust window and falls back to the full window when it is empty.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LoadBaseEstimate:
    """The load-base e1RM with the provenance the plan snapshot needs."""

    kg: float
    ref: str
    calibrated: bool
    decayed: bool
    coverage: int | None
    decay: float
    age_days: int | None
    selector: str
    quality: str


def select_load_base(
    sets: pd.DataFrame,
    *,
    exercise_id: str,
    for_date: str,
    window_days: int,
    robust_window_days: int,
    source: str,
    override: Mapping[str, Any] | None,
    calibration_factor: float,
    decay_factor: Callable[[float], float],
    history_equivalents: Sequence[str],
) -> LoadBaseEstimate | None:
    """Select the prescription load base, exactly as the engine does.

    The decay callable receives age in days and is supplied by the engine so the long-gap
    continuity exception remains owned by the engine. The function never fits or applies a
    calibration factor; it receives the factor already in force for this lift.
    """
    day = pd.Timestamp(for_date)

    if override is not None:
        age = (day - pd.Timestamp(override["effective_from"])).days
        decay = float(decay_factor(age))
        return LoadBaseEstimate(
            kg=float(override["e1rm_kg"]) * decay,
            ref=f"e1rm_override:{override['override_id']}",
            calibrated=False,
            decayed=decay != 1.0,
            coverage=None,
            decay=decay,
            age_days=int(age),
            selector="override",
            quality="ok",
        )

    if sets is None or sets.empty or "e1rm_kg" not in sets.columns:
        return None

    cutoff = day - pd.Timedelta(days=window_days)
    equivalents = tuple(history_equivalents) or (exercise_id,)
    frame = sets.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    usable = frame[
        frame["exercise_id"].isin(equivalents)
        & frame["e1rm_kg"].notna()
        & (frame["date"] >= cutoff)
    ]
    if "is_working_set" in usable.columns:
        usable = usable[usable["is_working_set"].astype(bool)]
    if usable.empty:
        return None
    usable = usable.assign(_age_days=(day - usable["date"]).dt.days)
    usable["_decay"] = [float(decay_factor(age)) for age in usable["_age_days"]]
    usable["_effective"] = usable["e1rm_kg"] * usable["_decay"]
    factor = float(calibration_factor)

    if source == "median":
        robust_start = day - pd.Timedelta(days=robust_window_days)
        pool = usable[usable["date"] >= robust_start]
        if pool.empty:
            pool = usable
        raw_median = float(pool["e1rm_kg"].median())
        effective_median = float(pool["_effective"].median())
        decay = effective_median / raw_median if raw_median > 0 else 1.0
        row = pool.sort_values(["date", "set_id"]).iloc[-1]
        qualities = (
            pool["e1rm_quality"]
            if "e1rm_quality" in pool.columns
            else pd.Series("ok", index=pool.index)
        )
        quality = "degraded" if qualities.astype(str).eq("degraded").any() else "ok"
        return LoadBaseEstimate(
            kg=effective_median * factor,
            ref=f"set:{row['session_id']}/{int(row['set_id'])}",
            calibrated=factor != 1.0,
            decayed=decay < 1.0 - 1e-9,
            coverage=int(len(pool)),
            decay=float(decay),
            age_days=int(row["_age_days"]),
            selector="median",
            quality=quality,
        )

    if source == "most_recent":
        row = usable.sort_values(["date", "set_id"]).iloc[-1]
        decay = float(row["_decay"])
        quality = str(row.get("e1rm_quality", "ok"))
        return LoadBaseEstimate(
            kg=float(row["e1rm_kg"]) * factor * decay,
            ref=f"set:{row['session_id']}/{int(row['set_id'])}",
            calibrated=factor != 1.0,
            decayed=decay != 1.0,
            coverage=int(len(usable)),
            decay=decay,
            age_days=int(row["_age_days"]),
            selector="most_recent",
            quality=quality,
        )

    # best_usable: highest current estimate; ties prefer the more recent set.
    row = usable.sort_values(
        ["_effective", "date", "set_id"], ascending=[False, False, False]
    ).iloc[0]
    decay = float(row["_decay"])
    quality = str(row.get("e1rm_quality", "ok"))
    return LoadBaseEstimate(
        kg=float(row["e1rm_kg"]) * factor * decay,
        ref=f"set:{row['session_id']}/{int(row['set_id'])}",
        calibrated=factor != 1.0,
        decayed=decay != 1.0,
        coverage=int(len(usable)),
        decay=decay,
        age_days=int(row["_age_days"]),
        selector="best_usable",
        quality=quality,
    )
