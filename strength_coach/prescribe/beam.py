"""Deterministic bounded beam over complete exercise assignments.

Step 4B is the search layer only. Candidate pools are supplied by the caller (later, the
generator); this module keeps partial assignments by a cheap deterministic candidate-rank order,
then runs the real read-only evaluator only on the final beam. The final build remains Step 4C.

This is not a globally optimal search and does not score partial prescriptions. Its partial
pruning is candidate rank order; only the final complete assignments receive the real pipeline
score.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from strength_coach.prescribe.evaluator import (
    AssignmentEvaluation,
    EvaluationInputs,
    evaluate_assignment,
)

DEFAULT_BEAM_WIDTH = 4
DEFAULT_CANDIDATE_CAP = 6
DEFAULT_FULL_EVALUATION_BUDGET = DEFAULT_BEAM_WIDTH


class BeamError(ValueError):
    """The beam cannot form a complete assignment from the supplied pools."""


class BeamEligibilityError(BeamError):
    """A field-level pool failure; no blueprint fallback is allowed."""

    def __init__(self, slot_id: str, message: str) -> None:
        self.slot_id = slot_id
        super().__init__(f"{slot_id}: {message}")


@dataclass(frozen=True)
class BeamConfig:
    width: int = DEFAULT_BEAM_WIDTH
    max_candidates_per_slot: int = DEFAULT_CANDIDATE_CAP
    max_full_evaluations: int = DEFAULT_FULL_EVALUATION_BUDGET

    def __post_init__(self) -> None:
        if self.width < 1:
            raise ValueError("beam width must be positive")
        if self.max_candidates_per_slot < 1:
            raise ValueError("max_candidates_per_slot must be positive")
        if self.max_full_evaluations < 1:
            raise ValueError("max_full_evaluations must be positive")


@dataclass(frozen=True)
class BeamResult:
    """Search outcome.

    best is None when no evaluated assignment is feasible; diagnostic then preserves the best
    scored result for the caller, but it is never a successful generated session.
    """

    best: AssignmentEvaluation | None
    diagnostic: AssignmentEvaluation | None
    evaluated: tuple[AssignmentEvaluation, ...]
    pruned: int
    truncated: bool
    candidate_cap_applied: bool
    evaluation_budget_applied: bool
    reason: str


@dataclass(frozen=True)
class _Partial:
    assignment: tuple[tuple[str, str], ...]
    order_cost: int


def _slot_candidates(
    slot,
    candidates: Mapping[str, Sequence[str]],
    cap: int,
) -> tuple[tuple[str, ...], bool]:
    raw = candidates.get(slot.id)
    if raw is None or isinstance(raw, str) or not raw:
        raise BeamEligibilityError(slot.id, "eligible candidate pool is missing or empty")
    unique: list[str] = []
    seen: set[str] = set()
    for exercise_id in raw:
        value = str(exercise_id)
        if not value.strip():
            raise BeamEligibilityError(slot.id, "candidate contains an empty exercise id")
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    if not unique:
        raise BeamEligibilityError(slot.id, "eligible candidate pool is empty")
    return tuple(unique[:cap]), len(unique) > cap


def search(
    conn,
    *,
    for_date: str,
    base_template,
    candidates: Mapping[str, Sequence[str]],
    config: BeamConfig | None = None,
    inputs: EvaluationInputs | None = None,
    evaluator: Callable[..., AssignmentEvaluation] = evaluate_assignment,
    evaluator_kwargs: Mapping[str, Any] | None = None,
) -> BeamResult:
    """Search complete assignments and evaluate the final beam only.

    The cheap partial order is the sum of each candidate's position in its supplied slot pool.
    Callers must therefore pass candidates in their preferred deterministic order. The full
    evaluator sees only complete assignments and makes the final choice by post-pipeline score.
    No wall-clock, random element, or blueprint fallback is used.
    """
    cfg = config or BeamConfig()
    working = evaluator_kwargs or {}
    known = {slot.id for slot in base_template.slots}
    if not known:
        raise BeamError("template has no slots")
    unknown = set(candidates) - known
    if unknown:
        raise ValueError(f"unknown slot(s) in candidates: {sorted(unknown)}")

    beam: list[_Partial] = [_Partial((), 0)]
    pruned = 0
    candidate_cap_applied = False
    for slot in base_template.slots:
        slot_candidates, capped = _slot_candidates(
            slot, candidates, cfg.max_candidates_per_slot
        )
        candidate_cap_applied = candidate_cap_applied or capped
        expanded: list[_Partial] = []
        for partial in beam:
            for rank, exercise_id in enumerate(slot_candidates):
                expanded.append(
                    _Partial(
                        partial.assignment + ((slot.id, exercise_id),),
                        partial.order_cost + rank,
                    )
                )
        expanded.sort(key=lambda item: (item.order_cost, item.assignment))
        pruned += max(0, len(expanded) - cfg.width)
        beam = expanded[: cfg.width]

    evaluation_budget_applied = len(beam) > cfg.max_full_evaluations
    final = beam[: cfg.max_full_evaluations]
    evaluated: list[AssignmentEvaluation] = []
    for partial in final:
        evaluated.append(
            evaluator(
                conn,
                for_date=for_date,
                base_template=base_template,
                assignment=dict(partial.assignment),
                candidate_pools=candidates,
                inputs=inputs,
                **working,
            )
        )

    if not evaluated:
        raise BeamError("beam produced no complete assignment to evaluate")

    feasible = [result for result in evaluated if result.feasible]
    best = (
        min(feasible, key=lambda result: (result.score, result.assignment))
        if feasible
        else None
    )
    diagnostic = min(evaluated, key=lambda result: (result.score, result.assignment))
    truncated = candidate_cap_applied or evaluation_budget_applied

    if best is None:
        reason = (
            f"no feasible assignment among {len(evaluated)} evaluated; "
            f"best diagnostic score {diagnostic.score:.4f}"
        )
    else:
        reason = f"selected a feasible assignment from {len(evaluated)} evaluated"
    if candidate_cap_applied:
        reason += "; candidate pools were deterministically capped"
    if evaluation_budget_applied:
        reason += f"; full-evaluation budget capped at {cfg.max_full_evaluations}"

    return BeamResult(
        best=best,
        diagnostic=diagnostic,
        evaluated=tuple(evaluated),
        pruned=pruned,
        truncated=truncated,
        candidate_cap_applied=candidate_cap_applied,
        evaluation_budget_applied=evaluation_budget_applied,
        reason=reason,
    )
