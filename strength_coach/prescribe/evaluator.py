"""Read-only evaluation of one complete, validated exercise assignment.

Step 4 uses the existing prescription pipeline once per complete assignment. This module is the
contract for that evaluation: it accepts exactly one eligible exercise for every slot, builds a
generated template, runs the normal engine read-only, and returns deterministic post-budget
components. It does not search assignments, choose a winner, persist anything, or wire the
generator into the engine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from strength_coach.prescribe import build_prescription, templates
from strength_coach.prescribe.models import Prescription

# Heuristic ordering weights, not calibrated utility. Hard feasibility is separate in
# AssignmentEvaluation.feasible; these terms only rank otherwise valid candidates.
# Unknown loads intentionally also incur the non-executable penalty because an unknown load is
# a cause of non-executability; the two reasons are kept visible in the diagnostic list.
ISSUE_PENALTY = 10.0
NON_EXECUTABLE_PENALTY = 2.0
SPINAL_OVER_PENALTY = 3.0
TIME_OVER_PENALTY = 1.0
VOLUME_ERROR_WEIGHT = 2.0
WARNING_PENALTY = 0.05
SESSION_REPLACED_PENALTY = 5.0
STRUCTURAL_PENALTY = 10.0


@dataclass(frozen=True)
class EvaluationInputs:
    """All build inputs shared by the evaluator and the eventual final build.

    The caller supplies conn, for_date, session_type and template; they are deliberately not
    part of this immutable contract. Keeping one object for the remaining arguments prevents
    the evaluator and production build from drifting apart. Selection fields exist only for
    signature parity; validate_for_resolver rejects them because resolver evaluation must not
    replace the assigned exercises.
    """

    document: Any = None
    thresholds: Any = None
    undulation: Any = None
    history: Any = None
    vbt: Any = None
    readiness_config: Any = None
    apply_selection: bool = False
    selection_chooser: Callable[..., Any] | None = None
    selection_confirmed: bool = False
    minimum_session: bool = False
    minimum_target_minutes: int | None = None
    minimum_include_main: bool = False
    minimum_accessories_only: bool = False
    resolver_policy: Any = None
    technique_throttle: bool = False
    technique_throttle_pattern: str | Sequence[str] | None = None
    deload_decision: Any = None
    drop_confirmed: bool = False
    top_set_requested: bool | None = None
    projected_items: tuple[Mapping[str, Any], ...] = ()
    projected_sessions: int = 0

    def validate_for_resolver(self) -> None:
        """Reject inputs that could replace the assigned exercise selection."""
        if self.apply_selection or self.selection_chooser is not None or self.selection_confirmed:
            raise ValueError(
                "resolver evaluation cannot apply selection; "
                "apply_selection/selection_chooser/selection_confirmed must be off"
            )

    def as_build_kwargs(self) -> dict[str, Any]:
        """Arguments accepted by build_prescription, excluding conn/date/type/template."""
        return {
            "document": self.document,
            "thresholds": self.thresholds,
            "undulation": self.undulation,
            "history": self.history,
            "vbt": self.vbt,
            "readiness_config": self.readiness_config,
            "apply_selection": self.apply_selection,
            "selection_chooser": self.selection_chooser,
            "selection_confirmed": self.selection_confirmed,
            "minimum_session": self.minimum_session,
            "minimum_target_minutes": self.minimum_target_minutes,
            "minimum_include_main": self.minimum_include_main,
            "minimum_accessories_only": self.minimum_accessories_only,
            "technique_throttle": self.technique_throttle,
            "technique_throttle_pattern": self.technique_throttle_pattern,
            "deload_decision": self.deload_decision,
            "drop_confirmed": self.drop_confirmed,
            "top_set_requested": self.top_set_requested,
            "projected_items": self.projected_items,
            "projected_sessions": self.projected_sessions,
        }


@dataclass(frozen=True)
class EvaluationComponents:
    """Deterministic post-pipeline terms used by the assignment score."""

    executable: bool
    issues: int
    unknown_loads: int
    volume_error: float
    spinal_over_cap: bool
    # Diagnostic only; headroom does not contribute to score or feasibility.
    spinal_headroom: float
    time_over_planned: bool
    time_over_minutes: float
    warnings: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "issues": self.issues,
            "unknown_loads": self.unknown_loads,
            "volume_error": round(self.volume_error, 4),
            "spinal_over_cap": self.spinal_over_cap,
            "spinal_headroom": round(self.spinal_headroom, 4),
            "time_over_planned": self.time_over_planned,
            "time_over_minutes": round(self.time_over_minutes, 4),
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class AssignmentEvaluation:
    """One complete assignment and the pipeline outcome it produced."""

    assignment: tuple[tuple[str, str], ...]
    score: float
    components: EvaluationComponents
    prescription: Prescription
    reasons: tuple[str, ...]
    assignment_preserved: bool = True
    session_replaced: bool = False
    replacement_reason: str | None = None
    structural_violations: tuple[str, ...] = ()

    @property
    def feasible(self) -> bool:
        """Hard feasibility only: executable, no issues, spinal cap, exact assignment and
        distinct-slot required-pattern coverage.

        Time overruns, volume-target error and warnings are soft objectives, not feasibility.
        """
        return (
            self.components.executable
            and self.components.issues == 0
            and not self.components.spinal_over_cap
            and self.assignment_preserved
            and not self.session_replaced
            and not self.structural_violations
        )

    @property
    def infeasibility_reason(self) -> str | None:
        if self.session_replaced:
            return self.replacement_reason or "session/template was replaced"
        if not self.assignment_preserved:
            return "prescription exercises differ from the assignment"
        if self.structural_violations:
            return self.structural_violations[0]
        if not self.components.executable:
            return "prescription is not executable"
        if self.components.issues:
            return f"{self.components.issues} validation/constraint issue(s)"
        if self.components.spinal_over_cap:
            return "weekly spinal cap exceeded"
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "assignment": dict(self.assignment),
            "score": round(self.score, 4),
            "feasible": self.feasible,
            "infeasibility_reason": self.infeasibility_reason,
            "reasons": list(self.reasons),
            "components": self.components.as_dict(),
            "issues": list(self.prescription.issues),
            "unknown_loads": [
                item.exercise_id
                for item in self.prescription.items
                if item.unknown_load_reason is not None
            ],
            "assignment_preserved": self.assignment_preserved,
            "session_replaced": self.session_replaced,
            "replacement_reason": self.replacement_reason,
            "structural_violations": list(self.structural_violations),
            "warnings": list(self.prescription.warnings),
        }


def candidate_ids(pool: Sequence[str] | None, *, where: str) -> tuple[str, ...]:
    """Strictly validate a candidate pool; never coerce or hide malformed ids."""
    if pool is None or isinstance(pool, str) or not isinstance(pool, Sequence):
        raise ValueError(f"{where}: candidate pool must be a sequence of exercise ids")
    ordered: list[str] = []
    seen: set[str] = set()
    for value in pool:
        if not isinstance(value, str):
            raise ValueError(
                f"{where}: candidate id must be a string, got {type(value).__name__}"
            )
        if not value.strip():
            raise ValueError(f"{where}: candidate id must be a non-empty string")
        if value in seen:
            raise ValueError(f"{where}: duplicate candidate id {value!r}")
        seen.add(value)
        ordered.append(value)
    if not ordered:
        raise ValueError(f"{where}: candidate pool is empty")
    return tuple(ordered)


def validate_assignment(
    base: templates.SessionTemplate,
    assignment: Mapping[str, str],
    candidate_pools: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, str], ...]:
    """Return the assignment in template slot order or raise a field-level error.

    Exact coverage is required: one non-empty exercise per slot, no missing or unknown slots,
    and every selection must appear in that slot's explicit eligible pool. Blueprint defaults
    are never substituted here.
    """
    expected = tuple(slot.id for slot in base.slots)
    expected_set = set(expected)
    assignment_keys = set(assignment)
    missing = sorted(expected_set - assignment_keys)
    unknown = sorted(assignment_keys - expected_set)
    if missing or unknown:
        raise ValueError(
            "assignment must cover every slot exactly; "
            f"missing {missing}, unknown {unknown}"
        )

    pool_keys = set(candidate_pools)
    missing_pools = sorted(expected_set - pool_keys)
    unknown_pools = sorted(pool_keys - expected_set)
    if missing_pools or unknown_pools:
        raise ValueError(
            "candidate pools must cover every slot exactly; "
            f"missing {missing_pools}, unknown {unknown_pools}"
        )

    validated: list[tuple[str, str]] = []
    for slot in base.slots:
        exercise_id = assignment[slot.id]
        if not isinstance(exercise_id, str) or not exercise_id.strip():
            raise ValueError(f"slot {slot.id!r}: exercise id must be a non-empty string")
        pool = candidate_ids(
            candidate_pools[slot.id], where=f"slot {slot.id!r}"
        )
        if exercise_id not in pool:
            raise ValueError(
                f"slot {slot.id!r}: {exercise_id!r} is not in the eligible candidate pool"
            )
        validated.append((slot.id, exercise_id))
    return tuple(validated)


def assignment_template(
    base: templates.SessionTemplate,
    assignment: Mapping[str, str],
    candidate_pools: Mapping[str, Sequence[str]],
) -> templates.SessionTemplate:
    """Return a concrete generated template from a complete validated assignment."""
    validated = validate_assignment(base, assignment, candidate_pools)
    selected = dict(validated)
    main = next(
        (
            slot
            for slot in base.slots
            if base.primary_exercise in slot.exercises
        ),
        None,
    )
    return replace(
        base,
        slots=tuple(
            replace(slot, exercise=selected[slot.id], variants=())
            for slot in base.slots
        ),
        primary_exercise=(
            selected[main.id] if main is not None else base.primary_exercise
        ),
    )


def _volume_error(prescription: Prescription) -> float:
    panel = prescription.notes.get("volume_panel") or {}
    groups = panel.get("groups") or {}
    error = 0.0
    total = 0.0
    for group in groups.values():
        target = float(group.get("target") or 0.0)
        if target <= 0:
            continue
        after = float(group.get("after") or 0.0)
        error += abs(after - target)
        total += target
    return error / total if total > 0 else 0.0


def _components(prescription: Prescription) -> EvaluationComponents:
    spinal = prescription.notes.get("spinal_cap") or {}
    time = prescription.notes.get("session_time") or {}
    estimated = time.get("estimated_minutes")
    planned = time.get("planned_minutes")
    over_minutes = 0.0
    if estimated is not None and planned is not None:
        over_minutes = max(0.0, float(estimated) - float(planned))
    return EvaluationComponents(
        executable=bool(prescription.executable),
        issues=len(prescription.issues),
        unknown_loads=sum(
            1 for item in prescription.items if item.unknown_load_reason is not None
        ),
        volume_error=_volume_error(prescription),
        spinal_over_cap=bool(spinal.get("over_cap")),
        spinal_headroom=float(spinal.get("headroom") or 0.0),
        time_over_planned=bool(time.get("over_planned")) or over_minutes > 0,
        time_over_minutes=over_minutes,
        warnings=len(prescription.warnings),
    )


def score_components(components: EvaluationComponents) -> tuple[float, tuple[str, ...]]:
    """Lower is better; return heuristic score and transparent reason strings.

    An unknown load is also non-executable, so it intentionally receives both the generic
    executable penalty and the unknown-load penalty. These weights order candidates; they are not
    calibrated utilities, and soft terms do not change AssignmentEvaluation.feasible.
    """
    score = 0.0
    reasons: list[str] = []
    if components.issues:
        score += ISSUE_PENALTY * components.issues
        reasons.append(f"{components.issues} validation issue(s)")
    if not components.executable:
        score += NON_EXECUTABLE_PENALTY
        reasons.append("not executable")
    if components.unknown_loads:
        penalty = NON_EXECUTABLE_PENALTY * components.unknown_loads
        score += penalty
        reasons.append(f"{components.unknown_loads} unknown load(s)")
    if components.spinal_over_cap:
        score += SPINAL_OVER_PENALTY
        reasons.append("weekly spinal cap exceeded")
    if components.time_over_planned:
        penalty = TIME_OVER_PENALTY + components.time_over_minutes / 30.0
        score += penalty
        reasons.append("session time over the planned target")
    score += VOLUME_ERROR_WEIGHT * components.volume_error
    if components.volume_error:
        reasons.append(f"volume target error {components.volume_error:.2f}")
    if components.warnings:
        score += WARNING_PENALTY * components.warnings
        reasons.append(f"{components.warnings} warning(s)")
    return round(score, 6), tuple(reasons)


def evaluate_assignment(
    conn,
    *,
    for_date: str,
    base_template: templates.SessionTemplate,
    assignment: Mapping[str, str],
    candidate_pools: Mapping[str, Sequence[str]],
    inputs: EvaluationInputs | None = None,
) -> AssignmentEvaluation:
    """Run one complete, validated assignment through the real engine read-only.

    The normal build applies readiness, continuity, deload, spinal, volume, time and validation.
    No engine function in this path writes to the store; the caller may use the returned
    prescription for preview/selection but must not persist it from the evaluator.
    """
    validated = validate_assignment(base_template, assignment, candidate_pools)
    build_inputs = inputs or EvaluationInputs()
    build_inputs.validate_for_resolver()
    template = assignment_template(base_template, assignment, candidate_pools)
    from strength_coach.prescribe import generator, resolver_policy
    from strength_coach.utils import exercises

    structural_violations = generator.required_pattern_violations(
        template,
        dict(validated),
        build_inputs.resolver_policy or resolver_policy.ResolverPolicy.load(),
        exercises.taxonomy().entities,
    )
    prescription = build_prescription(
        conn,
        for_date=for_date,
        session_type=base_template.session_type,
        template=template,
        use_resolver=False,
        **build_inputs.as_build_kwargs(),
    )
    components = _components(prescription)
    score, reasons = score_components(components)
    actual = tuple(item.exercise_id for item in prescription.items)
    expected = tuple(exercise_id for _slot_id, exercise_id in validated)
    assignment_preserved = actual == expected
    session_replaced = prescription.session_type != base_template.session_type
    replacement_reason = None
    if session_replaced:
        replacement_reason = (
            f"prescription session type {prescription.session_type!r} replaced "
            f"template {base_template.session_type!r}"
        )
        score += SESSION_REPLACED_PENALTY
        reasons += ("session/template was replaced",)
    elif not assignment_preserved:
        replacement_reason = (
            "prescription exercise list differs from the validated assignment "
            "(constraint omission or template substitution)"
        )
        score += SESSION_REPLACED_PENALTY
        reasons += ("assignment exercises were not preserved",)
    if structural_violations:
        score += STRUCTURAL_PENALTY
        reasons += structural_violations
    return AssignmentEvaluation(
        assignment=validated,
        score=round(score, 6),
        components=components,
        prescription=prescription,
        reasons=reasons,
        assignment_preserved=assignment_preserved,
        session_replaced=session_replaced,
        replacement_reason=replacement_reason,
        structural_violations=structural_violations,
    )
