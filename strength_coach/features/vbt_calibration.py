"""VBT calibration: historical velocity data -> per-lift, per-rep-count targets.

Deterministic and versioned, never an LLM decision (docs/VBT-CALIBRATION.md).

The hard part is not the arithmetic, it is honesty about sparse data. A velocity target
derived from four sets is not the same object as one derived from two hundred, so every
target carries its `scope`, `n_sets` and `n_sessions`, and when nothing adequate exists the
result is *no target* rather than a plausible number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from strength_coach.domain import rir as rir_mod
from strength_coach.features import derived
from strength_coach.utils import exercises, paths, stats

METHOD_VERSION = "1.0.0"


@dataclass(frozen=True)
class CalibrationParams:
    """Every number the calibration depends on. Changing any of these changes the output."""

    k: float = 2.0                     # robust band width in MADs
    min_relative_spread: float = 0.05  # floor so a degenerate sample cannot collapse the band
    reps_min: int = 1
    reps_max: int = 8                  # velocity targets are only meaningful for short sets
    min_sets_lift: int = 12
    min_sessions_lift: int = 3
    min_sets_family: int = 24
    # A warm-up-range load has no informative velocity target, so a set must be at least this
    # fraction of the lift's estimated maximum to calibrate from.
    min_load_fraction: float = 0.60

    def as_dict(self) -> dict:
        return {
            "k": self.k,
            "min_relative_spread": self.min_relative_spread,
            "reps_min": self.reps_min,
            "reps_max": self.reps_max,
            "min_sets_lift": self.min_sets_lift,
            "min_sessions_lift": self.min_sessions_lift,
            "min_sets_family": self.min_sets_family,
            "min_load_fraction": self.min_load_fraction,
        }


@dataclass(frozen=True)
class CalibrationTarget:
    """A velocity target for one lift at one rep count, with its provenance."""

    exercise_id: str
    scope: str                 # "lift" | "family" | "lift_pooled" | "family_pooled" | "none"
    rep_count: int
    rir_band: tuple[int, int]
    velocity_median: float | None
    velocity_low: float | None
    velocity_high: float | None
    n_sets: int
    n_sessions: int
    method_version: str = METHOD_VERSION
    params: dict = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        return self.scope != "none" and self.velocity_median is not None


@dataclass
class CalibrationResult:
    targets: list[CalibrationTarget]
    excluded: dict[str, int]          # exclusion criterion -> rows removed
    params: dict

    def lookup(self, exercise_id: str, rep_count: int) -> CalibrationTarget | None:
        """Find a target, preferring lift scope over family over pooled."""
        candidates = [
            t for t in self.targets
            if t.exercise_id == exercise_id and t.rep_count == rep_count and t.is_available
        ]
        if not candidates:
            return None
        order = {"lift": 0, "family": 1, "lift_pooled": 2, "family_pooled": 3}
        return sorted(candidates, key=lambda t: order.get(t.scope, 9))[0]


@lru_cache(maxsize=1)
def default_params() -> CalibrationParams:
    return CalibrationParams()


def calibrate(sets: pd.DataFrame, *, params: CalibrationParams | None = None) -> CalibrationResult:
    """Build calibration targets from clean, enriched sets.

    Expects the output of `features.derived.enrich` (needs `velocity_present`, `rir_class`,
    `e1rm_kg`).
    """
    params = params or default_params()
    taxonomy = exercises.taxonomy()
    family_of = {
        eid: (entity.get("vbt_family") or None)
        for eid, entity in taxonomy.entities.items()
    }

    excluded: dict[str, int] = {}
    frame = sets.copy()
    excluded["not_vbt_lift"] = int(
        (~frame["exercise_id"].map(lambda e: family_of.get(e) is not None)).sum()
    )
    frame = frame[frame["exercise_id"].map(lambda e: family_of.get(e) is not None)].copy()

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal frame
        excluded[reason] = int(mask.sum())
        frame = frame[~mask].copy()

    drop(~frame["velocity_present"], "no_velocity")
    drop(~frame["is_working_set"], "warmup")                     # DEC-RIR-01
    drop(~frame["rir_class"].eq("effort"), "no_effort_rating")

    # Each lift has its own effort window, so window membership is computed per row.
    in_window = [
        rir_mod.within_window(rir, *rir_mod.target_for(str(eid)))
        for rir, eid in zip(frame["rir"], frame["exercise_id"], strict=True)
    ]
    frame = frame[pd.Series(in_window, index=frame.index, dtype=bool)].copy()

    drop(~frame["reps"].between(params.reps_min, params.reps_max), "reps_out_of_range")
    drop(frame["load_basis"].eq("unknown"), "load_basis_unknown")
    drop(frame["flags"].str.contains("REPS_TYPO", na=False), "reps_typo")

    # Warm-up-range loads carry no useful velocity information.
    if not frame.empty:
        best = frame.groupby("exercise_id")["e1rm_kg"].transform("max")
        too_light = frame["e1rm_kg"].notna() & (frame["e1rm_kg"] < best * params.min_load_fraction)
        frame = frame[~too_light].copy()
        excluded["load_too_light"] = int(too_light.sum())

    if frame.empty:
        return CalibrationResult(targets=[], excluded=excluded, params=params.as_dict())

    frame = frame.assign(vbt_family=frame["exercise_id"].map(lambda e: family_of.get(e)))
    frame = _drop_velocity_outliers(frame, k=4.0)

    targets: list[CalibrationTarget] = []
    for (exercise_id, reps), group in frame.groupby(["exercise_id", "reps"]):
        target = _target_from_group(
            group, exercise_id=str(exercise_id), reps=int(reps), scope="lift", params=params
        )
        if target and len(group) >= params.min_sets_lift and group["date"].nunique() >= params.min_sessions_lift:
            targets.append(target)

    # Family fallback fills the rep counts a lift could not support on its own.
    covered = {(t.exercise_id, t.rep_count) for t in targets}
    for (family, reps), group in frame.dropna(subset=["vbt_family"]).groupby(["vbt_family", "reps"]):
        if len(group) < params.min_sets_family:
            continue
        members = group["exercise_id"].unique()
        for exercise_id in members:
            if (str(exercise_id), int(reps)) in covered:
                continue
            target = _target_from_group(
                group, exercise_id=str(exercise_id), reps=int(reps), scope="family", params=params
            )
            if target:
                targets.append(target)

    return CalibrationResult(targets=targets, excluded=excluded, params=params.as_dict())


def _target_from_group(
    group: pd.DataFrame,
    *,
    exercise_id: str,
    reps: int,
    scope: str,
    params: CalibrationParams,
) -> CalibrationTarget | None:
    velocities = group["velocity_mps"].to_numpy(dtype="float64")
    if velocities.size == 0:
        return None
    median = stats.median(velocities)
    low, high = stats.robust_band(
        velocities, k=params.k, min_relative_spread=params.min_relative_spread
    )
    if not np.isfinite(median):
        return None
    return CalibrationTarget(
        exercise_id=exercise_id,
        scope=scope,
        rep_count=reps,
        rir_band=rir_mod.target_for(exercise_id),
        velocity_median=round(float(median), 4),
        velocity_low=round(float(low), 4),
        velocity_high=round(float(high), 4),
        n_sets=int(len(group)),
        n_sessions=int(group["date"].nunique()),
        params=params.as_dict(),
    )


def _drop_velocity_outliers(frame: pd.DataFrame, *, k: float) -> pd.DataFrame:
    """Iteratively drop sets whose velocity is far from their (lift, rep) group centre.

    Capped at two passes: this removes obvious device glitches, not legitimate spread.
    """
    out = frame.copy()
    for _ in range(2):
        keep = pd.Series(True, index=out.index)
        for _, group in out.groupby(["exercise_id", "reps"]):
            if len(group) < 5:
                continue
            median = stats.median(group["velocity_mps"])
            spread = stats.mad(group["velocity_mps"]) or 0.0
            if spread <= 0:
                continue
            distance = (group["velocity_mps"] - median).abs()
            keep.loc[group.index] = distance <= k * spread
        if keep.all():
            break
        out = out[keep]
    return out


def summarize(result: CalibrationResult) -> pd.DataFrame:
    """One row per (lift, rep count, scope) — for the CLI and for tests."""
    rows = [
        {
            "exercise_id": t.exercise_id,
            "rep_count": t.rep_count,
            "scope": t.scope,
            "median": t.velocity_median,
            "low": t.velocity_low,
            "high": t.velocity_high,
            "n_sets": t.n_sets,
            "n_sessions": t.n_sessions,
        }
        for t in result.targets
    ]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    order = {"lift": 0, "family": 1, "lift_pooled": 2, "family_pooled": 3}
    return frame.sort_values(
        ["exercise_id", "rep_count", "scope"],
        key=lambda s: s.map(order) if s.name == "scope" else s,
    ).reset_index(drop=True)
