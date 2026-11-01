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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
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
    warnings: tuple[str, ...]
    policy_digest: str

    @property
    def exercise_ids(self) -> tuple[str, ...]:
        return tuple(slot.exercise_id for slot in self.slots)


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

    for index, slot in enumerate(template.slots):
        role = _slot_role(slot, main_slot)
        pool = pools[slot.id]
        permitted = _permitted_patterns(slot, role, policy, main_slot, taxonomy)
        default_id = _default_id(slot)
        last_id, sessions_since_change = _last_choice(history, index)
        rotation = settings.rotation_for(essential=slot.essential)
        dwell = settings.rotation_dwell(rotation)

        auto: list[str] = []
        for exercise_id in pool:
            if not _pattern_allowed(exercise_id, permitted, taxonomy):
                continue
            if exercise_id in vetoed or exercise_id in active_linked:
                continue
            rating = suitability.get(exercise_id)
            if rating is None:
                continue
            if not rating["can_do"]:
                continue
            if settings.will_do_blocks and not rating["will_do"]:
                continue
            if settings.feels_bad_blocks and rating["feels_bad"]:
                continue
            auto.append(exercise_id)

        default_allowed = (
            default_id is not None
            and default_id not in vetoed
            and default_id not in active_linked
            and _pattern_allowed(default_id, permitted, taxonomy)
        )
        if default_id is None:
            raise GenerationError(
                f"{session_type}/{slot.id}: no blueprint default exercise",
                session_type=session_type,
                slot_id=slot.id,
            )

        if slot.power:
            chosen = default_id
            reasons = ("fixed power slot",)
            score = 1.0
        elif last_id and last_id in auto and not _must_rotate(
            rotation, dwell, sessions_since_change
        ):
            chosen = last_id
            reasons = (
                f"kept last choice {last_id}",
                f"rotation {rotation:.2f}",
            )
            scored = _score(
                conn, chosen, slot, selected, template, accounting, assessment, injury,
                stress, stress_config, suitability, settings, volume_config, policy, taxonomy,
                current_spinal, spinal_cap, last_id, week_start, week_end,
            )
            score = scored.score
            reasons = scored.reasons
        elif auto:
            must_rotate = _must_rotate(rotation, dwell, sessions_since_change)
            candidates = [c for c in auto if not (must_rotate and c == last_id)]
            if not candidates:
                candidates = list(auto)
            ranked = _rank(
                conn, candidates, slot, selected, template, accounting, assessment,
                injury, stress, stress_config, suitability, settings, volume_config, policy,
                taxonomy,
                current_spinal, spinal_cap, last_id, week_start, week_end,
            )
            chosen = ranked[0].exercise_id
            score = ranked[0].score
            reasons = ranked[0].reasons
        elif default_allowed:
            chosen = default_id
            reasons = ("no auto-eligible candidate; kept blueprint default",)
            score = 0.0
            warnings.append(
                f"{slot.id}: no auto-eligible candidate; kept blueprint default {default_id}"
            )
        else:
            raise GenerationError(
                f"{session_type}/{slot.id}: no eligible candidate "
                f"(default {default_id!r} is vetoed or not permitted)",
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
                stress_config, suitability, settings, volume_config, policy, taxonomy, current_spinal,
                spinal_cap, last_id, chosen, week_start, week_end,
            ),
            pending_rating=suitability.get(chosen) is None,
        )

    selected, choices, repair_warnings = _repair_required(
        template, main_slot, pools, selected, choices, policy, suitability, vetoed,
        active_linked, taxonomy, settings, conn, accounting, assessment, injury, stress,
        stress_config, volume_config, current_spinal, spinal_cap, session_type, week_start,
        week_end,
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
        warnings=tuple(warnings),
        policy_digest=policy.digest,
    )


