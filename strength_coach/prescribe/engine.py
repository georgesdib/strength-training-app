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

from strength_coach import settings_profile
from strength_coach.features import injury_signal as injury_signal_mod
from strength_coach.features import readiness as readiness_mod
from strength_coach.features import readiness_score
from strength_coach.prescribe import config as config_mod
from strength_coach.prescribe import constraints as constraints_mod
from strength_coach.features import e1rm_calibration as e1rm_calibration_feature
from strength_coach.features import continuity_calibration
from strength_coach.features import high_intensity_exposure as exposure_feature
from strength_coach.features import test_cadence, volume as volume_feature
from strength_coach.prescribe import deload as deload_mod
from strength_coach.prescribe import minimum_session as minimum_session_mod
from strength_coach.prescribe import technique_throttle as technique_throttle_mod
from strength_coach.prescribe import warmup
from strength_coach.features import e1rm_decay as e1rm_decay_feature
from strength_coach.features import lift_readiness as lift_readiness_feature
from strength_coach.features import recent_stress as recent_stress_feature
from strength_coach.features import vbt_calibration
from strength_coach.prescribe import schemes as schemes_mod
from strength_coach.prescribe import undulation as undulation_mod
from strength_coach.prescribe import fallback, loads, schedule, templates
from strength_coach.prescribe import selection as selection_mod
from strength_coach.prescribe import volume_budget as volume_budget_mod
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
    session_type: str = "hinge",
    document=None,
    thresholds: config_mod.Thresholds | None = None,
    template: templates.SessionTemplate | None = None,
    readiness_config: readiness_mod.ReadinessConfig | None = None,
    undulation: undulation_mod.Undulation | None = None,
    history: History | None = None,
    vbt: vbt_calibration.CalibrationResult | None = None,
    apply_selection: bool = False,
    selection_chooser: Callable | None = None,
    selection_confirmed: bool = False,
    minimum_session: bool = False,
    minimum_target_minutes: int | None = None,
    minimum_include_main: bool = False,
    technique_throttle: bool = False,
    technique_throttle_pattern: str | None = None,
    deload_decision: Any | None = None,
    drop_confirmed: bool = False,
) -> Prescription:
    """Generate the deterministic session for `for_date`.

    `history` and `vbt` are optional precomputed inputs for callers that build more than one
    prescription from the same past (the programme forecast): the enriched frame and the VBT
    calibration do not change with the forecast date, so recomputing them per entry is waste.
    """
    resolved = settings_profile.feature_settings(conn, for_date)
    document = document or load_document()
    thresholds = thresholds or resolved.thresholds
    budget_config = volume_budget_mod.BudgetConfig.load(conn=conn, on_date=for_date)
    requested_session_type = session_type
    drop_plan = volume_budget_mod.plan_drop(
        conn, for_date, session_type, config=budget_config, confirmed=drop_confirmed,
    )
    drop_applied = bool(drop_plan.get("applied"))
    if drop_applied:
        session_type = str(drop_plan["session_type"])
        template = drop_plan["template"]
    elif template is None:
        template = templates.SessionTemplate.load(session_type)
    readiness_config = readiness_config or resolved.readiness
    undulation = undulation or resolved.undulation

    context = RuleContext.from_store(
        conn, end=for_date, rep_ranges=templates.all_rep_ranges(), history=history
    )
    policy_result = evaluate(document, context)
    decisions = policy_result.verdict("PRG-DP-001").details.get("decisions", {})
    exposure_status = exposure_feature.status(conn, for_date)

    items: list[PrescriptionItem] = []
    warnings: list[str] = []
    if drop_applied:
        if session_type == "technique":
            warnings.append(
                "MOD-VOL-005: week is at/above the high tolerance band; technique session"
            )
        else:
            warnings.append(
                "MOD-VOL-005: volume fill; "
                f"{drop_plan['note']['original_session_type']} main/accessories removed"
            )
    elif drop_plan.get("status") == "competition_confirmation":
        warnings.append(f"MOD-VOL-005: drop held: {drop_plan.get('note')}")
    if exposure_status.status != "clear":
        warnings.append(
            f"high-intensity exposure: {exposure_status.reason}"
            + (f"; next maximal exposure allowed on {exposure_status.next_maximal_on}"
               if exposure_status.next_maximal_on else "")
        )
    selection_rows: dict[str, selection_mod.SlotSelection] = {}
    selection_notes: list[dict] = []
    if apply_selection:
        selected = selection_mod.select(
            conn, context, for_date, session_type,
            chooser=selection_chooser,
        )
        selection_rows = {row.slot_id: row for row in selected}
        selection_notes = [row.as_dict() for row in selected]

    e1rm_factors = e1rm_calibration_feature.factors(
        conn, for_date, window_days=thresholds.e1rm_window_days,
        config=resolved.calibration, decay_config=resolved.decay,
    )
    for index, slot in enumerate(template.slots):
        selected_row = selection_rows.get(slot.id)
        selected_exercise = None
        if selected_row is not None and selected_row.changed:
            if selected_row.comparison_class == "C":
                blocked = "different lift/load basis; never automatic"
            elif selected_row.comparison_class == "B" and not selection_confirmed:
                blocked = "near-comparable substitution requires confirmation"
            else:
                blocked = None
            if blocked is None:
                selected_exercise = selected_row.suggested
            else:
                warnings.append(
                    f"selection skipped for {slot.id}: {selected_row.suggested} "
                    f"({blocked})"
                )
                note = next(
                    (row for row in selection_notes if row["slot_id"] == slot.id), None
                )
                if note is not None:
                    note["blocked_reason"] = blocked
        item, slot_warnings = build_item(
            conn, context, slot, index, thresholds, for_date, decisions, template,
            calibration_factors=e1rm_factors, exercise_id=selected_exercise,
        )
        if selected_exercise is not None:
            item = replace(
                item,
                rationale_refs=item.rationale_refs + ("MOD-SELECT-001",),
            )
            note = next(
                (row for row in selection_notes if row["slot_id"] == slot.id), None
            )
            if note is not None:
                note["applied"] = True
            warnings.append(
                f"MOD-SELECT-001: {slot.id} selected {selected_exercise} "
                f"({selected_row.source}, {selected_row.comparison_class}); "
                f"load re-solved from its own history"
            )
        items.append(item)
        warnings.extend(slot_warnings)
    dup_plan = None
    if undulation.enabled and context.block_week_index:
        items, dup_warnings, dup_plan = _apply_undulation(
            conn, context, tuple(items), template, thresholds, for_date, decisions, undulation,
            maximal_hinge_allowed=resolved.maximal_hinge_allowed,
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
        # An explicit override is not a score, but it is applied; saying otherwise would be
        # false and would hide the only readiness statement for the day (DEC-READINESS-17).
        tail = (
            "manual override applied; no numeric score"
            if assessment.overrides else "fatigue modifier not applied"
        )
        warnings.append(f"readiness unknown for {for_date}; {tail}")
    elif assessment.status == "insufficient":
        tail = (
            "manual override applied; no numeric score"
            if assessment.overrides else "score not applied"
        )
        warnings.append(
            f"readiness insufficient for {for_date}: {assessment.basis}; {tail}"
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
    items, gap_level, gap_warnings, load_factors = _apply_continuity(
        context, tuple(items), thresholds, prior_factors=readiness_factors,
        calibration=continuity_cal,
    )
    if gap_level == "fatigue_reduced":
        fallback_level = "fatigue_reduced"
    warnings.extend(gap_warnings)

    # The volume budget is off by default and enabled only in the athlete profile. It moves
    # non-essential sets; a safety cut is skipped, not re-added (MOD-VOL-003). In drop mode the
    # volume_fill template is already target-built, so 9b is not applied again.
    if drop_applied:
        budget_note = {"enabled": True, "status": "drop", "drop": drop_plan}
        compensation_note = {"status": "disabled", "reason": "drop mode"}
    else:
        items, budget_warnings, budget_note = volume_budget_mod.apply(
            tuple(items), conn=conn, context=context, for_date=for_date,
            session_type=requested_session_type, config=budget_config,
        )
        warnings.extend(budget_warnings)
        items, compensation_warnings, compensation_note = _apply_compensation(
            conn, context, tuple(items), for_date=for_date,
            session_type=requested_session_type,
            template=template, thresholds=thresholds, decisions=decisions,
            budget_note=budget_note, config=budget_config,
            calibration_factors=e1rm_factors,
        )
        warnings.extend(compensation_warnings)

    items, calibration_ids, vbt_note = _attach_vbt_targets(
        conn, context, tuple(items), for_date, fallback_level, calibration=vbt_cal
    )

    items, under_warnings, under_note = _apply_under_mev(
        context, tuple(items), for_date, config=resolved.volume
    )
    warnings.extend(under_warnings)
    items, volume_warnings, volume_note = _apply_volume_cap(
        context, tuple(items), for_date, config=resolved.volume
    )
    warnings.extend(volume_warnings)
    # Last set change before validation: the spinal cap is a veto on the week, and the
    # standard cycle sits exactly on it, so a non-essential exposure that pushes the week
    # over is removed rather than turned into a dead prescription (MOD-SPINE-001).
    items, spine_warnings, spine_note = _apply_spinal_trim(
        context, tuple(items), for_date, document
    )
    warnings.extend(spine_warnings)

    # Deload runs before the minimum session and before final validation. Its load factor is
    # compared with the cumulative readiness/continuity factor, never multiplied on top.
    deload_note = None
    if deload_decision is not None:
        primary = {
            item.exercise_id for item in items
            if context.entity(item.exercise_id).get("primary_compound", False)
        }
        items, deload_warning, deload_note, deload_level = deload_mod.apply_items(
            tuple(items), deload_decision, config=resolved.deload,
            prior_load_factors=load_factors,
            primary_compounds=primary,
        )
        if deload_warning:
            warnings.append(deload_warning)
        if deload_note is not None:
            fallback_level = deload_level

    # MOD-TECH-001 is a user request, so it runs after the automatic modifiers and compares
    # with their cumulative load factor instead of multiplying on top. It must precede the
    # ramp attach, which derives warm-up loads from the final top-set load.
    technique_note = None
    if technique_throttle:
        throttle_cfg = technique_throttle_mod.TechniqueThrottleConfig.load()
        patterns = {
            item.exercise_id: str(context.entity(item.exercise_id).get("pattern") or "")
            for item in items
        }
        throttle = technique_throttle_mod.apply(
            tuple(items), patterns,
            pattern=technique_throttle_pattern, config=throttle_cfg,
        )
        if throttle["applied"]:
            items = list(throttle["items"])
            warnings.append(
                f"MOD-TECH-001: user-declared technique throttle; {throttle['reason']}; "
                "this session only"
            )
        else:
            warnings.append(f"MOD-TECH-001 not applied: {throttle['reason']}")
        technique_note = {
            key: value for key, value in throttle.items() if key != "items"
        }

    # Attach the ramp before estimating a minimum session so its warm-up cost is not hidden.
    items = warmup.attach(tuple(items))

    # Constraint evaluation is needed before the optional minimum-session tier: a hard veto
    # must refuse volume reduction rather than hide it behind a non-executable prescription.
    constraint_report = constraints_mod.evaluate(
        conn, [item.exercise_id for item in items]
    )
    minimum_note = None
    if minimum_session:
        minimum_cfg = minimum_session_mod.MinimumSessionConfig.load()
        target = minimum_target_minutes or minimum_cfg.default_target_minutes
        pre_issues = validate_prescription(
            tuple(items), context, document, session_type, for_date
        )
        for exercise_id, reason in constraint_report.vetoes:
            pre_issues.append(f"CONSTRAINT_VETO:{exercise_id}:{reason}")
        if pre_issues:
            minimum_note = {
                "requested": True, "applied": False, "status": "unavailable",
                "reason": "prescription is not executable: " + "; ".join(pre_issues),
                "target_minutes": target,
                "include_main": minimum_include_main,
            }
            warnings.append(f"MOD-MIN-001 not applied: {minimum_note['reason']}")
        else:
            result = minimum_session_mod.apply(
                tuple(items), target_minutes=target,
                include_main=minimum_include_main, config=minimum_cfg,
            )
            if result["applied"]:
                items = list(result["items"])
                warnings.append(
                    f"MOD-MIN-001: {result['status']}; {result['reason']}; "
                    "load and RIR unchanged"
                )
            else:
                warnings.append(
                    f"MOD-MIN-001 not applied: {result['status']}; {result['reason']}"
                )
            minimum_note = {
                key: value for key, value in result.items() if key != "items"
            }

    load_stack = _load_stack(items)
    if load_stack:
        worst = load_stack[0]
        warnings.append(
            f"combined load reduction {worst['reduction_pct']:.1f}% on "
            f"{worst['exercise_id']} ({', '.join(worst['components'])}); "
            "the 20% cap covers readiness+continuity only, not e1RM decay or deload"
        )

    # Injury signals are context, never policy: a flaring region adds a warning naming the
    # lifts that load it, but never vetoes or edits a load (DEC-INJURY-01).
    warnings.extend(_injury_warnings(injury, tuple(items)))

    # Stored athlete state is applied deterministically: a hard constraint vetoes, a
    # suitability rating is surfaced. Unrecorded state is reported, never read as permission.
    if not constraint_report.recorded:
        warnings.append(
            "athlete state not recorded: constraints were not evaluated (they are unknown, "
            "not absent)"
        )
    warnings.extend(constraint_report.warnings)

    issues = validate_prescription(tuple(items), context, document, session_type, for_date)
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

    # The profile ceiling is informational/constraining metadata, not a silent set cut.
    # Planned target stays 80 min; the athlete's lower value can tighten it; 90 is the hard cap.
    profile = queries.athlete_profile(conn) or {}
    configured = profile.get("max_session_minutes")
    hard_minutes = 90
    planned_minutes = 80
    if configured is not None:
        planned_minutes = min(planned_minutes, hard_minutes, max(1, int(configured)))
    time_cap_s = planned_minutes * 60
    estimated_minutes = minimum_session_mod.estimate_minutes(tuple(items))
    if estimated_minutes > planned_minutes:
        warnings.append(
            f"session time: estimated {estimated_minutes:g} min exceeds the planned "
            f"{planned_minutes} min ceiling; use the minimum-session option or shorten it"
        )
    session_time = {
        "planned_minutes": planned_minutes,
        "hard_ceiling_minutes": hard_minutes,
        "estimated_minutes": estimated_minutes,
        "over_planned": estimated_minutes > planned_minutes,
        "configured_max_minutes": configured,
    }

    spine_rule = document.rule("PRG-SPINE-001")
    span_week, spine_cost, spine_cap, _spine_mix = _week_spinal(
        spine_rule, context, tuple(items), for_date
    )
    spinal_cap = {
        "week": span_week,
        "cost": spine_cost,
        "cap": spine_cap,
        "headroom": round(spine_cap - spine_cost, 2),
        "at_cap": abs(spine_cost - spine_cap) < 1e-9,
        "over_cap": spine_cost > spine_cap,
    }

    return Prescription(
        for_date=for_date,
        session_type=session_type,
        fallback_level=fallback_level,
        rule_document_version=document.version,
        items=tuple(items),
        time_cap_s=time_cap_s,
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
            "under_mev": under_note,
            "test_cadence": test_cadence.status(conn, for_date),
            "high_intensity_exposure": exposure_status.as_dict(),
            "volume_management": volume_note,
            "volume_budget": budget_note,
            "compensation": compensation_note,
            "drop": drop_plan.get("note") if drop_applied else None,
            "drop_confirmed": bool(drop_confirmed),
            "minimum_session": minimum_note,
            "technique_throttle": technique_note,
            "load_stack": load_stack,
        "session_time": session_time,
        "spinal_cap": spinal_cap,
        "spinal_trim": spine_note,
        **({"deload": deload_note} if deload_note is not None else {}),
            "selection": {
                "requested": bool(apply_selection),
                "applied": any(row.get("applied") for row in selection_notes),
                "llm_requested": bool(selection_chooser),
                "llm_used": any(row.get("source") == "llm" for row in selection_notes),
                "slots": selection_notes,
            },
        },
    )


# Lifts whose velocity signal is not trustworthy enough to prescribe from (docs/VBT-EVIDENCE.md).
VBT_UNRELIABLE = {"trap_bar_deadlift"}


def _apply_under_mev(
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    for_date: str,
    *,
    config: volume_feature.VolumeConfig | None = None,
) -> tuple[tuple[PrescriptionItem, ...], tuple[str, ...], dict]:
    """Add one accessory set to a pattern that has been below MEV for the configured window.

    Main lifts are intentionally excluded: this is a small accessory progression, not a
    licence to raise the primary strength dose. The MRV cap runs afterwards and can still
    remove a set if the result would exceed the ceiling.
    """
    cfg = config or volume_feature.VolumeConfig.load()
    if not cfg.under_mev_enabled or not cfg.landmarks:
        return items, (), {"applied": False}
    report = volume_feature.compute(
        context.sets, on_date=for_date,
        config=replace(cfg, window_weeks=cfg.under_mev_weeks),
    )
    # Status is judged on the landmark group, so the key to act on is the group, not the
    # raw pattern a row happens to name (DEC-VOLUME-05).
    under = {
        str(row.get("group") or volume_feature.volume_target_key(row["pattern"]))
        for row in report["patterns"] if row["status"] == "under"
    }
    if not under:
        return items, (), {"applied": False}
    out = list(items)
    changed: list[str] = []
    for key in sorted(under):
        indexes = [
            i for i, item in enumerate(out)
            if not item.essential
            and item.exercise_id
            and volume_feature.volume_target_key(
                context.entity(item.exercise_id).get("pattern") or ""
            ) == key
        ]
        if not indexes:
            continue
        index = indexes[0]
        item = out[index]
        add = min(cfg.under_mev_add_sets, cfg.under_mev_max_sets - item.sets)
        if add <= 0:
            continue
        out[index] = replace(
            item,
            sets=item.sets + add,
            rationale_refs=item.rationale_refs + ("MOD-VOL-002",),
        )
        changed.append(f"{key}:{item.exercise_id}+{add}")
    if not changed:
        return tuple(out), (), {"applied": False}
    warning = (
        "MOD-VOL-002: under-MEV accessory progression: " + ", ".join(changed)
    )
    return tuple(out), (warning,), {"applied": True, "changes": changed}


def _apply_volume_cap(
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    for_date: str,
    *,
    config: volume_feature.VolumeConfig | None = None,
) -> tuple[tuple[PrescriptionItem, ...], tuple[str, ...], dict]:
    """Trim non-essential sets when a pattern would exceed its configured MRV.

    The cap is deliberately one-directional: under-MEV is reported by the volume ledger but is
    never auto-filled. The MRV landmark is a coaching heuristic, not a measured individual
    threshold, so only accessories are trimmed; an essential item is never silently cut.
    """
    cfg = config or volume_feature.VolumeConfig.load()
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


def _week_spinal(
    rule,
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    for_date: str,
) -> tuple[str, float, float, dict[str, int]]:
    """Projected spinal cost for the session's ISO week, with its composition.

    The proposed session is costed by the same function that judges performed work
    (PRG-SPINE-001's exposure function), so the engine cannot disagree with the predicate
    about what the week costs. That is the whole reason MOD-SPINE-001 can exist: it trims
    against the rule's own arithmetic rather than a second implementation of it.
    """
    week = registry.iso_week(for_date)
    proposed = [(for_date, item.exercise_id, for_date) for item in items]
    entry = registry.weekly_spinal_costs(rule, context, proposed).get(week, {})
    mix = {str(ex): int(n) for ex, n in (entry.get("exercises") or {}).items()}
    return (
        week,
        float(entry.get("cost", 0.0)),
        float(rule.params.get("cap", 3)),
        mix,
    )


def _apply_spinal_trim(
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    for_date: str,
    document,
) -> tuple[tuple[PrescriptionItem, ...], tuple[str, ...], dict]:
    """Drop non-essential spinal work when the proposed session would exceed the weekly cap.

    PRG-SPINE-001 vetoes a *week*, and the standard cycle is designed to sit exactly on the
    cap (docs/W9-SPINAL-CAP.md), so one extra exposure is enough to make an otherwise good
    prescription non-executable. This is the same one-directional remedy the MRV cap uses:
    remove only non-essential high-fatigue spinal work, never an essential lift, and only
    while the removal actually reduces the week's cost. If the overage comes from essential
    work the veto stands and `validate_prescription` names the exposures that compose it.
    """
    rule = document.rule("PRG-SPINE-001")
    week, cost, cap, _mix = _week_spinal(rule, context, items, for_date)
    base = {"week": week, "cost": cost, "cap": cap}
    if cost <= cap:
        return items, (), {"applied": False, **base}

    excluded = {str(p) for p in (rule.params.get("excluded_patterns") or ())}
    costs = dict(rule.params.get("costs") or {})
    candidates: list[tuple[float, int, int]] = []
    for index, item in enumerate(items):
        if item.essential:
            continue
        entity = context.entity(item.exercise_id)
        if not entity.get("high_fatigue_spinal", False):
            continue
        if str(entity.get("pattern")) in excluded:
            continue
        exercise_cost = costs.get(item.exercise_id, entity.get("spinal_cost"))
        if exercise_cost is None:
            continue
        # Cheapest exposure first, then the item with the most sets: that saves the most
        # work per unit of spinal cost removed.
        candidates.append((float(exercise_cost), -int(item.sets), index))
    if not candidates:
        return items, (), {"applied": False, "reason": "no non-essential spinal work", **base}

    kept = list(range(len(items)))
    removed: list[str] = []
    current = cost
    for _cost, _neg_sets, index in sorted(candidates):
        if current <= cap:
            break
        trial = [i for i in kept if i != index]
        trial_cost = _week_spinal(rule, context, [items[i] for i in trial], for_date)[1]
        if trial_cost < current:
            kept = trial
            removed.append(items[index].exercise_id)
            current = trial_cost
    if not removed:
        # The overage is carried by essential lifts: removing an accessory cannot fix it, so
        # the veto must stand rather than silently delete unrelated work.
        return items, (), {
            "applied": False,
            "reason": "overage comes from essential lifts",
            **base,
        }
    # order_index is positional in models.Prescription.item(), so renumber after a removal.
    out = tuple(replace(items[i], order_index=position) for position, i in enumerate(kept))
    warning = (
        "MOD-SPINE-001: removed " + ", ".join(removed)
        + f" to keep the week within the spinal cap (cost {cost:g} -> {current:g}, cap {cap:g})"
    )
    return out, (warning,), {
        "applied": True,
        "week": week,
        "cap": cap,
        "removed": removed,
        "cost_before": cost,
        "cost_after": current,
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
    elif assessment.overrides:
        # No numeric score can be formed, but an explicit override is a dated athlete
        # statement and still supplies the factor for the categories it covers
        # (READINESS-SCORE §2.2a). The per-lift advisory is deliberately not computed: it
        # needs a base score and must not invent one on a partial day.
        for item in items:
            entity = (context.entities or {}).get(item.exercise_id, {})
            prepared[item.exercise_id] = readiness_score.effective(
                assessment, conn, item.exercise_id, entity, signal=injury
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
    override_used = False
    lift_reduced: list[str] = []
    sets_reduced: list[str] = []
    factors: dict[str, float] = {}
    for item in items:
        entity = (context.entities or {}).get(item.exercise_id, {})
        category = readiness_score.category_for(item.exercise_id, entity)
        scope = f"category:{category}" if category else None
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
        elif scope in assessment.overrides or "global" in assessment.overrides:
            # Only the covered categories take the override; an uncovered item keeps the
            # plain session, and no injury ceiling is applied through this path alone.
            score, factor, rir_bump, ceiling = prepared[item.exercise_id]
            if factor < 1.0:
                override_used = True
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
        if score is not None and assessment.score is not None:
            # No computed global score on a partial day: cite the override, not a score.
            refs += (f"readiness_score:{score:.3f}",)
        if ceiling < 1.0:
            capped = True
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
                load_factor=item.load_factor * factor,
            )
        )
    warnings: list[str] = []
    if reduced:
        pieces = []
        if scored and assessment.score is not None:
            pieces.append(f"readiness score {assessment.score:.2f}")
        if override_used and assessment.score is None:
            pieces.append("manual readiness override")
        if trigger:
            pieces.append(f"floor {trigger}")
        if capped:
            pieces.append("injury ceiling applied")
        if lift_reduced:
            pieces.append("per-lift readiness applied: " + ", ".join(lift_reduced))
        if sets_reduced:
            pieces.append("sets reduced: " + ", ".join(sets_reduced))
        warnings.append(
            "MOD-FAT-001: " + "; ".join(pieces) + "; session reduced"
        )
    return (tuple(out), ("fatigue_reduced" if reduced else "full"), tuple(warnings),
            factors, lift_scores)


def _load_stack(items: tuple[PrescriptionItem, ...]) -> list[dict]:
    """Items whose cumulative load factor is below 0.80, with the visible components."""
    labels = (
        ("MOD-E1RM-DECAY-001", "e1RM decay"),
        ("MOD-FAT-001", "readiness"),
        ("MOD-GAP-001", "continuity"),
        ("MOD-DELOAD-001", "deload"),
        ("MOD-TECH-001", "technique throttle"),
    )
    rows = []
    for item in items:
        if item.load_kg in (None, 0) or item.load_factor >= 0.80 - 1e-9:
            continue
        components = [
            label for ref, label in labels if ref in item.rationale_refs
        ] or ["load modifiers"]
        rows.append({
            "exercise_id": item.exercise_id,
            "factor": round(item.load_factor, 4),
            "reduction_pct": round((1.0 - item.load_factor) * 100, 1),
            "components": components,
        })
    return sorted(rows, key=lambda row: (row["factor"], row["exercise_id"]))


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
) -> tuple[tuple[PrescriptionItem, ...], str, tuple[str, ...], dict[str, float]]:
    """Return-to-training adjustment after a gap (DEC-CONTINUITY-01).

    The gap is detected from stored history; a declared break is optional. Short gaps add one
    RIR only. From 28 days the load is reduced and the same RIR bump applied; from 56 days the
    reduction is larger and the context has already stepped the ramp back one stage.
    Bodyweight work cannot shed load, so it loses a set instead.
    """
    band = _gap_band(context.gap_days, thresholds)
    if band is None:
        return items, "full", (), dict(prior_factors or {})

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
    factors_out = dict(prior_factors or {})
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
            factors_out[item.exercise_id] = prior * applied
            out.append(replace(
                item,
                load_kg=loads.round_down(
                    item.load_kg * applied, item.rounding_increment_kg
                ),
                rir_target=rir,
                rationale_refs=refs,
                load_factor=item.load_factor * applied,
            ))
        elif multiplier < 1.0 and item.load_basis == "bodyweight_total":
            # Bodyweight work cannot shed load, so it loses a set instead. The factor still
            # comes from the same readiness+continuity budget and must be bound here: a
            # bodyweight item can be the first one in the loop (box jump), and reading
            # `applied` from the branch above left it unbound (DEC-W3-02).
            prior = prior_factors.get(item.exercise_id, 1.0)
            applied = multiplier
            if prior * multiplier < 0.80:
                applied = min(1.0, 0.80 / prior)
                capped = capped or applied > multiplier
            factors_out[item.exercise_id] = prior * applied
            out.append(replace(
                item,
                sets=max(1, item.sets - 1),
                rir_target=rir,
                rationale_refs=refs,
                load_factor=item.load_factor * applied,
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
    return (tuple(out), "fatigue_reduced" if multiplier < 1 else "full", warnings,
            factors_out)


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
    template: templates.SessionTemplate,
    thresholds: config_mod.Thresholds,
    for_date: str,
    decisions: Mapping[str, Any],
    undulation: undulation_mod.Undulation,
    *,
    maximal_hinge_allowed: bool = False,
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
        if not schemes.applicable(
            name, exercise_id=item.exercise_id, essential=item.essential,
            maximal_hinge_allowed=maximal_hinge_allowed,
        ):
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


def _apply_compensation(
    conn,
    context,
    items,
    *,
    for_date: str,
    session_type: str,
    template,
    thresholds,
    decisions,
    budget_note,
    config,
    calibration_factors,
):
    """Apply the selected 9b compensation slot. Only a real, executable load is added."""
    if not budget_note.get("enabled") or not config.compensation_apply:
        return tuple(items), (), {
            "status": "disabled",
            "reason": "budget or compensation apply is off",
        }

    rows = [
        {
            "exercise_id": item.exercise_id,
            "sets": int(item.sets),
            "essential": bool(item.essential),
            "rest_s": int(item.rest_s or 0),
            "key": volume_budget_mod.pattern_key(item.exercise_id),
        }
        for item in items
    ]
    data = volume_budget_mod.report(
        conn, for_date, config=config, session_type=session_type,
    )
    projected = volume_budget_mod.projection(
        data["completed"],
        volume_budget_mod.pattern_sets(rows),
        [entry["sets"] for entry in data["future"]],
    )
    selection = volume_budget_mod.simulate_compensation(
        session_type=session_type,
        rows=rows,
        completed=data["completed"],
        effective=data["effective_targets"],
        projected=projected,
        config=config,
    )
    if selection.get("status") != "simulated" or not selection.get("selected"):
        return tuple(items), (), {
            "status": selection.get("status"),
            "selection": selection,
        }

    selected = dict(selection["selected"])
    exercise_id = str(selected["exercise_id"])
    if any(item.exercise_id == exercise_id for item in items):
        return tuple(items), (), {
            "status": "already_present",
            "selection": selection,
        }
    slot = templates.Slot(
        id=f"compensation:{exercise_id}",
        sets=int(selected["sets"]),
        reps_low=int(selected["reps_low"]),
        reps_high=int(selected["reps_high"]),
        rir_low=int(selected["rir_low"]),
        rir_high=int(selected["rir_high"]),
        rest_s=int(selected["rest_s"]),
        essential=False,
        load_source=str(selected["load_source"]),
        exercise=exercise_id,
    )
    item, slot_warnings = build_item(
        conn, context, slot, len(items), thresholds, for_date, decisions, template,
        calibration_factors=calibration_factors, exercise_id=exercise_id,
    )
    if item.load_kg is None or item.unknown_load_reason is not None:
        # Retry with the e1RM basis so a manual e1RM can satisfy 9b.
        if str(slot.load_source) != "e1rm":
            retry_slot = replace(slot, load_source="e1rm")
            retry, retry_warnings = build_item(
                conn, context, retry_slot, len(items), thresholds, for_date, decisions,
                template, calibration_factors=calibration_factors,
                exercise_id=exercise_id,
            )
            if retry.load_kg is not None and retry.unknown_load_reason is None:
                item = retry
                slot_warnings = tuple(slot_warnings) + tuple(retry_warnings)
        if item.load_kg is None or item.unknown_load_reason is not None:
            reason = item.unknown_load_reason or "no executable load"
            return tuple(items), (
                f"MOD-VOL-004: compensation {exercise_id} refused: {reason}; "
                "record an e1RM and rebuild",
            ), {
                "status": "refused",
                "selection": selection,
                "reason": reason,
            }
    item = replace(
        item, rationale_refs=item.rationale_refs + ("MOD-VOL-004",),
    )
    warning = (
        f"MOD-VOL-004: compensation {exercise_id} ({selected['group']}) "
        f"{selected['sets']} sets from {selection.get('source')}"
    )
    return tuple(items) + (item,), (warning,) + tuple(slot_warnings), {
        "status": "applied",
        "selection": selection,
        "selected": selected,
    }


def build_item(
    conn,
    context: RuleContext,
    slot: templates.Slot,
    index: int,
    thresholds: config_mod.Thresholds,
    for_date: str,
    decisions: Mapping[str, Any],
    template: templates.SessionTemplate,
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
    e1rm_source_sets: int | None = None
    decayed = False
    decay_factor = 1.0

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
                              thresholds.e1rm_window_days, calibration_factors,
                              source=thresholds.e1rm_source,
                              robust_window_days=thresholds.e1rm_robust_window_days)
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
            e1rm_kg, ref, calibrated, decayed, coverage, decay_factor = found
            e1rm_source_sets = coverage
            if coverage == 1:
                warnings.append(
                    f"{exercise_id}: e1RM source has one eligible set; confidence limited"
                )
            elif thresholds.e1rm_source == config_mod.E1RM_MEDIAN:
                # Say what the estimate summarised: a median is not a single stored set, and
                # the cited reference names only the most recent contributor.
                warnings.append(
                    f"{exercise_id}: e1RM is the median of {coverage} sets over up to "
                    f"{thresholds.e1rm_robust_window_days} days"
                )
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
            calibration_row = (calibration_factors or {}).get(exercise_id)
            advisory = _e1rm_plausibility(
                context, exercise_id, e1rm_kg, for_date, thresholds,
                calibration_factor=(
                    1.0 if calibration_row is None
                    else float(calibration_row.correction_factor)
                ),
            )
            if advisory:
                warnings.append(advisory)
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
        e1rm_source_sets=e1rm_source_sets,
        load_factor=decay_factor if decayed else 1.0,
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
    *,
    source: str = config_mod.E1RM_BEST_USABLE,
    robust_window_days: int = 28,
) -> tuple[float, str, bool, bool, int | None, float] | None:
    """The e1RM to prescribe from, with a citable reference.

    A manual override in force on the date outranks every computed estimate: the athlete may
    know a tested value the formula cannot see. Otherwise one of three selectors picks a
    value from the window ending at `for_date` (DEC-E1RM-SOURCE-01):

    * `best_usable` — the highest age-decayed estimate. The maximum of noisy observations is
      an optimistic estimator by construction, which is why it is no longer the default.
    * `median` — the median set-level estimate in the shorter robust window, falling back to
      `best_usable` when that window holds nothing. One great day cannot pin twelve weeks.
    * `most_recent` — the latest usable set.

    Every selector compares *age-decayed* values, so an old observation competes with a
    recent one on equal terms rather than by raw value alone. The window is measured from the
    prescription date, not the last session, so a returning athlete is not prescribed from a
    pre-break peak.
    """
    override = queries.e1rm_override(conn, exercise_id, for_date)
    if override is not None:
        age = (pd.Timestamp(for_date) - pd.Timestamp(override["effective_from"])).days
        decay = _e1rm_decay(context, age)
        return (float(override["e1rm_kg"]) * decay,
                f"e1rm_override:{override['override_id']}", False, decay != 1.0, None,
                decay)

    if context.sets.empty or "e1rm_kg" not in context.sets:
        return None
    frame = context.sets
    cutoff = pd.Timestamp(for_date) - pd.Timedelta(days=window_days)
    usable = frame[
        (frame["exercise_id"].isin(exercises_mod.history_equivalents(exercise_id)))
        & frame["e1rm_kg"].notna()
        & (frame["date"] >= cutoff)
    ]
    # Only working sets. A warm-up still carries a (much lower) formula e1RM; it can never win
    # a maximum, so `best_usable` was accidentally immune, but it drags a median down and can
    # be the "most recent" set. A lift with nothing but warm-ups has no usable e1RM, which is
    # the same answer the domain gives (DEC-RIR-01).
    if "is_working_set" in usable.columns:
        usable = usable[usable["is_working_set"].astype(bool)]
    if usable.empty:
        return None
    usable = usable.assign(
        _age_days=(pd.Timestamp(for_date) - usable["date"]).dt.days,
    )
    usable["_decay"] = [_e1rm_decay(context, age) for age in usable["_age_days"]]
    usable["_effective"] = usable["e1rm_kg"] * usable["_decay"]
    calibration = (calibration_factors or {}).get(exercise_id)
    factor = 1.0 if calibration is None else float(calibration.correction_factor)

    if source == config_mod.E1RM_MEDIAN:
        robust_start = pd.Timestamp(for_date) - pd.Timedelta(days=robust_window_days)
        pool = usable[usable["date"] >= robust_start]
        if pool.empty:
            # Nothing recent: the median falls back to the best usable estimate rather than
            # to "no e1RM", which would throw away real history on a returning athlete.
            pool = usable
        raw_median = float(pool["e1rm_kg"].median())
        effective_median = float(pool["_effective"].median())
        # The implied decay is the ratio of the two medians: it says how much age cost the
        # typical observation, without pretending any single set is the source.
        decay = effective_median / raw_median if raw_median > 0 else 1.0
        # Cite the most recent contributor: the reference proves the estimate came from
        # stored sets, and the warning says how many it summarised.
        row = pool.sort_values(["date", "set_id"]).iloc[-1]
        return (effective_median * factor,
                f"set:{row['session_id']}/{int(row['set_id'])}",
                factor != 1.0,
                decay < 1.0 - 1e-9,
                int(len(pool)),
                decay)

    if source == config_mod.E1RM_MOST_RECENT:
        row = usable.sort_values(["date", "set_id"]).iloc[-1]
        decay = float(row["_decay"])
        return (float(row["e1rm_kg"]) * factor * decay,
                f"set:{row['session_id']}/{int(row['set_id'])}",
                factor != 1.0,
                decay != 1.0,
                int(len(usable)),
                decay)

    # best_usable: the highest *current* estimate. The same e1RM from an older set decays
    # more, and a tie should prefer the more recent observation; selecting by raw e1RM first
    # made the oldest of several identical sets the winner.
    row = usable.sort_values(
        ["_effective", "date", "set_id"], ascending=[False, False, False]
    ).iloc[0]
    decay = float(row["_decay"])
    return (float(row["e1rm_kg"]) * factor * decay,
            f"set:{row['session_id']}/{int(row['set_id'])}",
            factor != 1.0,
            decay != 1.0,
            int(len(usable)),
            decay)


def _e1rm_plausibility(
    context: RuleContext,
    exercise_id: str,
    used_e1rm: float | None,
    for_date: str,
    thresholds,
    *,
    calibration_factor: float = 1.0,
) -> str | None:
    """An advisory when the load base sits far above this lift's recent typical estimate.

    Advisory, never policy: it changes no load, no set and no verdict — the precedent is the
    injury and recent-stress signals (DEC-INJURY-01, DEC-STRESS-01). It catches a *single-point*
    error in the load base: a measured override set far above history, a best-of-window estimate
    after a config flip, or a median that had to fall back to the older window. It is
    deliberately blind to a systematic bias in the whole e1RM distribution, because that cannot
    be seen in the distribution itself: MOD-E1RM-001 measures it against real tests.

    The reference is the median *working-set* e1RM over the recent window, decayed to the
    prescription date like the value it judges, so the comparison is like for like. Under the
    default `median` selector with ordinary history the two numbers are the same and this
    function is silent by construction (DEC-E1RM-PLAUS-01).
    """
    if not thresholds.plausibility_enabled or used_e1rm is None:
        return None
    frame = context.sets
    if frame.empty or "e1rm_kg" not in frame:
        return None
    cutoff = pd.Timestamp(for_date) - pd.Timedelta(
        days=thresholds.plausibility_reference_days
    )
    reference = frame[
        frame["exercise_id"].isin(exercises_mod.history_equivalents(exercise_id))
        & frame["e1rm_kg"].notna()
        & (frame["date"] >= cutoff)
    ]
    if "is_working_set" in reference.columns:
        reference = reference[reference["is_working_set"].astype(bool)]
    if len(reference) < thresholds.plausibility_min_sets:
        # Too little recent work to call anything implausible: say nothing rather than guess.
        return None
    ages = (pd.Timestamp(for_date) - reference["date"]).dt.days
    effective = [
        float(value) * _e1rm_decay(context, int(age))
        for value, age in zip(reference["e1rm_kg"], ages, strict=True)
    ]
    typical = float(pd.Series(effective).median())
    if typical <= 0:
        return None
    excess = float(used_e1rm) / typical - 1.0
    # A measured-test calibration is evidence, not an error, so the band widens by whatever it
    # justified: the advisory must not tell the athlete to distrust the one correction that is
    # checked against reality (MOD-E1RM-001). Its own warning already explains that load.
    allowed = thresholds.plausibility_max_above_reference + max(
        0.0, float(calibration_factor) - 1.0
    )
    if excess <= allowed:
        return None
    return (
        f"{exercise_id}: the e1RM behind this load ({float(used_e1rm):g} kg) is "
        f"{excess:.0%} above the recent median for this lift ({typical:g} kg from "
        f"{len(reference)} working sets in {thresholds.plausibility_reference_days} days); "
        "check the source before lifting — the load is unchanged (DEC-E1RM-PLAUS-01)"
    )


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
    session_type: str,
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
        if (
            context.entity(item.exercise_id).get("direct_erector", False)
            and session_type in {"hinge", "bench_hinge"}
        ):
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
    week, cost, cap, mix = _week_spinal(rule, context, items, for_date)
    if cost > cap:
        # Name the exposures: "move one of these" is actionable, "over the cap" is not.
        composition = ", ".join(f"{ex} x{n}" for ex, n in sorted(mix.items()))
        issues.append(
            f"SPINAL_CAP:{week}:cost {cost:g} exceeds cap {cap:g}"
            + (f" ({composition})" if composition else "")
        )

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
