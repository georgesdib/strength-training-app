"""Deterministic resolver core (Step 2).

This module chooses exercises for the four canonical session types. It does not build a
prescription, persist a session, choose a top set or apply the volume budget; those are later
steps. The fixed blueprint remains the default when the resolver flag is off.

The selection is deterministic: the same policy, settings, athlete state and history produce
the same result. No LLM and no randomness participate.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import pandas as pd

from strength_coach import settings_profile
from strength_coach.features import injury_signal, readiness_score, recent_stress, volume
from strength_coach.prescribe import constraints as constraints_mod
from strength_coach.prescribe import resolver_policy, templates
from strength_coach.prescribe.resolver_settings import ResolverSettings
from strength_coach.rules import RuleContext
from strength_coach.rules import loader as rules_loader
from strength_coach.rules import registry as rules_registry
from strength_coach.store import queries
from strength_coach.utils import exercises

STRESS_MISSING = 0.5
READINESS_MISSING = 0.5
COVERAGE_FACTORS = {"balanced": 0.15, "under_target": 0.25, "strict": 0.35}


class GenerationError(ValueError):
    """The generator cannot produce a valid session for a slot."""

    def __init__(
        self,
        message: str,
        *,
        session_type: str | None = None,
        slot_id: str | None = None,
    ) -> None:
        self.session_type = session_type
        self.slot_id = slot_id
        super().__init__(message)


@dataclass(frozen=True)
class GeneratedSlot:
    slot_id: str
    exercise_id: str
    pattern: str | None
    score: float
    reasons: tuple[str, ...]
    alternatives: tuple[str, ...]
    pending_rating: bool


@dataclass(frozen=True)
class GeneratedSession:
    for_date: str
    session_type: str
    template: templates.SessionTemplate
    slots: tuple[GeneratedSlot, ...]
    pending_ratings: tuple[str, ...]
    suggestions: tuple[str, ...]
    warnings: tuple[str, ...]
    policy_digest: str
    catalogue_digest: str

    @property
    def exercise_ids(self) -> tuple[str, ...]:
        return tuple(slot.exercise_id for slot in self.slots)


@dataclass(frozen=True)
class CandidatePools:
    """Eligible, ordered candidate pools for the joint evaluator."""

    template: templates.SessionTemplate
    pools: Mapping[str, tuple[str, ...]]
    main_slot: templates.Slot | None
    policy_digest: str
    catalogue_digest: str
    required_patterns: tuple[str, ...] = ()
    candidate_patterns: Mapping[str, Mapping[str, str | None]] = field(
        default_factory=dict
    )
    suggestions: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    exercise_id: str
    pattern: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _SlotChoice:
    exercise_id: str
    score: float
    reasons: tuple[str, ...]
    alternatives: tuple[str, ...]
    pending_rating: bool


def generate(
    conn,
    *,
    for_date: str,
    session_type: str,
    policy: resolver_policy.ResolverPolicy | None = None,
    settings: ResolverSettings | None = None,
    context: RuleContext | None = None,
    runtime: settings_profile.FeatureSettings | None = None,
) -> GeneratedSession:
    """Choose a complete exercise list for one session.

    The caller supplies the date and session type. The context and runtime values are
    optional precomputed inputs for tests and forecast callers; when absent they are loaded
    from the store. This function never writes to the store.
    """
    if session_type not in templates.SESSION_TYPES:
        raise GenerationError(
            f"unknown session type {session_type!r}", session_type=str(session_type)
        )
    policy = policy or resolver_policy.ResolverPolicy.load()
    settings = settings or ResolverSettings.load(conn, for_date)
    runtime = runtime or settings_profile.feature_settings(conn, for_date)
    if context is None:
        context = RuleContext.from_store(
            conn,
            end=for_date,
            rep_ranges=templates.all_rep_ranges(),
            spinal_cap=runtime.spinal_cap,
            spinal_costs=runtime.spinal_costs,
        )
    template = templates.SessionTemplate.load(session_type)
    catalogue = resolver_policy.load_candidate_catalogue(policy)
    catalogue_digest = resolver_policy.candidate_catalogue_digest(catalogue)
    taxonomy = exercises.taxonomy().entities
    accounting = context.prior_to(for_date)
    assessment = readiness_score.compute(conn, for_date)
    injury = injury_signal.compute(conn, for_date, ramp_week=context.block_week_index)
    stress_config = recent_stress.StressConfig.load()
    stress = recent_stress.compute(context.sets, for_date, config=stress_config)
    suitability = queries.exercise_suitability(conn)
    active_linked = {
        exercise_id
        for region in injury.regions
        if region.status == injury_signal.STATUS_ACTIVE
        for exercise_id in region.linked_exercises
    }
    main_slot = _main_slot(template, taxonomy)
    history = _choice_history(conn, session_type, for_date)
    volume_config = runtime.volume
    rule = _spinal_rule()
    week_start, week_end = _week_bounds(for_date)
    current_spinal = _weekly_spinal_cost(rule, accounting, week_start)
    spinal_cap = _spinal_cap(context, rule)

    pools: dict[str, tuple[str, ...]] = {}
    all_candidates: set[str] = set()
    for slot in template.slots:
        candidates = _candidate_ids(session_type, slot, policy, catalogue)
        pools[slot.id] = candidates
        all_candidates.update(candidates)
    veto_report = constraints_mod.evaluate(conn, sorted(all_candidates))
    vetoed = {exercise_id for exercise_id, _reason in veto_report.vetoes}

    selected: dict[str, str] = {}
    choices: dict[str, _SlotChoice] = {}
    warnings: list[str] = []
    suggestions: list[str] = []

    for index, slot in enumerate(template.slots):
        role = _slot_role(slot, main_slot)
        pool = pools[slot.id]
        permitted = _permitted_patterns(slot, role, policy, main_slot, taxonomy)
        default_id = _default_id(slot)
        last_id, sessions_since_change = _last_choice(history, index)
        rotation = settings.rotation_for(role=role)
        dwell = settings.rotation_dwell(rotation)

        auto, slot_suggestions = _classify_candidates(
            pool, permitted, vetoed, active_linked, suitability, settings, taxonomy
        )
        for candidate in slot_suggestions:
            if candidate not in suggestions:
                suggestions.append(candidate)
        if default_id is None:
            raise GenerationError(
                f"{session_type}/{slot.id}: no blueprint default exercise",
                session_type=session_type,
                slot_id=slot.id,
            )
        default_state = _candidate_class(
            default_id, permitted, vetoed, active_linked, suitability, settings, taxonomy
        )
        unrated_suggestions = [item for item in slot_suggestions if item not in suitability]
        if not auto and unrated_suggestions:
            # Carry only unrated suggestions into the preview; pending_rating remains true
            # until the athlete rates one. will_do/feels_bad blocks stay suggestion-only.
            auto = list(unrated_suggestions)
            warnings.append(
                f"{slot.id}: no rated candidate; suggesting {sorted(unrated_suggestions)} for rating"
            )

        if slot.power:
            if default_state != AUTO and not (
                default_state == SUGGESTION and default_id not in suitability
            ):
                raise GenerationError(
                    f"{session_type}/{slot.id}: fixed power exercise {default_id!r} "
                    f"is {_state_reason(default_state)}",
                    session_type=session_type,
                    slot_id=slot.id,
                )
            chosen = default_id
            reasons = ("fixed power slot",)
            score = 1.0
        elif last_id and last_id in auto and not _must_rotate(
            rotation, dwell, sessions_since_change
        ):
            chosen = last_id
            scored = _score(
                conn, chosen, slot, selected, template, accounting, assessment, injury,
                stress, stress_config, suitability, settings, volume_config, policy, rule,
                taxonomy, current_spinal, spinal_cap, last_id, week_start, week_end,
            )
            score = scored.score
            reasons = (
                f"kept last choice {last_id} because the dwell period has not elapsed",
                f"rotation {rotation:.2f}",
            ) + scored.reasons
        elif auto:
            must_rotate = _must_rotate(rotation, dwell, sessions_since_change)
            candidates = [c for c in auto if not (must_rotate and c == last_id)]
            if not candidates:
                if must_rotate and last_id is not None:
                    warnings.append(
                        f"{slot.id}: rotation change was due (rotation {rotation:.2f}) "
                        f"but no eligible alternative to {last_id} existed; kept it"
                    )
                candidates = list(auto)
            ranked = _rank(
                conn, candidates, slot, selected, template, accounting, assessment,
                injury, stress, stress_config, suitability, settings, volume_config, policy,
                rule, taxonomy, current_spinal, spinal_cap, last_id, week_start, week_end,
            )
            chosen = ranked[0].exercise_id
            score = ranked[0].score
            reasons = ranked[0].reasons
        else:
            hint = (
                f"; suggestions require confirmation: {sorted(slot_suggestions)}"
                if slot_suggestions
                else ""
            )
            raise GenerationError(
                f"{session_type}/{slot.id}: no automatically eligible candidate"
                f" (default {default_id!r} is {_state_reason(default_state)}){hint}",
                session_type=session_type,
                slot_id=slot.id,
            )

        selected[slot.id] = chosen
        choices[slot.id] = _SlotChoice(
            exercise_id=chosen,
            score=score,
            reasons=reasons,
            alternatives=_alternatives(
                conn, auto, slot, selected, template, accounting, assessment, injury, stress,
                stress_config, suitability, settings, volume_config, policy, rule, taxonomy, current_spinal,
                spinal_cap, last_id, chosen, week_start, week_end,
            ),
            pending_rating=_pending_rating(chosen, suitability, settings),
        )

    selected, choices, repair_warnings = _repair_required(
        template, main_slot, pools, selected, choices, policy, suitability, vetoed,
        active_linked, taxonomy, settings, conn, accounting, assessment, injury, stress,
        stress_config, volume_config, rule, current_spinal, spinal_cap, session_type,
        week_start, week_end,
    )
    warnings.extend(repair_warnings)
    _validate_spinal(
        rule, accounting, template, selected, for_date, spinal_cap, session_type
    )

    generated_slots = tuple(
        GeneratedSlot(
            slot_id=slot.id,
            exercise_id=selected[slot.id],
            pattern=_pattern(selected[slot.id], taxonomy),
            score=choices[slot.id].score,
            reasons=choices[slot.id].reasons,
            alternatives=choices[slot.id].alternatives,
            pending_rating=choices[slot.id].pending_rating,
        )
        for slot in template.slots
    )
    generated_template = replace(
        template,
        slots=tuple(
            replace(slot, exercise=selected[slot.id], variants=())
            for slot in template.slots
        ),
        primary_exercise=(
            selected[main_slot.id] if main_slot is not None else template.primary_exercise
        ),
    )
    pending_unique = tuple(
        dict.fromkeys(slot.exercise_id for slot in generated_slots if slot.pending_rating)
    )
    return GeneratedSession(
        for_date=for_date,
        session_type=session_type,
        template=generated_template,
        slots=generated_slots,
        pending_ratings=pending_unique,
        suggestions=tuple(suggestions),
        warnings=tuple(warnings),
        policy_digest=policy.digest,
        catalogue_digest=catalogue_digest,
    )


def candidate_pools(
    conn,
    *,
    for_date: str,
    session_type: str,
    policy: resolver_policy.ResolverPolicy | None = None,
    settings: ResolverSettings | None = None,
    context: RuleContext | None = None,
    template: templates.SessionTemplate | None = None,
) -> CandidatePools:
    """Return eligible candidate pools for the joint beam.

    Only candidates that pass the same hard eligibility, injury, suitability and can_do rules as
    generate() are returned. The pool order is the generator's preference: the last choice is
    first while its dwell is active, otherwise it is placed last when rotation is due. There is
    no blueprint fallback for a slot with no eligible candidate.

    Step 2's independent _score/_rank ordering is intentionally not applied here. Step 4's joint
    evaluator is authoritative for assignment quality; candidate order only supplies deterministic
    beam rank cost/tie-breaking. No Step 2 objective is double-counted.
    """
    if session_type not in templates.SESSION_TYPES and template is None:
        raise GenerationError(
            f"unknown session type {session_type!r}", session_type=str(session_type)
        )
    policy = policy or resolver_policy.ResolverPolicy.load()
    settings = settings or ResolverSettings.load(conn, for_date)
    if context is None:
        runtime = settings_profile.feature_settings(conn, for_date)
        context = RuleContext.from_store(
            conn,
            end=for_date,
            rep_ranges=templates.all_rep_ranges(),
            spinal_cap=runtime.spinal_cap,
            spinal_costs=runtime.spinal_costs,
        )
    template = template or templates.SessionTemplate.load(session_type)
    catalogue = resolver_policy.load_candidate_catalogue(policy)
    catalogue_digest = resolver_policy.candidate_catalogue_digest(catalogue)
    taxonomy = exercises.taxonomy().entities
    injury = injury_signal.compute(conn, for_date, ramp_week=context.block_week_index)
    suitability = queries.exercise_suitability(conn)
    active_linked = {
        term
        for region in injury.regions
        if region.status == injury_signal.STATUS_ACTIVE
        for term in region.linked_exercises
    }
    main_slot = _main_slot(template, taxonomy)
    history = _choice_history(conn, session_type, for_date)

    raw_pools: dict[str, tuple[str, ...]] = {}
    all_candidates: set[str] = set()
    for slot in template.slots:
        candidates = _candidate_ids(session_type, slot, policy, catalogue)
        raw_pools[slot.id] = candidates
        all_candidates.update(candidates)
    vetoed = {
        exercise_id
        for exercise_id, _reason in constraints_mod.evaluate(
            conn, sorted(all_candidates)
        ).vetoes
    }

    available, reason, auto_by_slot = _structure_check(
        template, policy, main_slot, raw_pools, vetoed, active_linked,
        suitability, settings, taxonomy,
    )
    if not available:
        raise GenerationError(
            f"{session_type}: {reason}", session_type=session_type
        )

    ordered: dict[str, tuple[str, ...]] = {}
    suggestions_by_slot: dict[str, tuple[str, ...]] = {}
    for index, slot in enumerate(template.slots):
        auto = list(auto_by_slot[slot.id])
        role = _slot_role(slot, main_slot)
        last_id, sessions_since_change = _last_choice(history, index)
        rotation = settings.rotation_for(role=role)
        must_rotate = _must_rotate(
            rotation, settings.rotation_dwell(rotation), sessions_since_change
        )
        if last_id in auto:
            rest = [candidate for candidate in auto if candidate != last_id]
            auto = rest + [last_id] if must_rotate else [last_id] + rest
        ordered[slot.id] = tuple(auto)
        _auto_check, suggestions = _classify_candidates(
            raw_pools[slot.id],
            _permitted_patterns(slot, role, policy, main_slot, taxonomy),
            vetoed,
            active_linked,
            suitability,
            settings,
            taxonomy,
        )
        suggestions_by_slot[slot.id] = tuple(suggestions)

    return CandidatePools(
        template=template,
        pools=ordered,
        main_slot=main_slot,
        policy_digest=policy.digest,
        catalogue_digest=catalogue_digest,
        required_patterns=_required_pattern_keys(policy, session_type),
        candidate_patterns={
            slot.id: {
                exercise_id: _pattern_key(exercise_id, taxonomy)
                for exercise_id in ordered[slot.id]
            }
            for slot in template.slots
        },
        suggestions=suggestions_by_slot,
    )


def _required_pattern_keys(
    policy: resolver_policy.ResolverPolicy, session_type: str
) -> tuple[str, ...]:
    return tuple(
        volume.volume_target_key(pattern)
        for pattern in policy.required_patterns[session_type]
    )


def _patterns_assignable(
    required: Sequence[str], patterns_by_slot: Mapping[str, set[str]]
) -> bool:
    """Small deterministic bipartite match: each required pattern needs a distinct slot."""
    matching: dict[str, str] = {}

    def assign(key: str, seen: set[str]) -> bool:
        for slot_id in sorted(patterns_by_slot):
            if slot_id in seen or key not in patterns_by_slot[slot_id]:
                continue
            seen.add(slot_id)
            if slot_id not in matching or assign(matching[slot_id], seen):
                matching[slot_id] = key
                return True
        return False

    return all(assign(key, set()) for key in required)


def patterns_assignable(
    required: Sequence[str], patterns_by_slot: Mapping[str, set[str]]
) -> bool:
    """Public structural matching contract shared with the bounded beam."""
    return _patterns_assignable(required, patterns_by_slot)


def _structure_check(
    template: templates.SessionTemplate,
    policy: resolver_policy.ResolverPolicy,
    main_slot: templates.Slot | None,
    pools: Mapping[str, Sequence[str]],
    vetoed: set[str],
    active_injury: set[str],
    suitability: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, str, dict[str, list[str]]]:
    """One authoritative automatic-candidate and slot-pattern feasibility check."""
    auto_by_slot: dict[str, list[str]] = {}
    for slot in template.slots:
        role = _slot_role(slot, main_slot)
        permitted = _permitted_patterns(slot, role, policy, main_slot, taxonomy)
        auto, suggestions = _classify_candidates(
            pools[slot.id], permitted, vetoed, active_injury, suitability, settings,
            taxonomy,
        )
        # A suggestion-only slot is a provisional preview candidate, not an automatic
        # selection. It lets the athlete see and rate the proposed lift instead of losing
        # the whole session family before the rating UI can appear. Start remains gated.
        if not auto:
            auto = [item for item in suggestions if item not in suitability]
        if not auto:
            return False, f"slot {slot.id!r}: no automatically eligible candidate", {}
        auto_by_slot[slot.id] = auto

    patterns_by_slot = {
        slot_id: {
            key
            for exercise_id in auto
            if (key := _pattern_key(exercise_id, taxonomy)) is not None
        }
        for slot_id, auto in auto_by_slot.items()
    }
    required = _required_pattern_keys(policy, template.session_type)
    if not _patterns_assignable(required, patterns_by_slot):
        missing = [
            key
            for key in required
            if not any(key in patterns for patterns in patterns_by_slot.values())
        ]
        detail = f" (missing pattern {missing[0]!r})" if missing else ""
        return (
            False,
            f"required patterns cannot be assigned to distinct slots{detail}",
            {},
        )
    return True, "", auto_by_slot


def required_pattern_violations(
    template: templates.SessionTemplate,
    assignment: Mapping[str, str],
    policy: resolver_policy.ResolverPolicy,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return structural violations for one complete assignment.

    This applies the same distinct-slot matching rule used by candidate-pool feasibility, but to
    the actual selected exercises rather than the theoretical pools.
    """
    required = _required_pattern_keys(policy, template.session_type)
    patterns_by_slot = {
        slot.id: {
            key
            for exercise_id in (assignment.get(slot.id),)
            if exercise_id is not None
            if (key := _pattern_key(exercise_id, taxonomy)) is not None
        }
        for slot in template.slots
    }
    if _patterns_assignable(required, patterns_by_slot):
        return ()
    missing = [
        key
        for key in required
        if not any(key in patterns for patterns in patterns_by_slot.values())
    ]
    if missing:
        return (
            "missing required pattern(s): " + ", ".join(sorted(set(missing))),
        )
    return ("required patterns cannot be assigned to distinct slots",)


