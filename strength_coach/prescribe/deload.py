"""Apply a deload decision to prescription items.

The decision itself lives in `features.deload`. This layer owns the item arithmetic. The
reducer is one-way: it never raises a set count, never removes an exercise and never pushes a
primary-compound RIR outside 1-4.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Mapping

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


def apply_items(
    items: Iterable[PrescriptionItem],
    decision: DeloadDecision | None,
    *,
    config: DeloadConfig | None = None,
    prior_load_factors: Mapping[str, float] | None = None,
    primary_compounds: Iterable[str] = (),
) -> tuple[tuple[PrescriptionItem, ...], str | None, dict | None, str]:
    """Reduce one deload week without ever adding work.

    `prior_load_factors` is the cumulative factor already applied by readiness and continuity.
    The deload uses the more restrictive single factor: if readiness is already stricter than
    the deload multiplier, the deload does not cut load again.
    """
    if decision is None:
        return tuple(items), None, None, "full"
    cfg = config or DeloadConfig.load()
    factors = dict(prior_load_factors or {})
    primary = {str(value) for value in primary_compounds}
    refs = ("MOD-DELOAD-001",)
    out: list[PrescriptionItem] = []
    changed_sets = 0
    changed_loads = 0
    capped_rir = 0
    for item in items:
        if item.essential and not cfg.include_essential:
            out.append(item)
            continue
        # One-way floor: a 1-set item stays at 1 even when the configured floor is 2.
        proposed = item.sets - cfg.set_reduction
        new_sets = min(item.sets, max(cfg.minimum_sets, proposed))
        if new_sets != item.sets:
            changed_sets += 1
        new_load = item.load_kg
        prior = max(1e-9, float(factors.get(item.exercise_id, 1.0)))
        if new_load is not None and cfg.load_multiplier < prior:
            # Apply only the difference needed to reach the deload factor from the base load;
            # never multiply an already-reduced load by another independent factor.
            ratio = cfg.load_multiplier / prior
            candidate = loads.round_down(new_load * ratio, item.rounding_increment_kg)
            if candidate != new_load:
                changed_loads += 1
                new_load = candidate
        new_rir = item.rir_target + cfg.rir_add
        if item.exercise_id in primary:
            capped = min(4, new_rir)
            if capped != new_rir:
                capped_rir += 1
            new_rir = capped
        out.append(replace(
            item,
            sets=new_sets,
            load_kg=new_load,
            rir_target=new_rir,
            rationale_refs=item.rationale_refs + refs,
        ))
    label = "reactive deload: " if "reactive" in decision.trigger else ""
    warning = (
        f"MOD-DELOAD-001: {label}{decision.reason}; "
        f"sets -{cfg.set_reduction} (floor {cfg.minimum_sets}), "
        f"load factor {cfg.load_multiplier:.0%} (most restrictive), "
        f"RIR +{cfg.rir_add}"
    )
    note = {
        "trigger": decision.trigger,
        "reason": decision.reason,
        "block_week": decision.block_week,
        "set_reduction": cfg.set_reduction,
        "minimum_sets": cfg.minimum_sets,
        "load_multiplier": cfg.load_multiplier,
        "rir_add": cfg.rir_add,
        "items_changed_sets": changed_sets,
        "items_changed_loads": changed_loads,
        "rir_capped": capped_rir,
    }
    return tuple(out), warning, note, "fatigue_reduced"


def apply(
    prescription: Prescription,
    decision: DeloadDecision | None,
    *,
    config: DeloadConfig | None = None,
    prior_load_factors: Mapping[str, float] | None = None,
    primary_compounds: Iterable[str] = (),
) -> Prescription:
    """Compatibility wrapper for callers that hold a full Prescription."""
    items, warning, note, fallback = apply_items(
        prescription.items, decision, config=config,
        prior_load_factors=prior_load_factors,
        primary_compounds=primary_compounds,
    )
    if decision is None or note is None:
        return prescription
    return replace(
        prescription,
        items=warmup.refresh(items),
        fallback_level=fallback,
        warnings=prescription.warnings + (warning,),
        notes={**prescription.notes, "deload": note},
    )
