"""Derived metrics computed on top of clean sets.

This is the boundary where "what happened" becomes "what it means numerically". Everything
here is a pure transform over a clean-set frame, so the critique, the prescription engine and
the backtest harness can all call the same functions and cannot disagree.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.domain import rir as rir_mod
from strength_coach.utils import exercises, numeric


def e1rm_applicable(entity_props: dict) -> bool:
    """Whether an e1RM is a meaningful quantity for this exercise.

    Explicit config wins; otherwise a structural rule: a movement supports an e1RM when it
    is loadable, not time-based, and does not carry bodyweight in the load column.
    """
    if "e1rm_applicable" in entity_props:
        return bool(entity_props["e1rm_applicable"])
    return bool(
        entity_props.get("loadable", True)
        and not entity_props.get("time_based", False)
        and not entity_props.get("bodyweight_type", False)
    )


def add_e1rm_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the applicability mask and the load column e1RM should use.

    The load used is total mass when the basis implies it (a bodyweight movement logged as
    a total, or a plate added to bodyweight) and the external load otherwise. This is the
    only place that decision is made, so e1RM cannot be computed from an ambiguous number.
    """
    out = frame.copy()
    taxonomy = exercises.taxonomy()
    out["e1rm_applicable"] = out["exercise_id"].map(
        lambda e: e1rm_applicable(dict(taxonomy.entities.get(e, {})))
    )
    implied_total = out["load_basis"].isin(["external", "bodyweight_total", "added"])
    out["e1rm_load_kg"] = out["total_load_kg"].where(implied_total, out["load_kg"])
    return out


def add_e1rm(frame: pd.DataFrame) -> pd.DataFrame:
    """Vectorised e1RM, mirroring `domain.e1rm` exactly including the rep caps.

    Warm-up sets (DEC-RIR-01) contribute no RIR adjustment: extrapolating a warm-up to a
    maximum is meaningless. They are excluded by requiring `rir_class == "effort"`.
    """
    out = add_e1rm_inputs(frame)
    load = out["e1rm_load_kg"]
    reps = out["reps"]
    rir = out["rir"]

    rir_usable = out["rir_class"].eq("effort") & rir.between(0, 5)
    valid = (
        load.notna() & (load > 0)
        & reps.notna() & (reps > 0) & (reps <= e1rm_mod.MAX_USABLE_REPS)
        & out["e1rm_applicable"].fillna(False).astype(bool)
    )

    plain = load * (1.0 + reps / e1rm_mod.EPLEY_DIVISOR)
    adjusted = load * (1.0 + (reps + rir) / e1rm_mod.EPLEY_DIVISOR)

    out["e1rm_kg"] = np.where(valid, np.where(rir_usable, adjusted, plain), np.nan)
    out["e1rm_method"] = np.where(
        valid & rir_usable, "epley_plus_rir", np.where(valid, "epley", None)
    )
    out["e1rm_quality"] = np.where(
        valid, np.where(reps <= e1rm_mod.MAX_RELIABLE_REPS, "ok", "degraded"), None
    )
    return out


def add_velocity_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """One boolean for the whole telemetry block (DQ-SENT-01).

    The export writes 0.000000 when the device was not used. Because all telemetry columns
    are zero on exactly the same rows, a single presence flag is sufficient and safer than
    testing each column independently.
    """
    out = frame.copy()
    # One definition, shared with the cleaner: a zero reading is a sentinel, not a measurement.
    out["velocity_present"] = numeric.positive_measurement_present(out["velocity_mps"])
    return out


def add_effort_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """Target-window membership per set, using the single RIR implementation."""
    out = frame.copy()
    out["rir_target_low"] = out["exercise_id"].map(
        lambda e: rir_mod.target_for(str(e))[0]
    )
    out["rir_target_high"] = out["exercise_id"].map(
        lambda e: rir_mod.target_for(str(e))[1]
    )
    out["in_rir_window"] = [
        rir_mod.within_window(rir, int(low), int(high))
        for rir, low, high in zip(
            out["rir"], out["rir_target_low"], out["rir_target_high"], strict=True
        )
    ]
    # Power work is quality-limited, not RIR-scored (DEC-POWER-02). Its RIR value is not a
    # target, so it is excluded from the window rather than counted as a failure.
    out["rir_target_low"] = out["rir_target_low"].astype("Float64")
    out["rir_target_high"] = out["rir_target_high"].astype("Float64")
    out["in_rir_window"] = out["in_rir_window"].astype("boolean")
    power_ids = {
        exercise_id for exercise_id, props in exercises.taxonomy().entities.items()
        if props.get("pattern") == "power_jump"
    }
    power_mask = out["exercise_id"].astype(str).isin(power_ids)
    out.loc[power_mask, "rir_target_low"] = pd.NA
    out.loc[power_mask, "rir_target_high"] = pd.NA
    out.loc[power_mask, "in_rir_window"] = pd.NA
    return out


def enrich(clean_sets: pd.DataFrame) -> pd.DataFrame:
    """Apply every per-set derived metric, in dependency order."""
    out = add_e1rm(clean_sets)
    out = add_velocity_flags(out)
    out = add_effort_fields(out)
    return out


def working_sets(frame: pd.DataFrame) -> pd.DataFrame:
    """Working sets only: excludes warm-ups (DEC-RIR-01)."""
    return frame[frame["is_working_set"]]


def effort_sets(frame: pd.DataFrame) -> pd.DataFrame:
    """Sets carrying a genuine effort rating, excluding warm-ups and missing RIR."""
    return frame[frame["rir_class"].eq("effort")]