def available_session_types(
    conn,
    for_date: str,
    *,
    policy: resolver_policy.ResolverPolicy | None = None,
) -> dict[str, bool]:
    """Pool-aware availability for the four identities. Read-only.

    A session is available only when every slot has an automatically eligible candidate and the
    required patterns can be assigned to distinct permitted slots. Suggestions, unrated
    confirmation and scoring are intentionally not part of this check.
    """
    policy = policy or resolver_policy.ResolverPolicy.load()
    catalogue = resolver_policy.load_candidate_catalogue(policy)
    taxonomy = exercises.taxonomy().entities
    settings = ResolverSettings.load(conn, for_date)
    runtime = settings_profile.feature_settings(conn, for_date)
    context = RuleContext.from_store(
        conn,
        end=for_date,
        rep_ranges=templates.all_rep_ranges(),
        spinal_cap=runtime.spinal_cap,
        spinal_costs=runtime.spinal_costs,
    )
    suitability = queries.exercise_suitability(conn)
    injury = injury_signal.compute(
        conn, for_date, ramp_week=context.block_week_index
    )
    active_injury = {
        term
        for region in injury.regions
        if region.status == injury_signal.STATUS_ACTIVE
        for term in region.linked_exercises
    }
    out: dict[str, bool] = {}
    for session_type in templates.SESSION_TYPES:
        template = templates.SessionTemplate.load(session_type)
        main_slot = _main_slot(template, taxonomy)
        if main_slot is None:
            out[session_type] = False
            continue
        pools = {
            slot.id: _candidate_ids(session_type, slot, policy, catalogue)
            for slot in template.slots
        }
        all_candidates = sorted({item for ids in pools.values() for item in ids})
        report = constraints_mod.evaluate(conn, all_candidates)
        vetoed = {exercise_id for exercise_id, _reason in report.vetoes}
        available, _reason, _auto = _structure_check(
            template, policy, main_slot, pools, vetoed, active_injury,
            suitability, settings, taxonomy,
        )
        out[session_type] = available
    return out


