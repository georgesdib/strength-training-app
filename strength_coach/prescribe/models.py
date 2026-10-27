"""Prescription value objects.

Frozen dataclasses, so a prescription that has been shown to the athlete cannot be edited in
place; a correction is a new prescription with a pointer back (AGENTS.md §3.7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WarmupSet:
    """One ramp set, expressed as a percentage and its rounded load."""
    percent: float
    reps: int
    load_kg: float


@dataclass(frozen=True)
class PrescriptionItem:
    order_index: int
    exercise_id: str
    sets: int
    reps_low: int
    reps_high: int
    load_kg: float | None
    load_basis: str
    rounding_increment_kg: float
    rir_target: int | None
    rest_s: int | None
    essential: bool
    rationale_refs: tuple[str, ...] = ()
    substitution_for: str | None = None
    time_cap_s: int | None = None
    # Set when the engine refused to invent a load. The prescription is then not executable.
    unknown_load_reason: str | None = None
    # VBT target from the per-lift calibration, when one is trustworthy enough to cite.
    # None means "no target", never a guessed velocity (docs/VBT-CALIBRATION.md).
    velocity_target: float | None = None
    vbt_basis: str | None = None
    # Number of usable sets behind a formula e1RM; None for overrides/fallbacks/accessories.
    e1rm_source_sets: int | None = None
    # Mean working-set intensity as a fraction of e1RM; None when it cannot be estimated.
    intensity: float | None = None
    # Cumulative load multiplier from e1RM decay, readiness, continuity and deload. Display
    # provenance only; the stored prescription remains the source for the actual load.
    load_factor: float = 1.0
    # Resolved flare policy: hold, reviewed, dose or none. Generation-time only; the stored
    # prescription is the outcome, not this policy (DEC-SPINE-07).
    flare: str = "none"
    # Power work is quality-limited: no RIR target, a stored stop rule (DEC-POWER-02).
    effort_model: str = "rir"
    quality_stop: str | None = None
    # Main-lift ramp sets; empty for accessories and unknown loads.
    warmup: tuple[WarmupSet, ...] = ()


@dataclass(frozen=True)
class Prescription:
    for_date: str
    session_type: str
    fallback_level: str
    rule_document_version: str
    items: tuple[PrescriptionItem, ...]
    time_cap_s: int | None = None
    warnings: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    calibration_ids: tuple[str, ...] = ()
    notes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        """V0-SCOPE §4.4: every load is real, rounded, and inside its RIR window."""
        return not self.issues and all(
            item.load_kg is not None and item.unknown_load_reason is None for item in self.items
        )

    def item(self, order_index: int) -> PrescriptionItem:
        return self.items[order_index]

    def as_rows(self) -> list[dict]:
        """Flat rows, shaped for the prescription_item table."""
        return [
            {
                "order_index": item.order_index,
                "exercise_id": item.exercise_id,
                "sets": item.sets,
                "reps_low": item.reps_low,
                "reps_high": item.reps_high,
                "load_kg": item.load_kg,
                "load_basis": item.load_basis,
                "rounding_increment": item.rounding_increment_kg,
                "rir_target": item.rir_target,
                "effort_model": item.effort_model,
                "quality_stop": item.quality_stop,
                "rest_s": item.rest_s,
                "time_cap_s": item.time_cap_s,
                "essential": item.essential,
                "rationale_refs": list(item.rationale_refs),
                "substitution_for": item.substitution_for,
                "velocity_target": item.velocity_target,
                "vbt_basis": item.vbt_basis,
                "e1rm_source_sets": item.e1rm_source_sets,
                "warmup": [
                    {"percent": w.percent, "reps": w.reps, "load_kg": w.load_kg}
                    for w in item.warmup
                ],
            }
            for item in self.items
        ]
