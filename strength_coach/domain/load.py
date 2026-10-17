"""Load resolution and rounding.

Two problems live here:

1. **What does the logged number mean?** The same column holds three things (DQ-BW-01):
   nothing for an unweighted movement, the athlete's total mass when the device captured
   bodyweight, and a genuinely added plate. `resolve_load_basis` disambiguates using the
   exercise's `bodyweight_type` property and the athlete's bodyweight on that date.

2. **Which side do we round to?** A prescription must never round *up*. Rounding a
   computed 102.5 kg target to 105 kg prescribes more than the rules allow, so all
   prescription rounding floors to the available increment. E1RM and analysis are never
   rounded at all — rounding is a presentation concern for the prescription only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

LoadBasis = Literal["external", "bodyweight_total", "added", "unknown"]

# Midpoint between the two clusters actually observed in the log: added loads sit below
# 10 kg while captured-bodyweight values sit within a few percent of 100-107 kg.
BODYWEIGHT_TOTAL_LOW = 0.50
BODYWEIGHT_TOTAL_HIGH = 1.15

DEFAULT_INCREMENT_KG = 2.5

# DEC-LOAD-02: the athlete chooses ADDED LOAD as the progression axis for bodyweight
# movements. So a pull-up is programmed as "bodyweight + 2.5 kg", never as "104 kg", and
# the double-progression increment applies to the plate. Total mass is still the correct
# input for an e1RM, which is why both are carried on ResolvedLoad.
PROGRESSION_BASIS_BODYWEIGHT = "added"


@dataclass(frozen=True)
class ResolvedLoad:
    """A logged weight, its meaning, and the external load that was actually added."""

    basis: LoadBasis
    external_load_kg: float | None
    total_load_kg: float | None
    reason: str


def resolve_load_basis(
    weight_kg: float | None,
    *,
    bodyweight_kg: float | None,
    is_bodyweight_type: bool,
    is_time_based: bool = False,
) -> ResolvedLoad:
    """Classify one logged weight. Implements DQ-BW-01 in the documented order."""
    if is_time_based:
        # Planks and carries: the logged number (if any) is a plate, but the movement is
        # scored on seconds, so tonnage is undefined and load_basis carries no meaning
        # beyond bookkeeping.
        return ResolvedLoad(
            basis="external",
            external_load_kg=weight_kg,
            total_load_kg=None,
            reason="time-based movement: tonnage undefined",
        )

    if weight_kg is None:
        return ResolvedLoad("unknown", None, None, "no weight logged")

    if weight_kg == 0:
        # Zero on a loadable movement means it was performed unweighted, not unrecorded.
        if is_bodyweight_type:
            return ResolvedLoad(
                basis="bodyweight_total",
                external_load_kg=0.0,
                total_load_kg=bodyweight_kg,
                reason="unweighted bodyweight movement",
            )
        return ResolvedLoad("external", 0.0, 0.0, "bar-only or unweighted")

    if not is_bodyweight_type:
        return ResolvedLoad("external", weight_kg, weight_kg, "external load")

    if bodyweight_kg is None or bodyweight_kg <= 0:
        return ResolvedLoad(
            basis="unknown",
            external_load_kg=None,
            total_load_kg=None,
            reason="bodyweight movement but no bodyweight on record",
        )

    ratio = weight_kg / bodyweight_kg
    if BODYWEIGHT_TOTAL_LOW < ratio <= BODYWEIGHT_TOTAL_HIGH:
        return ResolvedLoad(
            basis="bodyweight_total",
            external_load_kg=0.0,
            total_load_kg=weight_kg,
            reason=f"logged weight is {ratio:.2f} x bodyweight -> captured total mass",
        )

    if 0 < ratio <= BODYWEIGHT_TOTAL_LOW:
        return ResolvedLoad(
            basis="added",
            external_load_kg=weight_kg,
            total_load_kg=bodyweight_kg + weight_kg,
            reason=f"logged weight is {ratio:.2f} x bodyweight -> added load",
        )

    return ResolvedLoad(
        basis="unknown",
        external_load_kg=None,
        total_load_kg=None,
        reason=f"logged weight is {ratio:.2f} x bodyweight -> outside known clusters",
    )


def progression_load(resolved: ResolvedLoad, *, is_bodyweight_type: bool) -> float | None:
    """The load a progression decision or a prescription should act on.

    Implements DEC-LOAD-02. For an ordinary barbell lift this is simply the external load.
    For a bodyweight movement it is the *added* load, with a device-captured total-mass
    reading resolving to 0 kg added (because the bar is the athlete).
    """
    if not is_bodyweight_type:
        return resolved.external_load_kg
    if resolved.basis == "bodyweight_total":
        # The logged number included the athlete's mass; nothing was added.
        return 0.0
    if resolved.basis == "added":
        return resolved.external_load_kg
    # Unknown basis: refuse to invent a progression load.
    return None


def default_increment_kg(load_kg: float | None) -> float:
    """Smallest sensible jump for a given load.

    This log contains 0.5, 1.0 and 2.5 kg steps, so a single global constant would
    over-prescribe small lifts. Until the per-exercise increment table is confirmed
    (docs/DATA-QUALITY.md), small loads get a smaller step.
    """
    if load_kg is None:
        return DEFAULT_INCREMENT_KG
    if load_kg < 20:
        return 1.0
    if load_kg < 40:
        return 2.0
    return DEFAULT_INCREMENT_KG


def round_load_down(load_kg: float | None, increment_kg: float | None = None) -> float | None:
    """Floor a load to the available increment.

    Flooring, never nearest/up: a prescription must not exceed the value the rules
    produced. For a 102.5 kg computed target with 2.5 kg plates this returns 102.5;
    for 103.0 it returns 102.5.
    """
    if load_kg is None:
        return None
    # Explicit None check: `or` would silently swallow a 0 increment, which is a
    # programming error rather than a request for the default.
    increment = DEFAULT_INCREMENT_KG if increment_kg is None else increment_kg
    if increment <= 0:
        raise ValueError("increment_kg must be positive")
    # The epsilon guards against 99.99999 -> 97.5 style errors from float division.
    steps = math.floor((load_kg + 1e-9) / increment)
    return round(steps * increment, 6)


def round_load_up(load_kg: float | None, increment_kg: float | None = None) -> float | None:
    """Ceiling variant, provided for analysis and reporting only — never prescriptions."""
    if load_kg is None:
        return None
    increment = DEFAULT_INCREMENT_KG if increment_kg is None else increment_kg
    if increment <= 0:
        raise ValueError("increment_kg must be positive")
    steps = math.ceil((load_kg - 1e-9) / increment)
    return round(steps * increment, 6)


def apply_percent_modifier(load_kg: float | None, multiplier: float) -> float | None:
    """Scale a load (used by fatigue modifiers, e.g. 0.90-0.95)."""
    if load_kg is None:
        return None
    return load_kg * multiplier