def _main_slot(
    template: templates.SessionTemplate,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> templates.Slot | None:
    if template.primary_exercise:
        for slot in template.slots:
            if template.primary_exercise in slot.exercises:
                return slot
    return next((slot for slot in template.slots if slot.essential and not slot.power), None)


def _slot_role(slot: templates.Slot, main_slot: templates.Slot | None) -> str:
    if slot.power:
        return "power"
    if main_slot is not None and slot.id == main_slot.id:
        return "main"
    if slot.essential:
        return "secondary"
    return "accessory"


def _default_id(slot: templates.Slot) -> str | None:
    if slot.exercise:
        return slot.exercise
    return slot.variants[0] if slot.variants else None


def _pattern(exercise_id: str, taxonomy: Mapping[str, Mapping[str, Any]]) -> str | None:
    pattern = taxonomy.get(exercise_id, {}).get("pattern")
    return str(pattern) if pattern else None


def _pattern_key(exercise_id: str, taxonomy: Mapping[str, Mapping[str, Any]]) -> str | None:
    pattern = _pattern(exercise_id, taxonomy)
    return volume.volume_target_key(pattern) if pattern else None


def _default_patterns(
    slot: templates.Slot, taxonomy: Mapping[str, Mapping[str, Any]]
) -> set[str]:
    return {
        pattern
        for exercise_id in slot.exercises
        if (pattern := _pattern(exercise_id, taxonomy)) is not None
    }


def _primary_patterns(
    main_slot: templates.Slot | None,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    return _default_patterns(main_slot, taxonomy) if main_slot is not None else set()


def _permitted_patterns(
    slot: templates.Slot,
    role: str,
    policy: resolver_policy.ResolverPolicy,
    main_slot: templates.Slot | None,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    if role == "main":
        return _primary_patterns(main_slot, taxonomy) or _default_patterns(slot, taxonomy)
    if role == "secondary":
        return _default_patterns(slot, taxonomy)
    if slot.id in policy.allowed_patterns:
        return set(policy.allowed_patterns[slot.id])
    return _default_patterns(slot, taxonomy)


def _pattern_allowed(
    exercise_id: str,
    permitted: set[str],
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> bool:
    pattern = _pattern(exercise_id, taxonomy)
    return pattern is not None and pattern in permitted


def _candidate_ids(
    session_type: str,
    slot: templates.Slot,
    policy: resolver_policy.ResolverPolicy,
    catalogue: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> tuple[str, ...]:
    if slot.power:
        return slot.exercises
    explicit = policy.slot_pools.get(session_type, {}).get(slot.id)
    if explicit:
        return tuple(explicit)
    ids = list(slot.exercises)
    ids.extend(catalogue.get(session_type, {}).get(slot.id, ()))
    return tuple(dict.fromkeys(ids))


def _week_bounds(on_date: str) -> tuple[str, str]:
    day = dt.date.fromisoformat(str(on_date))
    start = day - dt.timedelta(days=day.weekday())
    end = start + dt.timedelta(days=6)
    return start.isoformat(), end.isoformat()


def _plan_mapping(plan_json: str) -> dict[int, str]:
    try:
        plan = json.loads(plan_json)
    except (TypeError, ValueError):
        return {}
    items = plan.get("items") if isinstance(plan, Mapping) else None
    if not isinstance(items, list):
        return {}
    mapping: dict[int, str] = {}
    for index, item in enumerate(items):
        if not isinstance(item, Mapping) or not item.get("exercise_id"):
            continue
        try:
            order = int(item.get("order_index", index))
        except (TypeError, ValueError):
            order = index
        mapping[order] = str(item["exercise_id"])
    return mapping


def _choice_history(conn, session_type: str, before_date: str) -> list[dict[int, str]]:
    """Recent session choices, newest first, merged by date.

    A completed workout is the performed record for its date. A prescription supplies the
    fallback only when no completed workout exists for that same date, so a plan and its
    performed session are never counted twice.
    """
    by_date: dict[str, dict[int, str]] = {}
    completed_dates: set[str] = set()
    rows = conn.execute(
        """
        SELECT for_date, plan_json FROM workout_session
         WHERE session_type = ? AND for_date < ? AND status = 'completed'
         ORDER BY for_date DESC, started_at DESC
         LIMIT 52
        """,
        (session_type, before_date),
    ).fetchall()
    for row in rows:
        mapping = _plan_mapping(row["plan_json"])
        date = str(row["for_date"])
        completed_dates.add(date)
        if mapping and date not in by_date:
            by_date[date] = mapping

    rows = conn.execute(
        """
        SELECT p.prescription_id, p.for_date, pi.order_index, pi.exercise_id
          FROM prescription p
          JOIN prescription_item pi ON pi.prescription_id = p.prescription_id
         WHERE p.session_type = ? AND p.for_date < ?
         ORDER BY p.for_date DESC, p.created_at DESC, p.prescription_id DESC,
                  pi.order_index ASC
         LIMIT 520
        """,
        (session_type, before_date),
    ).fetchall()
    grouped: dict[str, tuple[str, dict[int, str]]] = {}
    for row in rows:
        prescription = str(row["prescription_id"])
        date = str(row["for_date"])
        if prescription not in grouped:
            grouped[prescription] = (date, {})
        grouped[prescription][1][int(row["order_index"])] = str(row["exercise_id"])
    prescription_by_date: dict[str, dict[int, str]] = {}
    for date, mapping in grouped.values():
        if mapping and date not in prescription_by_date:
            prescription_by_date[date] = mapping
    for date, mapping in prescription_by_date.items():
        if date not in completed_dates:
            by_date[date] = mapping
    return [by_date[date] for date in sorted(by_date, reverse=True)]


def _last_choice(history: Sequence[Mapping[int, str]], index: int) -> tuple[str | None, int]:
    """Most recent row containing the slot; newer rows missing that slot are skipped."""
    for start, entry in enumerate(history):
        last = entry.get(index)
        if last is None:
            continue
        count = 0
        for later in history[start:]:
            value = later.get(index)
            if value is None:
                continue
            if value != last:
                break
            count += 1
        return last, count
    return None, 0


def _must_rotate(rotation: float, dwell: int | None, sessions_since_change: int) -> bool:
    if rotation <= 0.0 or dwell is None:
        return False
    return sessions_since_change >= dwell

AUTO = "auto"
SUGGESTION = "suggestion"
EXCLUDED = "excluded"


def _injury_matches(
    exercise_id: str,
    terms: Iterable[str],
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Match a concrete exercise id or a pattern:<family> injury identifier."""
    if exercise_id in terms:
        return True
    pattern = _pattern(exercise_id, taxonomy)
    return bool(pattern and f"pattern:{pattern}" in terms)


def _injury_excludes(
    exercise_id: str,
    active_terms: Iterable[str],
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> bool:
    return _injury_matches(exercise_id, active_terms, taxonomy)


def _injury_component(
    injury,
    exercise_id: str,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> float:
    """Candidate-specific injury score without double-counting readiness.

    The readiness ceiling already covers every region except the low back, which DEC-INJURY-04
    deliberately leaves to the back-flare rules. The resolver weight is therefore a low-back
    review/monitoring signal only; active low-back links are hard exclusions, not scores.
    """
    region = injury.region("low_back") if injury is not None else None
    if region is None or region.status not in (
        injury_signal.STATUS_REVIEW,
        injury_signal.STATUS_MONITORING,
    ):
        return 1.0
    if not _injury_matches(exercise_id, region.linked_exercises, taxonomy):
        return 1.0
    return 0.65 if region.status == injury_signal.STATUS_REVIEW else 0.85


def _pending_rating(
    exercise_id: str,
    suitability: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
) -> bool:
    """The one rule for a selected-but-unconfirmed exercise."""
    return suitability.get(exercise_id) is None and settings.unrated_mode != "exclude"


def _state_reason(state: str) -> str:
    if state == EXCLUDED:
        return "hard-excluded, vetoed, injured or not permitted"
    if state == SUGGESTION:
        return "suggestion-only (unrated/needs confirmation or preference block)"
    return "automatically eligible"


def _candidate_class(
    exercise_id: str,
    permitted: set[str],
    vetoed: set[str],
    active_injury: set[str],
    suitability: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> str:
    """Classify a candidate as automatic, suggestion-only or excluded.

    Hard constraints and active injury links always exclude. Unrated behaviour is controlled
    by require_can_do and unrated_mode. will_do=0 and feels_bad=1 are never automatic; the
    corresponding Step 1 flags decide whether they remain suggestion-only or are hidden.
    """
    if not _pattern_allowed(exercise_id, permitted, taxonomy):
        return EXCLUDED
    if exercise_id in vetoed or _injury_excludes(exercise_id, active_injury, taxonomy):
        return EXCLUDED
    rating = suitability.get(exercise_id)
    if rating is None:
        # unrated_mode is the policy for the requirement-on case; when can_do is not
        # required the candidate is admissible automatically.
        if settings.require_can_do:
            return SUGGESTION if settings.unrated_mode == "confirm" else EXCLUDED
        return AUTO
    if not rating["can_do"]:
        return EXCLUDED
    if not rating["will_do"]:
        return SUGGESTION if settings.will_do_blocks else EXCLUDED
    if rating["feels_bad"]:
        return SUGGESTION if settings.feels_bad_blocks else EXCLUDED
    return AUTO


def _classify_candidates(
    pool: Sequence[str],
    permitted: set[str],
    vetoed: set[str],
    active_injury: set[str],
    suitability: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    auto: list[str] = []
    suggestions: list[str] = []
    for exercise_id in pool:
        state = _candidate_class(
            exercise_id, permitted, vetoed, active_injury, suitability, settings, taxonomy
        )
        if state == AUTO:
            auto.append(exercise_id)
        elif state == SUGGESTION:
            suggestions.append(exercise_id)
    return auto, suggestions


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _readiness_component(
    assessment,
    conn,
    exercise_id: str,
    entity: Mapping[str, Any],
    injury,
) -> float:
    score, _factor, _rir, ceiling = readiness_score.effective(
        assessment, conn, exercise_id, entity, signal=injury
    )
    category = readiness_score.category_for(exercise_id, entity)
    base = (
        assessment.score
        if category is None
        else assessment.category_scores.get(category, assessment.score)
    )
    if base is None and not assessment.overrides:
        value = READINESS_MISSING
        if ceiling is not None:
            value = min(value, float(ceiling))
        return _clamp(value)
    return _clamp(score)


def _stress_component(
    exercise_id: str,
    stress: Mapping[str, recent_stress.StressEntry],
    config: recent_stress.StressConfig,
) -> float:
    entry = stress.get(exercise_id)
    if entry is None:
        return STRESS_MISSING
    return _clamp(1.0 - entry.decayed_sets / max(config.high_decayed_sets, 1.0))


def _session_spinal_extra(
    template: templates.SessionTemplate,
    selected: Mapping[str, str],
    slot: templates.Slot,
    candidate: str,
    week_start: str,
) -> list[tuple[str, str, str, int, None]]:
    """One aggregated extra row per exercise for the proposed generated session.

    spinal_exposures() keys by (session_id, exercise_id). Sending one row per slot would let a
    duplicate exercise overwrite an earlier slot instead of contributing its sets. Aggregate the
    whole proposed session by exercise id before calling the authoritative rule.
    """
    assignment = dict(selected)
    assignment[slot.id] = candidate
    sets_by_exercise: Counter[str] = Counter()
    for current in template.slots:
        exercise_id = assignment.get(current.id) or _default_id(current)
        if exercise_id is not None:
            sets_by_exercise[exercise_id] += int(current.sets)
    session_id = f"generator:{week_start}"
    return [
        (session_id, exercise_id, week_start, sets, None)
        for exercise_id, sets in sets_by_exercise.items()
    ]


def _provisional_spinal_delta(
    rule,
    accounting: RuleContext,
    week_start: str,
    template: templates.SessionTemplate,
    selected: Mapping[str, str],
    slot: templates.Slot,
    candidate: str,
    current_cost: float,
) -> float:
    """Projected whole-session delta from the authoritative spinal rule.

    The proposal includes completed weekly exposures (through accounting), every already
    selected slot, the candidate slot, and the blueprint default for slots not yet selected.
    This keeps candidate comparisons on the same whole-session state while final validation
    remains authoritative.
    """
    if rule is None:
        return 0.0
    extra = _session_spinal_extra(template, selected, slot, candidate, week_start)
    proposed = _weekly_spinal_cost(rule, accounting, week_start, extra)
    return max(0.0, proposed - current_cost)



def _spinal_component(total_cost: float, cap: float) -> float:
    if cap <= 0:
        return 1.0
    return _clamp(1.0 - total_cost / cap)


def _assignment_pattern_sets(
    template: templates.SessionTemplate,
    selected: Mapping[str, str],
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> Counter[str]:
    totals: Counter[str] = Counter()
    for slot in template.slots:
        exercise_id = selected.get(slot.id) or _default_id(slot)
        if exercise_id is None:
            continue
        key = _pattern_key(exercise_id, taxonomy)
        if key is not None:
            totals[key] += int(slot.sets)
    return totals


def _completed_pattern_sets(
    accounting: RuleContext,
    week_start: str,
    week_end: str,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> Counter[str]:
    totals: Counter[str] = Counter()
    frame = accounting.sets
    if frame is None or frame.empty:
        return totals
    required_columns = {"date", "exercise_id", "is_working_set"}
    if not required_columns <= set(frame.columns):
        return totals
    try:
        work = frame[frame["is_working_set"].astype(bool)].copy()
        dates = pd.to_datetime(work["date"], errors="coerce")
        work = work[
            (dates >= pd.Timestamp(week_start))
            & (dates <= pd.Timestamp(week_end))
        ]
    except (TypeError, ValueError):
        return totals
    for row in work.itertuples(index=False):
        key = _pattern_key(str(row.exercise_id), taxonomy)
        if key is not None:
            totals[key] += 1
    return totals


def _coverage_component(
    completed: Counter[str],
    assigned: Counter[str],
    volume_config: Any,
    settings: ResolverSettings,
) -> float:
    targets = getattr(volume_config, "targets", None) or {}
    if not targets:
        return 1.0
    under = 0.0
    over = 0.0
    for key, (low, high) in targets.items():
        total = float(completed.get(key, 0)) + float(assigned.get(key, 0))
        if total < low:
            under += float(low) - total
        elif total > high:
            over += total - float(high)
    denominator = max(
        1.0, sum(max(1.0, float(low)) for low, _high in targets.values())
    )
    raw = 1.0 - (
        settings.under_target_weight * under + settings.over_target_weight * over
    ) / denominator
    return _clamp(raw)


def _redundancy_penalty(
    template: templates.SessionTemplate,
    selected: Mapping[str, str],
    slot: templates.Slot,
    candidate: str,
    policy: resolver_policy.ResolverPolicy,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> float:
    patterns: Counter[str] = Counter()
    muscles: Counter[str] = Counter()
    for current in template.slots:
        exercise_id = candidate if current.id == slot.id else (
            selected.get(current.id) or _default_id(current)
        )
        if exercise_id is None:
            continue
        pattern = _pattern(exercise_id, taxonomy)
        if pattern:
            patterns[pattern] += 1
        for muscle in taxonomy.get(exercise_id, {}).get("primary_muscles") or ():
            muscles[str(muscle)] += 1
    excess = sum(
        max(0, count - policy.redundancy.max_per_pattern)
        for count in patterns.values()
    )
    excess += sum(
        max(0, count - policy.redundancy.max_per_primary_muscle)
        for count in muscles.values()
    )
    return min(0.5, 0.1 * excess)


def _score(
    conn,
    exercise_id: str,
    slot: templates.Slot,
    selected: Mapping[str, str],
    template: templates.SessionTemplate,
    accounting: RuleContext,
    assessment,
    injury,
    stress: Mapping[str, recent_stress.StressEntry],
    stress_config: recent_stress.StressConfig,
    suitability: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
    volume_config: Any,
    policy: resolver_policy.ResolverPolicy,
    rule,
    taxonomy: Mapping[str, Mapping[str, Any]],
    current_spinal: float,
    spinal_cap: float,
    last_id: str | None,
    week_start: str,
    week_end: str,
) -> _Candidate:
    entity = taxonomy.get(exercise_id, {})
    readiness = _readiness_component(assessment, conn, exercise_id, entity, injury)
    stress_value = _stress_component(exercise_id, stress, stress_config)
    candidate_spinal = _provisional_spinal_delta(
        rule, accounting, week_start, template, selected, slot, exercise_id, current_spinal
    )
    spinal = _spinal_component(current_spinal + candidate_spinal, spinal_cap)
    injury_value = _injury_component(injury, exercise_id, taxonomy)
    partial = dict(selected)
    partial[slot.id] = exercise_id
    assigned = _assignment_pattern_sets(template, partial, taxonomy)
    completed = _completed_pattern_sets(accounting, week_start, week_end, taxonomy)
    coverage = _coverage_component(completed, assigned, volume_config, settings)
    redundancy = _redundancy_penalty(template, selected, slot, exercise_id, policy, taxonomy)
    components = (
        ("readiness", readiness),
        ("fatigue", stress_value),
        ("spinal", spinal),
        ("injury", injury_value),
    )
    weights = {key: float(settings.weights.get(key, 0.0)) for key, _value in components}
    total_weight = sum(weights.values())
    weighted = (
        sum(weights[key] * value for key, value in components) / total_weight
        if total_weight > 0
        else 0.0
    )
    factor = COVERAGE_FACTORS.get(settings.coverage_priority, 0.15)
    score = _clamp(weighted + factor * (coverage - 0.5) - redundancy)
    reasons = tuple(
        f"{key} {value:.2f} (weight {weights[key] / total_weight:.2f})"
        for key, value in components
        if total_weight > 0 and weights[key] > 0
    ) + (
        f"coverage {coverage:.2f}",
        f"redundancy penalty {redundancy:.2f}",
    )
    return _Candidate(
        exercise_id=exercise_id,
        pattern=_pattern(exercise_id, taxonomy) or "",
        score=score,
        reasons=reasons,
    )


def _rank_key(
    candidate: _Candidate,
    candidates: Sequence[str],
    stress: Mapping[str, recent_stress.StressEntry],
    tie_break: str,
) -> tuple:
    if tie_break == "canonical":
        return (-candidate.score, candidate.exercise_id)
    if tie_break == "blueprint":
        return (-candidate.score, candidates.index(candidate.exercise_id))
    entry = stress.get(candidate.exercise_id)
    last_date = entry.last_date if entry is not None else "0000-00-00"
    return (-candidate.score, last_date, candidate.exercise_id)


def _rank(
    conn,
    candidates: Sequence[str],
    slot: templates.Slot,
    selected: Mapping[str, str],
    template: templates.SessionTemplate,
    accounting: RuleContext,
    assessment,
    injury,
    stress: Mapping[str, recent_stress.StressEntry],
    stress_config: recent_stress.StressConfig,
    suitability: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
    volume_config: Any,
    policy: resolver_policy.ResolverPolicy,
    rule,
    taxonomy: Mapping[str, Mapping[str, Any]],
    current_spinal: float,
    spinal_cap: float,
    last_id: str | None,
    week_start: str,
    week_end: str,
) -> tuple[_Candidate, ...]:
    scored = [
        _score(
            conn, exercise_id, slot, selected, template, accounting, assessment, injury,
            stress, stress_config, suitability, settings, volume_config, policy, rule, taxonomy,
            current_spinal, spinal_cap, last_id, week_start, week_end,
        )
        for exercise_id in candidates
    ]
    scored.sort(key=lambda item: _rank_key(item, candidates, stress, settings.tie_break))
    return tuple(scored)


def _alternatives(
    conn,
    candidates: Sequence[str],
    slot: templates.Slot,
    selected: Mapping[str, str],
    template: templates.SessionTemplate,
    accounting: RuleContext,
    assessment,
    injury,
    stress: Mapping[str, recent_stress.StressEntry],
    stress_config: recent_stress.StressConfig,
    suitability: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
    volume_config: Any,
    policy: resolver_policy.ResolverPolicy,
    rule,
    taxonomy: Mapping[str, Mapping[str, Any]],
    current_spinal: float,
    spinal_cap: float,
    last_id: str | None,
    chosen: str,
    week_start: str,
    week_end: str,
) -> tuple[str, ...]:
    if not candidates:
        return ()
    ranked = _rank(
        conn, candidates, slot, selected, template, accounting, assessment, injury,
        stress, stress_config, suitability, settings, volume_config, policy, rule, taxonomy,
        current_spinal, spinal_cap, last_id, week_start, week_end,
    )
    return tuple(item.exercise_id for item in ranked if item.exercise_id != chosen)[:5]


def _repair_required(
    template: templates.SessionTemplate,
    main_slot: templates.Slot | None,
    pools: Mapping[str, tuple[str, ...]],
    selected: dict[str, str],
    choices: dict[str, _SlotChoice],
    policy: resolver_policy.ResolverPolicy,
    suitability: Mapping[str, Mapping[str, Any]],
    vetoed: set[str],
    active_linked: set[str],
    taxonomy: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
    conn,
    accounting: RuleContext,
    assessment,
    injury,
    stress: Mapping[str, recent_stress.StressEntry],
    stress_config: recent_stress.StressConfig,
    volume_config: Any,
    rule,
    current_spinal: float,
    spinal_cap: float,
    session_type: str,
    week_start: str,
    week_end: str,
) -> tuple[dict[str, str], dict[str, _SlotChoice], list[str]]:
    required = {
        volume.volume_target_key(pattern)
        for pattern in policy.required_patterns[session_type]
    }
    warnings: list[str] = []
    for _attempt in range(len(template.slots) * 2 + 1):
        assigned = _assignment_pattern_sets(template, selected, taxonomy)
        missing = required - set(assigned)
        if not missing:
            return selected, choices, warnings
        changed = False
        for slot in template.slots:
            if _slot_role(slot, main_slot) != "accessory":
                continue
            permitted = _permitted_patterns(
                slot, "accessory", policy, main_slot, taxonomy
            )
            auto, _slot_suggestions = _classify_candidates(
                pools[slot.id], permitted, vetoed, active_linked, suitability, settings,
                taxonomy,
            )
            candidates = [
                exercise_id
                for exercise_id in auto
                if _pattern_key(exercise_id, taxonomy) in missing
            ]
            if not candidates:
                default_id = _default_id(slot)
                if (
                    default_id is not None
                    and default_id in pools[slot.id]
                    and _candidate_class(
                        default_id, permitted, vetoed, active_linked, suitability, settings,
                        taxonomy,
                    )
                    == AUTO
                    and _pattern_key(default_id, taxonomy) in missing
                ):
                    candidates = [default_id]
            if not candidates:
                continue
            partial = dict(selected)
            partial.pop(slot.id, None)
            ranked = _rank(
                conn, candidates, slot, partial, template, accounting, assessment, injury,
                stress, stress_config, suitability, settings, volume_config, policy, rule,
                taxonomy, current_spinal, spinal_cap, None, week_start, week_end,
            )
            chosen = ranked[0]
            selected[slot.id] = chosen.exercise_id
            choices[slot.id] = _SlotChoice(
                exercise_id=chosen.exercise_id,
                score=chosen.score,
                reasons=("required-pattern repair",) + chosen.reasons,
                alternatives=_alternatives(
                    conn, candidates, slot, partial, template, accounting, assessment,
                    injury, stress, stress_config, suitability, settings, volume_config,
                    policy, rule, taxonomy, current_spinal, spinal_cap, None,
                    chosen.exercise_id, week_start, week_end,
                ),
                pending_rating=_pending_rating(
                    chosen.exercise_id, suitability, settings
                ),
            )
            warnings.append(
                f"{slot.id}: required-pattern repair selected {chosen.exercise_id}"
            )
            changed = True
            break
        if not changed:
            raise GenerationError(
                f"{session_type}: required patterns not covered: {sorted(missing)}",
                session_type=session_type,
            )
    raise GenerationError(
        f"{session_type}: required-pattern repair did not settle",
        session_type=session_type,
    )


def _spinal_rule():
    document = rules_loader.load_document()
    return document.rule("PRG-SPINE-001")


def _weekly_spinal_cost(
    rule,
    accounting: RuleContext,
    week_start: str,
    extra: Sequence[tuple] = (),
) -> float:
    if rule is None:
        return 0.0
    costs = rules_registry.weekly_spinal_costs(rule, accounting, extra)
    return float(costs.get(rules_registry.iso_week(week_start), {}).get("cost", 0.0))


def _spinal_cap(context: RuleContext, rule) -> float:
    if context.spinal_cap is not None:
        return float(context.spinal_cap)
    return float(rule.params.get("cap", 6))


def _validate_spinal(
    rule,
    accounting: RuleContext,
    template: templates.SessionTemplate,
    selected: Mapping[str, str],
    for_date: str,
    cap: float,
    session_type: str,
) -> None:
    if rule is None:
        return
    sets_by_exercise: Counter[str] = Counter()
    for slot in template.slots:
        if slot.id in selected:
            sets_by_exercise[selected[slot.id]] += int(slot.sets)
    extras = [
        (f"generator:{for_date}", exercise_id, for_date, sets, None)
        for exercise_id, sets in sets_by_exercise.items()
    ]
    week = rules_registry.iso_week(for_date)
    costs = rules_registry.weekly_spinal_costs(rule, accounting, extras)
    total = float(costs.get(week, {}).get("cost", 0.0))
    if total > cap + 1e-9:
        raise GenerationError(
            f"{session_type}: projected weekly spinal cost {total:.2f} exceeds cap {cap:.2f}",
            session_type=session_type,
        )
