"""The deterministic Day B prescription engine.

Python computes, the LLM explains (AGENTS.md §1). Every number here comes from a stored fact
or a config value, and every item carries the citations that justify it, so the rationale
validator can refuse a prescription whose reasoning does not resolve.

Order of operations is deliberate:

1. read history only up to `for_date` — no look-ahead, or a backtest would be a lie;
2. derive loads from e1RM (main lifts) or double progression (accessories);
3. apply MOD-FAT-001, which can only *reduce* a load;
4. validate executability, including the weekly spinal cap, using the same function the
   rule uses — so a prescription cannot satisfy the engine and violate the constitution.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Mapping

import pandas as pd

from strength_coach.features import injury_signal as injury_signal_mod
from strength_coach.features import readiness as readiness_mod
from strength_coach.features import readiness_score
from strength_coach.prescribe import config as config_mod
from strength_coach.prescribe import constraints as constraints_mod
from strength_coach.features import e1rm_calibration as e1rm_calibration_feature
from strength_coach.features import continuity_calibration
from strength_coach.features import volume as volume_feature
from strength_coach.features import e1rm_decay as e1rm_decay_feature
from strength_coach.features import lift_readiness as lift_readiness_feature
from strength_coach.features import recent_stress as recent_stress_feature
from strength_coach.features import vbt_calibration
from strength_coach.prescribe import schemes as schemes_mod
from strength_coach.prescribe import undulation as undulation_mod
from strength_coach.prescribe import fallback, loads, schedule, templates
from strength_coach.prescribe import selection as selection_mod
from strength_coach.prescribe.models import Prescription, PrescriptionItem
from strength_coach.rules import History, RuleContext, evaluate, load_document, registry
from strength_coach.rules import policy as policy_mod
from strength_coach.store import queries, repositories
from strength_coach.utils import exercises as exercises_mod

RULE_REF_RE = re.compile(r"^(PRG|MOD)(?:-[A-Z0-9]+)+-\d{3}$")
# Which readiness fields drive the modifier, and at what threshold, is config
# (config/readiness.v1.yaml); this module no longer hardcodes either.


def build_prescription(
    conn,
    *,
    for_date: str,
    session_day: str = "B",
    document=None,
    thresholds: config_mod.Thresholds | None = None,
    template: templates.DayTemplate | None = None,
    readiness_config: readiness_mod.ReadinessConfig | None = None,
    undulation: undulation_mod.Undulation | None = None,
    history: History | None = None,
    vbt: vbt_calibration.CalibrationResult | None = None,
    apply_selection: bool = False,
    selection_chooser: Callable | None = None,
    session_type: str | None = None,
) -> Prescription:
    """Generate the deterministic session for `for_date`.

    `history` and `vbt` are optional precomputed inputs for callers that build more than one
    prescription from the same past (the programme forecast): the enriched frame and the VBT
    calibration do not change with the forecast date, so recomputing them per entry is waste.
    """
    document = document or load_document()
    thresholds = thresholds or config_mod.Thresholds.load()
    if session_type is not None:
        if template is None:
            template = templates.SessionTemplate.load(session_type)
        session_day = schedule.legacy_day(session_type)
    else:
        template = template or templates.DayTemplate.load(session_day)
    readiness_config = readiness_config or readiness_mod.ReadinessConfig.load()
    undulation = undulation or undulation_mod.Undulation.load()

    context = RuleContext.from_store(
        conn, end=for_date, rep_ranges=templates.all_rep_ranges(), history=history
    )
    policy_result = evaluate(document, context)
    decisions = policy_result.verdict("PRG-DP-001").details.get("decisions", {})

    items: list[PrescriptionItem] = []
    warnings: list[str] = []
    selection_rows: dict[str, selection_mod.SlotSelection] = {}
    selection_notes: list[dict] = []
    if apply_selection:
        selected = selection_mod.select(
            conn, context, for_date, session_day,
            session_type=session_type, chooser=selection_chooser,
        )
        selection_rows = {row.slot_id: row for row in selected}
        selection_notes = [row.as_dict() for row in selected]

    e1rm_factors = e1rm_calibration_feature.factors(
        conn, for_date, window_days=thresholds.e1rm_window_days
    )
    for index, slot in enumerate(template.slots):
        selected_row = selection_rows.get(slot.id)
        selected_exercise = (
            selected_row.suggested
            if selected_row is not None and selected_row.changed else None
        )
        item, slot_warnings = build_item(
            conn, context, slot, index, thresholds, for_date, decisions, template,
            calibration_factors=e1rm_factors, exercise_id=selected_exercise,
        )
        if selected_exercise is not None:
            item = replace(
                item,
                rationale_refs=item.rationale_refs + ("MOD-SELECT-001",),
            )
            warnings.append(
                f"MOD-SELECT-001: {slot.id} selected {selected_exercise} "
                f"({selected_row.source}); load re-solved from its own history"
            )
        items.append(item)
        warnings.extend(slot_warnings)
    dup_plan = None
    if undulation.enabled and context.block_week_index:
        items, dup_warnings, dup_plan = _apply_undulation(
            conn, context, tuple(items), template, thresholds, for_date, decisions, undulation,
            calibration_factors=e1rm_factors,
        )
        warnings.extend(dup_warnings)

    fallback_level = "full"
    # Injury status is needed for the readiness ceiling, so compute it before applying the
    # readiness factor. It is also used later for advisory warnings.
    injury = injury_signal_mod.compute(
        conn, for_date, ramp_week=context.block_week_index
    )
    readiness = queries.readiness_day(conn, for_date)
    assessment = readiness_score.compute(conn, for_date)
    trigger = readiness_config.trigger(readiness)
    if assessment.status == "unknown":
        warnings.append(
            f"readiness unknown for {for_date}; fatigue modifier not applied"
        )
    elif assessment.status == "insufficient":
        warnings.append(
            f"readiness insufficient for {for_date}: {assessment.basis}; "
            "score not applied"
        )

    vbt_cal = vbt
    if vbt_cal is None and not context.sets.empty:
        vbt_cal = vbt_calibration.calibrate(context.sets)
    items, readiness_level, readiness_warnings, readiness_factors, lift_readiness = _apply_readiness_score(
        conn, context, tuple(items), for_date, assessment, injury, trigger, thresholds,
        readiness_config=readiness_config, calibration=vbt_cal,
    )
    if readiness_level == "fatigue_reduced":
        fallback_level = "fatigue_reduced"
    warnings.extend(readiness_warnings)

    if context.symptom_flare is True:
        # MOD-BACK-001: a flare returns erector work to the weeks 1-3 dose and holds main
        # lifts at RIR 3-4 for the week. Applied after the fatigue modifier, so a flare
        # always wins over a load reduction.
        items = list(_apply_back_flare(tuple(items), context, thresholds))
        warnings.append(
            f"MOD-BACK-001: back flare (level {context.symptom_level}, {context.symptom_on}); "
            f"erector work back to the weeks 1-3 dose, main lifts at RIR "
            f"{thresholds.back_flare_main_rir}"
        )

    continuity_cal = None
    if context.gap_days is not None and context.gap_days >= thresholds.continuity_short_days:
        continuity_cal = continuity_calibration.compute(
            context.sets,
            short_days=thresholds.continuity_short_days,
            medium_days=thresholds.continuity_medium_days,
            long_days=thresholds.continuity_long_days,
            medium_multiplier=thresholds.continuity_medium_multiplier,
            long_multiplier=thresholds.continuity_long_multiplier,
        )
    items, gap_level, gap_warnings = _apply_continuity(
        context, tuple(items), thresholds, prior_factors=readiness_factors,
        calibration=continuity_cal,
    )
    if gap_level == "fatigue_reduced":
        fallback_level = "fatigue_reduced"
    warnings.extend(gap_warnings)

    items, calibration_ids, vbt_note = _attach_vbt_targets(
        conn, context, tuple(items), for_date, fallback_level, calibration=vbt_cal
    )

    items, volume_warnings, volume_note = _apply_volume_cap(
        context, tuple(items), for_date
    )
    warnings.extend(volume_warnings)

    # Injury signals are context, never policy: a flaring region adds a warning naming the
    # lifts that load it, but never vetoes or edits a load (DEC-INJURY-01).
    warnings.extend(_injury_warnings(injury, tuple(items)))

    # Stored athlete state is applied deterministically: a hard constraint vetoes, a
    # suitability rating is surfaced. Unrecorded state is reported, never read as permission.
    constraint_report = constraints_mod.evaluate(conn, [item.exercise_id for item in items])
    if not constraint_report.recorded:
        warnings.append(
            "athlete state not recorded: constraints were not evaluated (they are unknown, "
            "not absent)"
        )
    warnings.extend(constraint_report.warnings)

    issues = validate_prescription(tuple(items), context, document, session_day, for_date)
    for exercise_id, reason in constraint_report.vetoes:
        issues.append(f"CONSTRAINT_VETO:{exercise_id}:{reason}")

    for verdict in policy_result.unknowns:
        warnings.append(
            f"{verdict.rule_id} not assessable: missing {', '.join(verdict.missing_inputs)}"
        )

    # Advisory recent stress: visible context, never a load change (DEC-STRESS-01).
    stress = recent_stress_feature.compute(context.sets, for_date)
    warnings.extend(recent_stress_feature.advisories(
        stress, tuple(item.exercise_id for item in items)
    ))

    return Prescription(
        for_date=for_date,
        session_day=session_day,
        session_type=session_type,
        fallback_level=fallback_level,
        rule_document_version=document.version,
        items=tuple(items),
        time_cap_s=template.time_cap_s,
        warnings=tuple(warnings),
        issues=tuple(issues),
        calibration_ids=tuple(calibration_ids),
        notes={
            # VBT now attaches a real target where the calibration is trustworthy, and says so
            # when it is not. The upgrade path (per-rep velocity loss, individual load-velocity
            # profiles) is recorded in docs/VBT-CALIBRATION.md.
            "vbt": vbt_note,
            "recent_stress": recent_stress_feature.as_dict(stress),
            "per_lift_readiness": lift_readiness_feature.as_dict(lift_readiness),
            "e1rm_calibration": {
                key: {"factor": row.correction_factor, "reason": row.correction_reason}
                for key, row in e1rm_factors.items()
            },
            "undulation_week": (
                ((int(context.block_week_index) - 1) % undulation.cycle_weeks) + 1
                if dup_plan and undulation.cycle_weeks else None
            ),
            "undulation": dict(dup_plan) if dup_plan else {},
            "gap_days": context.gap_days,
            "gap_band": _gap_band(context.gap_days, thresholds),
            "continuity_calibration": (
                continuity_cal.as_dict() if continuity_cal is not None else None
            ),
            "injury_signal": injury.as_dict(),
            "policy_outcome": policy_result.outcome,
            "e1rm_window_days": thresholds.e1rm_window_days,
            "fatigue_trigger": trigger,
            "readiness_fields": list(readiness_config.modifier_fields),
            "readiness_set_reduction": {
                "enabled": readiness_config.set_reduction_enabled,
                "score_below": readiness_config.set_reduction_score_below,
                "sets": readiness_config.set_reduction_sets,
                "include_essential": readiness_config.set_reduction_include_essential,
            },
            "back_flare": bool(context.symptom_flare),
            "constraints": constraint_report.status,
            "session_type": session_type,
            "volume_management": volume_note,
            "selection": {
                "applied": bool(apply_selection),
                "llm_requested": bool(selection_chooser),
                "llm_used": any(row.get("source") == "llm" for row in selection_notes),
                "slots": selection_notes,
            },
        },
    )


# Lifts whose velocity signal is not trustworthy enough to prescribe from (docs/VBT-EVIDENCE.md).
VBT_UNRELIABLE = {"trap_bar_deadlift"}


def _apply_volume_cap(
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    for_date: str,
) -> tuple[tuple[PrescriptionItem, ...], tuple[str, ...], dict]:
    """Trim non-essential sets when a pattern would exceed its configured MRV.

    The cap is deliberately one-directional: under-MEV is reported by the volume ledger but is
    never auto-filled. The MRV landmark is a coaching heuristic, not a measured individual
    threshold, so only accessories are trimmed; an essential item is never silently cut.
    """
    cfg = volume_feature.VolumeConfig.load()
    if not cfg.apply_mrv_cap or cfg.landmarks is None:
        return items, (), {"applied": False, "reason": "cap disabled"}

    cutoff = pd.Timestamp(for_date) - pd.Timedelta(days=7)
    prior = context.sets
    if not prior.empty and "is_working_set" in prior:
        prior = prior[prior["is_working_set"].astype(bool)]
        prior = prior[(prior["date"] > cutoff) & (prior["date"] <= pd.Timestamp(for_date))]
    prior_counts: dict[str, int] = {}
    if not prior.empty:
        for exercise_id in prior["exercise_id"].astype(str).unique():
            pattern = context.entity(exercise_id).get("pattern")
            key = volume_feature.volume_target_key(pattern) if pattern else None
            if key:
                count = int((prior["exercise_id"].astype(str) == exercise_id).sum())
                prior_counts[key] = prior_counts.get(key, 0) + count

    proposed: dict[str, list[int]] = {}
    for index, item in enumerate(items):
        pattern = context.entity(item.exercise_id).get("pattern")
        key = volume_feature.volume_target_key(pattern) if pattern else None
        if key:
            proposed.setdefault(key, []).append(index)

    warnings: list[str] = []
    changed: dict[int, int] = {}
    for key, indexes in proposed.items():
        landmark = cfg.landmarks.get(key)
        if landmark is None:
            continue
        mrv = landmark[3]
        total = prior_counts.get(key, 0) + sum(items[i].sets for i in indexes)
        if total <= mrv:
            continue
        for index in indexes:
            if items[index].essential:
                continue
            if total <= mrv:
                break
            item = items[index]
            cut = min(item.sets - 1, total - mrv)
            if cut > 0:
                changed[index] = item.sets - cut
                total -= cut
        if total > mrv:
            warnings.append(
                f"volume: {key} would reach {total:g} hard sets in 7 days, above MRV "
                f"{mrv:g}; no non-essential sets left to trim"
            )

    out: list[PrescriptionItem] = []
    for index, item in enumerate(items):
        if index not in changed:
            out.append(item)
            continue
        out.append(replace(
            item,
            sets=changed[index],
            rationale_refs=item.rationale_refs + ("MOD-VOL-001",),
        ))
    if changed:
        warnings.append(
            "MOD-VOL-001: trimmed non-essential sets to stay at or below the configured MRV"
        )
    return tuple(out), tuple(warnings), {
        "applied": bool(changed),
        "reductions": {items[i].exercise_id: items[i].sets - sets
                       for i, sets in changed.items()},
        "warning_count": len(warnings),
    }


def _injury_warnings(signal: injury_signal_mod.InjurySignal,
                     items: tuple[PrescriptionItem, ...]) -> list[str]:
    """Name the prescribed lifts that load a currently flaring region.

    Low back is excluded because MOD-BACK-001 already reports it; naming it twice would bury
    the modifier's own warning. Advisory only — it never vetoes or edits a load.
    """
    warnings: list[str] = []
    for region in signal.regions:
        if region.status != injury_signal_mod.STATUS_ACTIVE or region.region == "low_back":
            continue
        hits = sorted({
            item.exercise_id for item in items
            if item.exercise_id in region.linked_exercises
        })
        if hits:
            warnings.append(
                f"injury signal: {region.label} is flaring; this session loads it via "
                f"{', '.join(hits)} (advisory; the athlete decides)"
            )
    return warnings


def _apply_readiness_score(
    conn,
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    for_date: str,
    assessment,
    injury,
    trigger: str | None,
    thresholds,
    *,
    readiness_config: readiness_mod.ReadinessConfig | None = None,
    calibration: "vbt_calibration.CalibrationResult | None" = None,
) -> tuple[tuple[PrescriptionItem, ...], str, tuple[str, ...], dict[str, float],
           dict[str, lift_readiness_feature.LiftReadiness]]:
    """Apply the readiness factor per item, with the old sleep/energy floor.

    The injury ceiling is folded into the per-item score before the factor is chosen, so a
    high readiness score can never lift an item above its injury status. The old
    sleep/energy trigger remains a floor for partial days that cannot form a score.
    """
    floor_factor = thresholds.fatigue_load_multiplier if trigger else 1.0
    # Per-lift readiness: a lower score may reduce this lift's load; a higher one never
    # raises it. Without a ready global score there is no base to adjust, so it stays empty.
    lift_scores: dict[str, lift_readiness_feature.LiftReadiness] = {}
    prepared: dict[str, tuple[float | None, float, int, float]] = {}
    if assessment.status == "ready":
        base_scores: dict[str, float] = {}
        for item in items:
            entity = (context.entities or {}).get(item.exercise_id, {})
            effective = readiness_score.effective(
                assessment, conn, item.exercise_id, entity, signal=injury
            )
            prepared[item.exercise_id] = effective
            if effective[0] is not None:
                base_scores[item.exercise_id] = float(effective[0])
        lift_scores = lift_readiness_feature.compute(
            context.sets, base_scores, for_date, calibration=calibration
        )
    config = readiness_config or readiness_mod.ReadinessConfig.load()
    poor_for_sets = bool(
        config.set_reduction_enabled
        and (
            trigger is not None
            or (assessment.score is not None
                and assessment.score < config.set_reduction_score_below)
        )
    )
    out: list[PrescriptionItem] = []
    reduced = False
    capped = False
    scored = False
    lift_reduced: list[str] = []
    sets_reduced: list[str] = []
    factors: dict[str, float] = {}
    for item in items:
        entity = (context.entities or {}).get(item.exercise_id, {})
        factor = 1.0
        rir_bump = 0
        score = None
        ceiling = 1.0
        if assessment.status == "ready":
            score, factor, rir_bump, ceiling = prepared[item.exercise_id]
            scored = True
            lift = lift_scores.get(item.exercise_id)
            if lift is not None and lift.score < score:
                # Asymmetric on purpose: evidence for per-lift readiness is weak, so it can
                # only add caution, never make the session harder.
                previous = factor
                score = min(lift.score, ceiling)
                factor, rir_bump = readiness_score.factor_for(score)
                if factor < previous:
                    lift_reduced.append(item.exercise_id)
                scored = True
        factor = min(factor, floor_factor)
        if trigger and floor_factor < 1.0:
            rir_bump = max(rir_bump, 1)
        factors[item.exercise_id] = min(factors.get(item.exercise_id, 1.0), factor)
        new_sets = item.sets
        if (poor_for_sets and config.set_reduction_sets > 0
                and (config.set_reduction_include_essential or not item.essential)):
            new_sets = max(1, item.sets - config.set_reduction_sets)
            if new_sets != item.sets:
                sets_reduced.append(item.exercise_id)
        if factor >= 1.0 and rir_bump == 0 and new_sets == item.sets:
            out.append(item)
            continue
        reduced = True
        refs = item.rationale_refs + ("MOD-FAT-001", f"readiness:{for_date}")
        if score is not None:
            refs += (f"readiness_score:{score:.3f}",)
        if ceiling < 1.0:
            capped = True
        scope = None
        category = readiness_score.category_for(item.exercise_id, entity)
        if category:
            scope = f"category:{category}"
        override = assessment.overrides.get(scope) if scope else None
        override = override or assessment.overrides.get("global")
        if override is not None:
            refs += (f"readiness_override:{override['override_id']}",)
        new_load = item.load_kg
        if new_load is not None:
            new_load = loads.round_down(
                new_load * factor, item.rounding_increment_kg
            )
        out.append(
            replace(
                item,
                sets=new_sets,
                load_kg=new_load,
                rir_target=min(4, item.rir_target + rir_bump),
                rationale_refs=refs,
            )
        )
    warnings: list[str] = []
    if reduced:
        pieces = []
        if scored and assessment.score is not None:
            pieces.append(f"readiness score {assessment.score:.2f}")
        if trigger:
            pieces.append(f"floor {trigger}")
        if capped:
            pieces.append("injury ceiling applied")
        if lift_reduced:
            pieces.append("per-lift readiness applied: " + ", ".join(lift_reduced))
        if sets_reduced:
            pieces.append("accessory sets reduced: " + ", ".join(sets_reduced))
        warnings.append(
            "MOD-FAT-001: " + "; ".join(pieces) + "; session reduced"
        )
    return (tuple(out), ("fatigue_reduced" if reduced else "full"), tuple(warnings),
            factors, lift_scores)


def _gap_band(gap_days: int | None, thresholds: config_mod.Thresholds) -> str | None:
    if gap_days is None or gap_days < thresholds.continuity_short_days:
        return None
    if gap_days >= thresholds.continuity_long_days:
        return "long"
    if gap_days >= thresholds.continuity_medium_days:
        return "medium"
    return "short"


def _apply_continuity(
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    thresholds: config_mod.Thresholds,
    *,
    prior_factors: Mapping[str, float] | None = None,
    calibration: continuity_calibration.Calibration | None = None,
) -> tuple[tuple[PrescriptionItem, ...], str, tuple[str, ...]]:
    """Return-to-training adjustment after a gap (DEC-CONTINUITY-01).

    The gap is detected from stored history; a declared break is optional. Short gaps add one
    RIR only. From 28 days the load is reduced and the same RIR bump applied; from 56 days the
    reduction is larger and the context has already stepped the ramp back one stage.
    Bodyweight work cannot shed load, so it loses a set instead.
    """
    band = _gap_band(context.gap_days, thresholds)
    if band is None:
        return items, "full", ()

    if band == "long":
        multiplier = thresholds.continuity_long_multiplier
    elif band == "medium":
        multiplier = thresholds.continuity_medium_multiplier
    else:
        multiplier = 1.0
    fixed_multiplier = multiplier
    calibrated = False
    if calibration is not None:
        estimate = calibration.bands.get(band)
        if estimate is not None and estimate.applied:
            multiplier = estimate.factor
            calibrated = True
    bump = thresholds.continuity_rir_bump
    prior_factors = prior_factors or {}
    capped = False
    out: list[PrescriptionItem] = []
    for item in items:
        refs = item.rationale_refs + ("MOD-GAP-001",)
        rir = min(4, item.rir_target + bump)
        if multiplier < 1.0 and item.load_kg is not None and item.load_kg > 0:
            prior = prior_factors.get(item.exercise_id, 1.0)
            applied = multiplier
            if prior * multiplier < 0.80:
                # The readiness factor is already on the item; do not let the pair exceed the
                # 20% combined cap. If readiness alone is beyond it, add nothing further.
                applied = min(1.0, 0.80 / prior)
                capped = capped or applied > multiplier
            out.append(replace(
                item,
                load_kg=loads.round_down(
                    item.load_kg * applied, item.rounding_increment_kg
                ),
                rir_target=rir,
                rationale_refs=refs,
            ))
        elif multiplier < 1.0 and item.load_basis == "bodyweight_total":
            out.append(replace(
                item,
                sets=max(1, item.sets - 1),
                rir_target=rir,
                rationale_refs=refs,
            ))
        else:
            out.append(replace(item, rir_target=rir, rationale_refs=refs))

    calibration_note = ""
    if calibrated:
        calibration_note = (
            f"; calibrated factor {multiplier:.3f} from "
            f"{calibration.bands[band].n} returns (fixed {fixed_multiplier:.2f})"
        )
    warnings = (
        f"MOD-GAP-001: {context.gap_days}-day gap; prescription amended "
        f"({'load reduced, ' if multiplier < 1 else ''}one extra RIR"
        f"{'; combined readiness+continuity capped at 20%' if capped else ''}"
        f"{calibration_note})",
    )
    return tuple(out), "fatigue_reduced" if multiplier < 1 else "full", warnings


def _attach_vbt_targets(
    conn,
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    for_date: str,
    fallback_level: str,
    *,
    calibration: "vbt_calibration.CalibrationResult | None" = None,
) -> tuple[tuple[PrescriptionItem, ...], tuple[str, ...], dict[str, Any]]:
    """Attach velocity targets from the per-lift calibration, when it is trustworthy.

    The calibration needs 12 sets across 3 sessions per lift before it produces a target; with
    the current export that is often unavailable, and the honest answer is "no target" rather
    than a plausible velocity. A session already modified by a safety rule is skipped: its load
    no longer matches the calibration's assumptions.
    """
    if fallback_level != "full" or context.symptom_flare:
        return items, (), {
            "status": "skipped",
            "reason": "session modified by a safety rule; load no longer matches the calibration",
        }
    if context.sets.empty:
        return items, (), {"status": "unavailable", "reason": "no stored sets"}

    result = calibration or vbt_calibration.calibrate(context.sets)
    if not result.targets:
        return items, (), {
            "status": "unavailable",
            "reason": "no lift has 12 clean sets across 3 sessions with velocity",
            "upgrade": "per-rep velocity and individual load-velocity profiles are deferred "
                       "(docs/VBT-CALIBRATION.md)",
        }

    out: list[PrescriptionItem] = []
    ids: list[str] = []
    withheld: list[str] = []
    for item in items:
        if item.exercise_id in VBT_UNRELIABLE:
            # Chen et al. 2026 found hex-bar RIR-velocity relationships fail the accuracy bar;
            # a target here would be a confident-looking number the evidence does not support.
            withheld.append(item.exercise_id)
            out.append(item)
            continue
        target = result.lookup(item.exercise_id, item.reps_low)
        if target is None:
            out.append(item)
            continue
        calibration_id = _persist_calibration(conn, target, for_date)
        ids.append(calibration_id)
        out.append(
            replace(
                item,
                velocity_target=target.velocity_median,
                vbt_basis=f"{target.scope} · {target.n_sets} sets/{target.n_sessions} sessions",
            )
        )

    note = {
        "status": "available" if ids else "unavailable",
        "targets": len(ids),
        "calibration_ids": ids,
        "withheld": sorted(set(withheld)),
        "upgrade": "mean velocity only; per-rep velocity loss deferred (docs/VBT-CALIBRATION.md)",
    }
    return tuple(out), tuple(ids), note


def _persist_calibration(conn, target, for_date: str) -> str:
    """Store the target (append-only) and return a stable id for the prescription to cite."""
    raw = (
        f"{target.exercise_id}|{target.rep_count}|{target.velocity_median}|"
        f"{target.velocity_low}|{target.velocity_high}|{target.n_sets}|"
        f"{target.n_sessions}|{target.method_version}|{for_date}"
    )
    calibration_id = "vbt-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    existing = conn.execute(
        "SELECT 1 FROM vbt_calibration WHERE calibration_id = ?", (calibration_id,)
    ).fetchone()
    if existing is None:
        repositories.append_calibration(
            conn,
            calibration_id=calibration_id,
            exercise_id=target.exercise_id,
            vbt_family=None,
            scope=target.scope if target.scope in ("lift", "family") else "global_prior",
            rep_count=target.rep_count,
            rir_band=target.rir_band,
            velocity_median=target.velocity_median,
            velocity_low=target.velocity_low,
            velocity_high=target.velocity_high,
            n_sets=target.n_sets,
            n_sessions=target.n_sessions,
            method_version=target.method_version,
            params=target.params,
            window_end=for_date,
        )
    return calibration_id


def _apply_undulation(
    conn,
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    template: templates.DayTemplate,
    thresholds: config_mod.Thresholds,
    for_date: str,
    decisions: Mapping[str, Any],
    undulation: undulation_mod.Undulation,
    *,
    calibration_factors: Mapping[str, object] | None = None,
) -> tuple[tuple[PrescriptionItem, ...], tuple[str, ...], Mapping[str, str] | None]:
    """Apply the week's rep schemes, rebuilding each item's load through the solver.

    A scheme is only applied where it is allowed: `maximal` is skipped for hinges, which fall
    back to the strength scheme. Loads are rebuilt before the fatigue and back-flare modifiers,
    so those still act on the final session.
    """
    week = int(context.block_week_index or 0)
    plan = undulation.for_week(week)
    if not plan:
        return items, (), None

    schemes = schemes_mod.Schemes.load()
    cycle_week = ((week - 1) % undulation.cycle_weeks) + 1
    # Power is quality work: a longer or shorter rep scheme would change its intent, so the
    # undulating accessory layer leaves it alone (DEC-POWER-01).
    power_ids = {
        exercise for slot in template.slots if slot.power for exercise in slot.exercises
    }
    out: list[PrescriptionItem] = []
    for item in items:
        if item.exercise_id in power_ids:
            out.append(item)
            continue
        layer = "main" if item.essential else "accessory"
        name = plan.get(layer)
        if not name:
            out.append(item)
            continue
        if not schemes.applicable(name, exercise_id=item.exercise_id,
                                  essential=item.essential):
            name = "strength" if item.essential else "accessory"
        scheme = schemes.get(name)
        if (item.reps_low, item.reps_high) == (scheme.reps_low, scheme.reps_high):
            out.append(item)
            continue
        slot = templates.Slot(
            id=f"dup:{item.exercise_id}",
            sets=item.sets,
            reps_low=scheme.reps_low,
            reps_high=scheme.reps_high,
            rir_low=item.rir_target,
            rir_high=item.rir_target,
            rest_s=item.rest_s,
            essential=item.essential,
            load_source="e1rm" if item.essential else "double_progression",
            exercise=item.exercise_id,
        )
        rebuilt, _ = build_item(
            conn, context, slot, item.order_index, thresholds, for_date, decisions, template,
            calibration_factors=calibration_factors,
        )
        out.append(rebuilt)

    detail = ", ".join(f"{layer} {name}" for layer, name in plan.items())
    return tuple(out), (f"DUP week {cycle_week}: {detail}",), dict(plan)


def _apply_back_flare(
    items: tuple[PrescriptionItem, ...],
    context: RuleContext,
    thresholds: config_mod.Thresholds,
) -> tuple[PrescriptionItem, ...]:
    """MOD-BACK-001 as a transformation: erector dose down, main-lift effort held back."""
    extra: tuple[str, ...] = ("MOD-BACK-001",)
    if context.symptom_on:
        extra += (f"symptom:{context.symptom_on}",)

    added = float(thresholds.back_flare_erector_added_kg)
    out: list[PrescriptionItem] = []
    for item in items:
        refs = item.rationale_refs + extra
        if context.entity(item.exercise_id).get("direct_erector", False):
            out.append(
                replace(
                    item,
                    sets=thresholds.back_flare_erector_sets,
                    load_kg=added,
                    load_basis="bodyweight_total" if added == 0 else "external",
                    rationale_refs=refs,
                    unknown_load_reason=None,
                )
            )
        elif item.essential:
            out.append(
                replace(item, rir_target=thresholds.back_flare_main_rir, rationale_refs=refs)
            )
        else:
            out.append(replace(item, rationale_refs=refs))
    return tuple(out)


def build_item(
    conn,
    context: RuleContext,
    slot: templates.Slot,
    index: int,
    thresholds: config_mod.Thresholds,
    for_date: str,
    decisions: Mapping[str, Any],
    template: templates.DayTemplate,
    *,
    calibration_factors: Mapping[str, object] | None = None,
    exercise_id: str | None = None,
) -> tuple[PrescriptionItem, tuple[str, ...]]:
    """Build one item from a slot, solving its load from stored history.

    Kept separate from the loop so a proposal can rebuild a single item after a substitution
    without re-deriving loads itself -- the proposal path must use the same solver as the
    deterministic path, or the two would drift.
    """
    warnings: list[str] = []
    if exercise_id is None:
        exercise_id, chosen_variant = _choose_exercise(slot, context)
        if chosen_variant:
            warnings.append(f"{slot.id}: chose {exercise_id} from {list(slot.variants)}")
    else:
        # Selection already validated the candidate against constraints/suitability.
        chosen_variant = False

    increment = thresholds.increment_for(exercise_id)
    props = context.entity(exercise_id)
    bodyweight = bool(props.get("bodyweight_type", False))
    # A power jump is never load-progressed, even if a proposal rebuilds the item through a
    # generic slot. The pattern check is the backstop; the template also uses bodyweight.
    power_exercise = bool(slot.power) or str(props.get("pattern")) == "power_jump"
    load: float | None
    refs: tuple[str, ...] = ()
    unknown_reason: str | None = None

    if calibration_factors is None:
        calibration_factors = e1rm_calibration_feature.factors(
            conn, for_date, window_days=thresholds.e1rm_window_days
        )
    if power_exercise:
        if bodyweight:
            load = 0.0
        else:
            load = None
            unknown_reason = f"{exercise_id}: power work is bodyweight/implement-only"
    elif slot.load_source == "bodyweight":
        if bodyweight:
            load = 0.0
            if not slot.power:
                warnings.append(
                    f"{exercise_id}: bodyweight; progress by reps or sets, not load"
                )
        else:
            load = None
            unknown_reason = (
                f"{exercise_id}: bodyweight load_source on a non-bodyweight exercise"
            )
    elif slot.load_source == "e1rm":
        found = _latest_e1rm(conn, context, exercise_id, for_date,
                              thresholds.e1rm_window_days, calibration_factors)
        if found is None:
            # No recent e1RM is common after a layoff. Reusing the last working load is
            # safer than refusing to prescribe: the load is a real, previously managed
            # weight, and the warning makes the staleness visible.
            last_set = _last_working_set(context, exercise_id)
            if last_set is None:
                load = None
                refs = ()
                unknown_reason = (
                    f"no usable e1RM for {exercise_id} in the last "
                    f"{thresholds.e1rm_window_days} days, and no earlier working load"
                )
            else:
                prior_load, ref = last_set
                load = loads.round_down(prior_load, increment)
                refs = ("PRG-RIR-001", ref)
                warnings.append(
                    f"{exercise_id}: no e1RM in the last "
                    f"{thresholds.e1rm_window_days} days; reused the last working load"
                )
        else:
            e1rm_kg, ref, calibrated, decayed = found
            load = loads.solve_load(e1rm_kg, slot.reps_low, slot.rir_low, increment)
            refs = ("PRG-RIR-001", ref)
            if calibrated:
                refs += ("MOD-E1RM-001",)
                warnings.append(
                    f"{exercise_id}: e1RM calibrated from measured tests "
                    f"(x{float(calibration_factors[exercise_id].correction_factor):.3f})"
                )
            if decayed:
                refs += ("MOD-E1RM-DECAY-001",)
                warnings.append(
                    f"{exercise_id}: e1RM is old; decayed for the load basis "
                    f"({e1rm_kg:g} kg effective)"
                )
            if ref.startswith("e1rm_override:"):
                warnings.append(
                    f"{exercise_id}: using a manual e1RM override ({e1rm_kg:g} kg)"
                )
    else:
        found = _last_working_set(context, exercise_id)
        if found is None and bodyweight:
            # Bodyweight work needs no history to start: week 1 of an erector ramp is
            # bodyweight by definition, so prescribing 0 is correct, not a guess.
            load = 0.0
            refs = ()
            warnings.append(f"{exercise_id}: no history; starting at bodyweight")
        elif found is None:
            load = None
            refs = ()
            unknown_reason = f"no working history for {exercise_id}"
        else:
            prior_load, ref = found
            decision = decisions.get(exercise_id, {}).get("decision", "hold_load")
            if bodyweight and prior_load == 0:
                # Unweighted bodyweight work: adding 0.5 kg to nothing is not a
                # progression. Bodyweight progression acts on reps or sets instead
                # (DEC-LOAD-02), so the load stays 0 and the warning says why.
                load = 0.0
                warnings.append(
                    f"{exercise_id}: bodyweight, progress by reps or sets, not load"
                )
            else:
                load = prior_load + increment if decision == "add_increment" else prior_load
                load = loads.round_down(load, increment)
            refs = ("PRG-DP-001", ref)

    if power_exercise:
        # A power set is not progressed by load or scored by RIR; the rationale is intent and
        # quality, so no rule citation is attached and the warning says what "RIR" means here.
        refs = ()
        warnings.append(
            f"{exercise_id}: power work — maximal intent, full recovery, stop when height or "
            f"quality drops"
        )

    item = PrescriptionItem(
        order_index=index,
        exercise_id=exercise_id,
        sets=slot.sets,
        reps_low=slot.reps_low,
        reps_high=slot.reps_high,
        load_kg=load,
        load_basis=(
            "bodyweight_total"
            if bodyweight and (load in (None, 0.0))
            else "external"
        ),
        rounding_increment_kg=increment,
        rir_target=slot.rir_low,
        rest_s=slot.rest_s,
        essential=slot.essential,
        rationale_refs=refs,
        time_cap_s=template.time_cap_s if slot.essential else None,
        unknown_load_reason=unknown_reason,
    )
    return item, tuple(warnings)


def _choose_exercise(slot: templates.Slot, context: RuleContext) -> tuple[str, bool]:
    """Pick one exercise for a slot; variants resolve to whichever was trained most recently."""
    if len(slot.exercises) == 1:
        return slot.exercises[0], False

    latest: tuple[pd.Timestamp, str] | None = None
    for exercise_id in slot.exercises:
        history = context.sets[context.sets["exercise_id"] == exercise_id]
        if history.empty:
            continue
        when = history["date"].max()
        if latest is None or when > latest[0]:
            latest = (when, exercise_id)
    if latest is None:
        # Nothing trained yet: take the first variant in config order so the choice is
        # reproducible rather than dependent on dict ordering.
        return slot.exercises[0], True
    return latest[1], True


def _e1rm_decay(context: RuleContext, age_days: float) -> float:
    """Age decay, unless the continuity modifier already handles a long gap.

    A gap of 28+ days triggers MOD-GAP-001's load reduction; decaying the e1RM as well would
    double-count the same absence. A stale lift while training continues (small gap) still
    decays normally.
    """
    if context.gap_days is not None and context.gap_days >= 28:
        return 1.0
    return e1rm_decay_feature.factor(age_days)


def _latest_e1rm(
    conn, context: RuleContext, exercise_id: str, for_date: str, window_days: int,
    calibration_factors: Mapping[str, object] | None = None,
) -> tuple[float, str, bool, bool] | None:
    """The e1RM to prescribe from, with a citable reference.

    A manual override in force on the date outranks the computed estimate: the athlete may
    know a tested value the formula cannot see. Otherwise the best usable e1RM in the window
    ending at `for_date` is used. The window is measured from the prescription date, not from
    the last session, so a returning athlete is not prescribed from a pre-break peak.
    """
    override = queries.e1rm_override(conn, exercise_id, for_date)
    if override is not None:
        age = (pd.Timestamp(for_date) - pd.Timestamp(override["effective_from"])).days
        decay = _e1rm_decay(context, age)
        return (float(override["e1rm_kg"]) * decay,
                f"e1rm_override:{override['override_id']}", False, decay != 1.0)

    if context.sets.empty or "e1rm_kg" not in context.sets:
        return None
    frame = context.sets
    cutoff = pd.Timestamp(for_date) - pd.Timedelta(days=window_days)
    usable = frame[
        (frame["exercise_id"].isin(exercises_mod.history_equivalents(exercise_id)))
        & frame["e1rm_kg"].notna()
        & (frame["date"] >= cutoff)
    ]
    if usable.empty:
        return None
    # Pick the best *current* estimate: the same e1RM from an older set decays more, and a
    # tie should prefer the more recent observation. Selecting by raw e1RM first made the
    # oldest of several identical sets the winner.
    usable = usable.assign(
        _age_days=(pd.Timestamp(for_date) - usable["date"]).dt.days,
    )
    usable["_decay"] = [_e1rm_decay(context, age) for age in usable["_age_days"]]
    usable["_effective"] = usable["e1rm_kg"] * usable["_decay"]
    row = usable.sort_values(
        ["_effective", "date", "set_id"], ascending=[False, False, False]
    ).iloc[0]
    calibration = (calibration_factors or {}).get(exercise_id)
    factor = 1.0 if calibration is None else float(calibration.correction_factor)
    decay = float(row["_decay"])
    return (float(row["e1rm_kg"]) * factor * decay,
            f"set:{row['session_id']}/{int(row['set_id'])}",
            factor != 1.0,
            decay != 1.0)


def _last_working_set(
    context: RuleContext, exercise_id: str
) -> tuple[float, str] | None:
    """The most recent working load, for double progression."""
    if context.sets.empty:
        return None
    usable = context.sets[
        context.sets["exercise_id"].isin(exercises_mod.history_equivalents(exercise_id))
        & context.sets["is_working_set"]
        & context.sets["load_kg"].notna()
    ]
    if usable.empty:
        return None
    row = usable.sort_values(["date", "set_id"]).iloc[-1]
    return float(row["load_kg"]), f"set:{row['session_id']}/{int(row['set_id'])}"


def validate_prescription(
    items: tuple[PrescriptionItem, ...],
    context: RuleContext,
    document,
    session_day: str,
    for_date: str,
) -> list[str]:
    """V0-SCOPE §4.4: a prescription must be executable before it is shown."""
    issues: list[str] = []

    for item in items:
        if item.load_kg is None:
            issues.append(f"NO_LOAD:{item.exercise_id}:{item.unknown_load_reason}")
            continue
        if item.load_basis == "bodyweight_total" and item.load_kg == 0:
            continue  # unweighted bodyweight: 0 is the correct load, not a missing one
        if item.load_kg <= 0:
            issues.append(f"LOAD_NOT_POSITIVE:{item.exercise_id}:{item.load_kg}")
        if not loads.is_multiple_of(item.load_kg, item.rounding_increment_kg):
            issues.append(
                f"LOAD_NOT_EXECUTABLE:{item.exercise_id}:{item.load_kg} "
                f"is not a multiple of {item.rounding_increment_kg}"
            )
        if context.entity(item.exercise_id).get("direct_erector", False) and session_day == "B":
            # PRG-SCHED-001: direct erector work never belongs on the hinge day.
            issues.append(f"ERECTOR_ON_HINGE_DAY:{item.exercise_id}")

        if context.entity(item.exercise_id).get("primary_compound", False):
            # PRG-RIR-001: the effort window is a rule, not a suggestion. This check was
            # missing until proposals could name a menu option, which is exactly when a
            # target RIR stopped being guaranteed by the template.
            params = document.rule("PRG-RIR-001").params
            window = (params.get("per_exercise_rir") or {}).get(
                item.exercise_id, params.get("default_rir")
            )
            if window:
                low, high = int(window["min"]), int(window["max"])
                if not low <= item.rir_target <= high:
                    issues.append(
                        f"RIR_OUTSIDE_WINDOW:{item.exercise_id}:{item.rir_target} "
                        f"not in {low}-{high}"
                    )

    rule = document.rule("PRG-SPINE-001")
    proposed = [(for_date, item.exercise_id, for_date) for item in items]
    costs = registry.weekly_spinal_costs(rule, context, proposed)
    week = registry.iso_week(for_date)
    cost = float(costs.get(week, {}).get("cost", 0.0))
    cap = float(rule.params.get("cap", 3))
    if cost > cap:
        issues.append(f"SPINAL_CAP:{week}:cost {cost:g} exceeds cap {cap:g}")

    return issues


def validate_references(
    prescription: Prescription,
    context: RuleContext,
    conn,
    document=None,
) -> list[str]:
    """Every rationale reference must resolve (V0-SCOPE §4.8).

    Rule ids must exist in the document; data references must name a stored set, or a
    readiness row when the fatigue modifier fired. A citation that resolves to nothing is a
    hallucination even when Python produced it.
    """
    document = document or load_document()
    known = set(document.rule_ids) | {
        str(modifier.get("id")) for modifier in document.modifiers
    }
    problems: list[str] = []
    for item in prescription.items:
        for ref in item.rationale_refs:
            if RULE_REF_RE.match(ref):
                if ref not in known:
                    problems.append(f"{item.exercise_id}: unknown rule {ref}")
            elif ref.startswith("readiness:"):
                if queries.readiness_day(conn, ref.split(":", 1)[1]) is None:
                    problems.append(f"{item.exercise_id}: no readiness row for {ref}")
            elif ref.startswith("readiness_score:"):
                try:
                    float(ref.split(":", 1)[1])
                except ValueError:
                    problems.append(f"{item.exercise_id}: malformed reference {ref}")
            elif ref.startswith("e1rm_override:"):
                try:
                    override_id = int(ref.split(":", 1)[1])
                except ValueError:
                    problems.append(f"{item.exercise_id}: malformed reference {ref}")
                else:
                    if queries.e1rm_override_by_id(conn, override_id) is None:
                        problems.append(f"{item.exercise_id}: no e1RM override for {ref}")
            elif not policy_mod.resolve_reference(context, ref):
                problems.append(f"{item.exercise_id}: unresolvable reference {ref}")
    return problems