def available_session_types(
    conn,
    for_date: str,
    *,
    policy: resolver_policy.ResolverPolicy | None = None,
) -> dict[str, bool]:
    """Pool-aware availability for the four identities. Read-only."""
    policy = policy or resolver_policy.ResolverPolicy.load()
    catalogue = resolver_policy.load_candidate_catalogue(policy)
    taxonomy = exercises.taxonomy().entities
    injury = injury_signal.compute(conn, for_date)
    active_linked = {
        exercise_id
        for region in injury.regions
        if region.status == injury_signal.STATUS_ACTIVE
        for exercise_id in region.linked_exercises
    }
    out: dict[str, bool] = {}
    for session_type in templates.SESSION_TYPES:
        template = templates.SessionTemplate.load(session_type)
        main_slot = _main_slot(template, taxonomy)
        if main_slot is None:
            out[session_type] = True
            continue
        candidates = _candidate_ids(session_type, main_slot, policy, catalogue)
        permitted = _permitted_patterns(main_slot, "main", policy, main_slot, taxonomy)
        report = constraints_mod.evaluate(conn, list(candidates))
        vetoed = {exercise_id for exercise_id, _reason in report.vetoes}
        out[session_type] = any(
            exercise_id not in vetoed
            and exercise_id not in active_linked
            and _pattern_allowed(exercise_id, permitted, taxonomy)
            for exercise_id in candidates
        )
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


def _choice_history(conn, session_type: str, before_date: str) -> list[dict[int, str]]:
    """Recent session choices, newest first.

    Completed workouts are the performed record; prescriptions are the fallback for dates
    without a workout. A missing slot in a session is skipped rather than guessed.
    """
    rows = conn.execute(
        """
        SELECT for_date, plan_json FROM workout_session
         WHERE session_type = ? AND for_date < ? AND status = 'completed'
         ORDER BY for_date DESC, started_at DESC
         LIMIT 52
        """,
        (session_type, before_date),
    ).fetchall()
    out: list[dict[int, str]] = []
    for row in rows:
        try:
            plan = json.loads(row["plan_json"])
        except (TypeError, ValueError):
            continue
        items = plan.get("items") if isinstance(plan, Mapping) else None
        if not isinstance(items, list):
            continue
        mapping: dict[int, str] = {}
        for index, item in enumerate(items):
            if not isinstance(item, Mapping) or not item.get("exercise_id"):
                continue
            try:
                order = int(item.get("order_index", index))
            except (TypeError, ValueError):
                order = index
            mapping[order] = str(item["exercise_id"])
        if mapping:
            out.append(mapping)
    if out:
        return out

    rows = conn.execute(
        """
        SELECT p.prescription_id, p.for_date, pi.order_index, pi.exercise_id
          FROM prescription p
          JOIN prescription_item pi ON pi.prescription_id = p.prescription_id
         WHERE p.session_type = ? AND p.for_date < ?
         ORDER BY p.for_date DESC, p.created_at DESC, pi.order_index ASC
         LIMIT 520
        """,
        (session_type, before_date),
    ).fetchall()
    grouped: dict[str, dict[int, str]] = {}
    order: list[str] = []
    for row in rows:
        prescription = str(row["prescription_id"])
        if prescription not in grouped:
            grouped[prescription] = {}
            order.append(prescription)
        grouped[prescription][int(row["order_index"])] = str(row["exercise_id"])
    return [grouped[key] for key in order]


def _last_choice(history: Sequence[Mapping[int, str]], index: int) -> tuple[str | None, int]:
    if not history:
        return None, 0
    last = history[0].get(index)
    if last is None:
        return None, 0
    count = 0
    for entry in history:
        if entry.get(index) != last:
            break
        count += 1
    return last, count


def _must_rotate(rotation: float, dwell: int | None, sessions_since_change: int) -> bool:
    if rotation <= 0.0 or dwell is None:
        return False
    return sessions_since_change >= dwell

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


def _preference_component(
    exercise_id: str,
    suitability: Mapping[str, Mapping[str, Any]],
) -> float:
    rating = suitability.get(exercise_id)
    if rating is None:
        return 0.5
    if not rating["will_do"]:
        return 0.0
    if rating["feels_bad"]:
        return 0.25
    return 1.0


def _candidate_spinal(
    exercise_id: str, taxonomy: Mapping[str, Mapping[str, Any]]
) -> float:
    entity = taxonomy.get(exercise_id, {})
    if not entity.get("high_fatigue_spinal", False):
        return 0.0
    return float(entity.get("spinal_cost") or 0.0)


