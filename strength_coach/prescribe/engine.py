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
from dataclasses import replace
from typing import Any, Mapping

import pandas as pd

from strength_coach.features import readiness as readiness_mod
from strength_coach.prescribe import config as config_mod
from strength_coach.prescribe import constraints as constraints_mod
from strength_coach.features import vbt_calibration
from strength_coach.prescribe import schemes as schemes_mod
from strength_coach.prescribe import undulation as undulation_mod
from strength_coach.prescribe import fallback, loads, templates
from strength_coach.prescribe.models import Prescription, PrescriptionItem
from strength_coach.rules import RuleContext, evaluate, load_document, registry
from strength_coach.rules import policy as policy_mod
from strength_coach.store import queries, repositories
from strength_coach.utils import exercises as exercises_mod

RULE_REF_RE = re.compile(r"^(PRG|MOD)-[A-Z]+-\d{3}$")
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
) -> Prescription:
    """Generate the deterministic session for `for_date`."""
    document = document or load_document()
    thresholds = thresholds or config_mod.Thresholds.load()
    template = template or templates.DayTemplate.load(session_day)
    readiness_config = readiness_config or readiness_mod.ReadinessConfig.load()
    undulation = undulation or undulation_mod.Undulation.load()

    context = RuleContext.from_store(conn, end=for_date, rep_ranges=template.rep_ranges())
    policy_result = evaluate(document, context)
    decisions = policy_result.verdict("PRG-DP-001").details.get("decisions", {})

    items: list[PrescriptionItem] = []
    warnings: list[str] = []

    for index, slot in enumerate(template.slots):
        item, slot_warnings = build_item(
            conn, context, slot, index, thresholds, for_date, decisions, template
        )
        items.append(item)
        warnings.extend(slot_warnings)
    dup_plan = None
    if undulation.enabled and context.block_week_index:
        items, dup_warnings, dup_plan = _apply_undulation(
            conn, context, tuple(items), template, thresholds, for_date, decisions, undulation
        )
        warnings.extend(dup_warnings)

    fallback_level = "full"
    readiness = queries.readiness_day(conn, for_date)
    trigger = readiness_config.trigger(readiness)
    if trigger:
        multiplier = thresholds.fatigue_load_multiplier
        items = list(
            fallback.scale_loads(
                tuple(items),
                multiplier,
                extra_refs=("MOD-FAT-001", f"readiness:{for_date}"),
            )
        )
        fallback_level = "fatigue_reduced"
        warnings.append(
            f"MOD-FAT-001: {trigger}; loads x{multiplier} (readiness {for_date})"
        )

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

    items, calibration_ids, vbt_note = _attach_vbt_targets(
        conn, context, tuple(items), for_date, fallback_level
    )

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

    return Prescription(
        for_date=for_date,
        session_day=session_day,
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
            "undulation_week": (
                ((int(context.block_week_index) - 1) % undulation.cycle_weeks) + 1
                if dup_plan and undulation.cycle_weeks else None
            ),
            "undulation": dict(dup_plan) if dup_plan else {},
            "policy_outcome": policy_result.outcome,
            "e1rm_window_days": thresholds.e1rm_window_days,
            "fatigue_trigger": trigger,
            "readiness_fields": list(readiness_config.modifier_fields),
            "back_flare": bool(context.symptom_flare),
            "constraints": constraint_report.status,
        },
    )


# Lifts whose velocity signal is not trustworthy enough to prescribe from (docs/VBT-EVIDENCE.md).
VBT_UNRELIABLE = {"trap_bar_deadlift"}


def _attach_vbt_targets(
    conn,
    context: RuleContext,
    items: tuple[PrescriptionItem, ...],
    for_date: str,
    fallback_level: str,
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

    result = vbt_calibration.calibrate(context.sets)
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
    out: list[PrescriptionItem] = []
    for item in items:
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
            conn, context, slot, item.order_index, thresholds, for_date, decisions, template
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
) -> tuple[PrescriptionItem, tuple[str, ...]]:
    """Build one item from a slot, solving its load from stored history.

    Kept separate from the loop so a proposal can rebuild a single item after a substitution
    without re-deriving loads itself -- the proposal path must use the same solver as the
    deterministic path, or the two would drift.
    """
    warnings: list[str] = []
    exercise_id, chosen_variant = _choose_exercise(slot, context)
    if chosen_variant:
        warnings.append(f"{slot.id}: chose {exercise_id} from {list(slot.variants)}")

    increment = thresholds.increment_for(exercise_id)
    bodyweight = bool(context.entity(exercise_id).get("bodyweight_type", False))
    load: float | None
    refs: tuple[str, ...] = ()
    unknown_reason: str | None = None

    if slot.load_source == "e1rm":
        found = _latest_e1rm(conn, context, exercise_id, for_date,
                              thresholds.e1rm_window_days)
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
            e1rm_kg, ref = found
            load = loads.solve_load(e1rm_kg, slot.reps_low, slot.rir_low, increment)
            refs = ("PRG-RIR-001", ref)
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


def _latest_e1rm(
    conn, context: RuleContext, exercise_id: str, for_date: str, window_days: int
) -> tuple[float, str] | None:
    """The e1RM to prescribe from, with a citable reference.

    A manual override in force on the date outranks the computed estimate: the athlete may
    know a tested value the formula cannot see. Otherwise the best usable e1RM in the window
    ending at `for_date` is used. The window is measured from the prescription date, not from
    the last session, so a returning athlete is not prescribed from a pre-break peak.
    """
    override = queries.e1rm_override(conn, exercise_id, for_date)
    if override is not None:
        return float(override["e1rm_kg"]), f"e1rm_override:{override['override_id']}"

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
    row = usable.loc[usable["e1rm_kg"].idxmax()]
    return float(row["e1rm_kg"]), f"set:{row['session_id']}/{int(row['set_id'])}"


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
