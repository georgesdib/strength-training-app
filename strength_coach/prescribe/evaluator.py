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

# Feasibility failures dominate; warnings are context, not hard failures.
ISSUE_PENALTY = 10.0
NON_EXECUTABLE_PENALTY = 2.0
SPINAL_OVER_PENALTY = 3.0
TIME_OVER_PENALTY = 1.0
VOLUME_ERROR_WEIGHT = 2.0
WARNING_PENALTY = 0.05


@dataclass(frozen=True)
class EvaluationInputs:
    """All build inputs shared by the evaluator and the eventual final build.

    The caller supplies conn, for_date, session_type and template; they are deliberately not
    part of this immutable contract. Keeping one object for the remaining arguments prevents
    the evaluator and production build from drifting apart.
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
    technique_throttle: bool = False
    technique_throttle_pattern: str | Sequence[str] | None = None
    deload_decision: Any = None
    drop_confirmed: bool = False
    top_set_requested: bool | None = None
    projected_items: tuple[Mapping[str, Any], ...] = ()
    projected_sessions: int = 0

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

    @property
    def feasible(self) -> bool:
        return (
            self.components.executable
            and self.components.issues == 0
            and not self.components.spinal_over_cap
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "assignment": dict(self.assignment),
            "score": round(self.score, 4),
            "feasible": self.feasible,
            "components": self.components.as_dict(),
            "warnings": list(self.prescription.warnings),
        }


def _pool_ids(pool: Sequence[str] | None) -> tuple[str, ...]:
    if pool is None or isinstance(pool, str) or not pool:
        return ()
    return tuple(str(value) for value in pool if str(value).strip())


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
        pool = _pool_ids(candidate_pools[slot.id])
        if not pool:
            raise ValueError(f"slot {slot.id!r}: eligible candidate pool is empty")
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
    """Lower is better; return score and transparent reason strings."""
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
    score += WARNING_PENALTY * components.warnings
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
    template = assignment_template(base_template, assignment, candidate_pools)
    build_inputs = inputs or EvaluationInputs()
    prescription = build_prescription(
        conn,
        for_date=for_date,
        session_type=base_template.session_type,
        template=template,
        **build_inputs.as_build_kwargs(),
    )
    components = _components(prescription)
    score, reasons = score_components(components)
    return AssignmentEvaluation(
        assignment=validated,
        score=score,
        components=components,
        prescription=prescription,
        reasons=reasons,
    )
