"""Turning an e1RM into a load the athlete can actually put on the bar.

Two rules, both config-driven:

* the load is solved from the e1RM using the inverse of the same formula that produced it
  (`domain.e1rm.load_for_reps`), never a second approximation;
* it is rounded DOWN to the smallest real increment. Rounding up would push the set above the
  target RIR, which is the direction that costs a session rather than a kilogram.
"""

from __future__ import annotations

from decimal import Decimal

from strength_coach.domain import e1rm as e1rm_mod

# Floating point cannot represent 0.1 exactly, so equality tests on "is this a multiple of
# 0.5" need a tolerance. A milligram is far below any plate.
_TOLERANCE = Decimal("0.000001")


def round_down(load_kg: float, increment_kg: float) -> float:
    """Largest multiple of `increment_kg` not greater than `load_kg`."""
    if increment_kg <= 0:
        raise ValueError(f"increment must be positive, got {increment_kg}")
    load = Decimal(str(load_kg))
    increment = Decimal(str(increment_kg))
    steps = (load / increment).to_integral_value(rounding="ROUND_FLOOR")
    return float(steps * increment)


def solve_load(
    e1rm_kg: float,
    reps: int,
    rir: int,
    increment_kg: float,
) -> float:
    """The rounded load that puts `reps` at `rir` given the e1RM."""
    raw = e1rm_mod.load_for_reps(e1rm_kg, reps, rir)
    return round_down(raw, increment_kg)


def is_multiple_of(load_kg: float, increment_kg: float) -> bool:
    """Whether a load is representable with the available plates."""
    load = Decimal(str(load_kg))
    increment = Decimal(str(increment_kg))
    remainder = load % increment
    return remainder <= _TOLERANCE or (increment - remainder) <= _TOLERANCE
