"""Deterministic fallback.

The deterministic engine is the fallback: when the LLM layer (phase 7) is unavailable or its
proposal is vetoed, this is what the athlete gets. That is the whole point of the architecture
-- `build_prescription` never needs a model to produce a safe, executable session.

This module holds the one transformation the fallback *does* need: scaling loads down without
breaking executability (rounding, increments) or the citation trail.
"""

from __future__ import annotations

from dataclasses import replace

from strength_coach.prescribe import loads
from strength_coach.prescribe.models import Prescription, PrescriptionItem


def scale_loads(
    items: tuple[PrescriptionItem, ...],
    factor: float,
    *,
    extra_refs: tuple[str, ...] = (),
) -> tuple[PrescriptionItem, ...]:
    """Multiply every load by `factor` and round DOWN to the item's own increment.

    Rounding down matters: a 5% reduction that rounds up would sometimes leave the load
    unchanged or even higher, which would make the modifier a no-op reported as applied.
    """
    if not 0 < factor <= 1:
        raise ValueError(f"scale factor must be in (0, 1], got {factor}")
    scaled: list[PrescriptionItem] = []
    for item in items:
        if item.load_kg is None:
            scaled.append(item)
            continue
        new_load = loads.round_down(
            item.load_kg * factor, item.rounding_increment_kg
        )
        scaled.append(
            replace(item, load_kg=new_load, rationale_refs=item.rationale_refs + extra_refs)
        )
    return tuple(scaled)


def reduced_prescription(
    prescription: Prescription,
    *,
    factor: float,
    reason: str,
) -> Prescription:
    """A copy of a prescription with loads reduced, for a policy downgrade."""
    return replace(
        prescription,
        items=scale_loads(prescription.items, factor, extra_refs=("MOD-FAT-001",)),
        fallback_level="fatigue_reduced",
        warnings=prescription.warnings + (f"loads reduced to {factor:.0%}: {reason}",),
    )
