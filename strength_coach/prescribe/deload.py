"""Apply a deload decision to a built prescription.

Kept in the prescription layer because it edits PrescriptionItem values. The decision itself
lives in `features.deload`, which owns the policy and the block/reactive triggers.
"""

from __future__ import annotations

from dataclasses import replace

from strength_coach.features.deload import DeloadConfig, DeloadDecision
from strength_coach.prescribe import loads, warmup
from strength_coach.prescribe.models import Prescription, PrescriptionItem


def suggest(prescription: Prescription, decision: DeloadDecision | None) -> Prescription:
    """Record a scheduled deload as a suggestion, without changing the session."""
    if decision is None:
        return prescription
    return replace(
        prescription,
        warnings=prescription.warnings + (
            f"deload suggested: {decision.reason}; train as planned unless confirmed",
        ),
        notes={
            **prescription.notes,
            "deload_suggestion": {
                "trigger": decision.trigger,
                "reason": decision.reason,
                "block_week": decision.block_week,
                "applied": False,
            },
        },
    )


def apply(
    prescription: Prescription,
    decision: DeloadDecision | None,
    *,
    config: DeloadConfig | None = None,
) -> Prescription:
    """Reduce sets/load and add RIR for one deload week, preserving the citation trail."""
    if decision is None:
        return prescription
    cfg = config or DeloadConfig.load()
    refs = ("MOD-DELOAD-001",)
    items: list[PrescriptionItem] = []
    changed_sets = 0
    changed_loads = 0
    for item in prescription.items:
        if item.essential and not cfg.include_essential:
            items.append(item)
            continue
        new_sets = max(cfg.minimum_sets, item.sets - cfg.set_reduction)
        if new_sets != item.sets:
            changed_sets += 1
        new_load = item.load_kg
        if new_load is not None:
            candidate = loads.round_down(
                new_load * cfg.load_multiplier, item.rounding_increment_kg
            )
            if candidate != new_load:
                changed_loads += 1
                new_load = candidate
        items.append(replace(
            item,
            sets=new_sets,
            load_kg=new_load,
            rir_target=item.rir_target + cfg.rir_add,
            rationale_refs=item.rationale_refs + refs,
        ))
    label = "reactive deload: " if "reactive" in decision.trigger else ""
    warning = (
        f"MOD-DELOAD-001: {label}{decision.reason}; "
        f"sets -{cfg.set_reduction}, load {cfg.load_multiplier:.0%}, "
        f"RIR +{cfg.rir_add}"
    )
    return replace(
        prescription,
        items=warmup.refresh(tuple(items)),
        fallback_level="fatigue_reduced",
        warnings=prescription.warnings + (warning,),
        notes={
            **prescription.notes,
            "deload": {
                "trigger": decision.trigger,
                "reason": decision.reason,
                "block_week": decision.block_week,
                "set_reduction": cfg.set_reduction,
                "load_multiplier": cfg.load_multiplier,
                "rir_add": cfg.rir_add,
                "items_changed_sets": changed_sets,
                "items_changed_loads": changed_loads,
            },
        },
    )