def _spinal_component(
    current_cost: float,
    exercise_id: str,
    taxonomy: Mapping[str, Mapping[str, Any]],
    cap: float,
) -> float:
    if cap <= 0:
        return 1.0
    total = current_cost + _candidate_spinal(exercise_id, taxonomy)
    return _clamp(1.0 - total / cap)


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
    spinal = _spinal_component(current_spinal, exercise_id, taxonomy, spinal_cap)
    preference = _preference_component(exercise_id, suitability)
    partial = dict(selected)
    partial[slot.id] = exercise_id
    assigned = _assignment_pattern_sets(template, partial, taxonomy)
    completed = _completed_pattern_sets(accounting, week_start, week_end, taxonomy)
    coverage = _coverage_component(completed, assigned, volume_config, settings)
    redundancy = _redundancy_penalty(template, selected, slot, exercise_id, policy, taxonomy)
    rotation = 1.0 if last_id and exercise_id != last_id else 0.5
    weighted = sum(
        float(settings.weights.get(key, 0.0)) * value
        for key, value in (
            ("readiness", readiness),
            ("fatigue", stress_value),
            ("spinal", spinal),
            ("injury", 1.0),
            ("rotation", rotation),
            ("preference", preference),
        )
    )
    factor = COVERAGE_FACTORS.get(settings.coverage_priority, 0.15)
    score = _clamp(weighted + factor * (coverage - 0.5) - redundancy)
    reasons = (
        f"readiness {readiness:.2f}",
        f"stress {stress_value:.2f}",
        f"spinal {spinal:.2f}",
        f"coverage {coverage:.2f}",
        f"preference {preference:.2f}",
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
            stress, stress_config, suitability, settings, volume_config, policy, taxonomy,
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
        stress, stress_config, suitability, settings, volume_config, policy, taxonomy,
        current_spinal, spinal_cap, last_id, week_start, week_end,
    )
    return tuple(item.exercise_id for item in ranked if item.exercise_id != chosen)[:5]


def _auto_candidates(
    pool: Sequence[str],
    permitted: set[str],
    vetoed: set[str],
    active_linked: set[str],
    suitability: Mapping[str, Mapping[str, Any]],
    settings: ResolverSettings,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    auto: list[str] = []
    unrated: list[str] = []
    for exercise_id in pool:
        if not _pattern_allowed(exercise_id, permitted, taxonomy):
            continue
        if exercise_id in vetoed or exercise_id in active_linked:
            continue
        rating = suitability.get(exercise_id)
        if rating is None:
            unrated.append(exercise_id)
            continue
        if not rating["can_do"]:
            continue
        if settings.will_do_blocks and not rating["will_do"]:
            continue
        if settings.feels_bad_blocks and rating["feels_bad"]:
            continue
        auto.append(exercise_id)
    return auto, unrated


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
            auto, _unrated = _auto_candidates(
                pools[slot.id], permitted, vetoed, active_linked, suitability, settings,
                taxonomy,
            )
            default_id = _default_id(slot)
            fallback = (
                [default_id]
                if default_id is not None
                and default_id not in vetoed
                and default_id not in active_linked
                and _pattern_allowed(default_id, permitted, taxonomy)
                else []
            )
            candidates = [
                exercise_id
                for exercise_id in (auto or fallback)
                if _pattern_key(exercise_id, taxonomy) in missing
            ]
            if not candidates:
                continue
            partial = dict(selected)
            partial.pop(slot.id, None)
            ranked = _rank(
                conn, candidates, slot, partial, template, accounting, assessment, injury,
                stress, stress_config, suitability, settings, volume_config, policy,
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
                    policy, taxonomy, current_spinal, spinal_cap, None, chosen.exercise_id,
                    week_start, week_end,
                ),
                pending_rating=suitability.get(chosen.exercise_id) is None,
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


def _weekly_spinal_cost(rule, accounting: RuleContext, week_start: str) -> float:
    if rule is None:
        return 0.0
    costs = rules_registry.weekly_spinal_costs(rule, accounting)
    return float(costs.get(week_start, {}).get("cost", 0.0))


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
    extras = [
        (f"generator:{for_date}", selected[slot.id], for_date, slot.sets, None)
        for slot in template.slots
        if slot.id in selected
    ]
    week = _week_bounds(for_date)[0]
    costs = rules_registry.weekly_spinal_costs(rule, accounting, extras)
    total = float(costs.get(week, {}).get("cost", 0.0))
    if total > cap + 1e-9:
        raise GenerationError(
            f"{session_type}: projected weekly spinal cost {total:.2f} exceeds cap {cap:.2f}",
            session_type=session_type,
        )
