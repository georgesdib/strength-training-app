"""Deterministic bounded beam over complete exercise assignments.

Step 4B is the search layer only. Candidate pools are supplied by the caller (later, the
generator); this module keeps the best partial assignments by a cheap deterministic order cost,
then runs the real read-only evaluator only on the final beam. The final build remains Step 4C.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from strength_coach.prescribe.evaluator import (
    AssignmentEvaluation,
    evaluate_assignment,
)

DEFAULT_BEAM_WIDTH = 4
DEFAULT_CANDIDATE_CAP = 6
DEFAULT_FULL_EVALUATION_BUDGET = 16


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
    best: AssignmentEvaluation | None
    evaluated: tuple[AssignmentEvaluation, ...]
    pruned: int
    truncated: bool
    fallback_assignment: tuple[tuple[str, str], ...]
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
    if raw is None or not raw:
        default = slot.exercises[0] if slot.exercises else None
        return ((default,) if default is not None else ()), True
    ordered: list[str] = []
    seen: set[str] = set()
    for exercise_id in raw:
        value = str(exercise_id)
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
        if len(ordered) >= cap:
            break
    return tuple(ordered), len(raw) > len(ordered)


def _default_assignment(base_template, candidates: Mapping[str, Sequence[str]]) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for slot in base_template.slots:
        raw = candidates.get(slot.id) or ()
        exercise = str(raw[0]) if raw else (slot.exercises[0] if slot.exercises else None)
        if exercise is None:
            raise ValueError(f"slot {slot.id!r} has no candidate or blueprint exercise")
        out.append((slot.id, exercise))
    return tuple(out)


def search(
    conn,
    *,
    for_date: str,
    base_template,
    candidates: Mapping[str, Sequence[str]],
    config: BeamConfig | None = None,
    top_set_requested: bool | None = None,
    evaluator: Callable[..., AssignmentEvaluation] = evaluate_assignment,
    evaluator_kwargs: Mapping[str, Any] | None = None,
) -> BeamResult:
    """Search complete assignments and evaluate the final beam only.

    The cheap partial order is the sum of each candidate's position in its supplied slot pool.
    Callers must therefore pass candidates in their preferred deterministic order. The full
    evaluator sees only complete assignments and makes the final choice by post-pipeline score.
    No wall-clock or random element is used.
    """
    cfg = config or BeamConfig()
    working = evaluator_kwargs or {}
    known = {slot.id for slot in base_template.slots}
    unknown = set(candidates) - known
    if unknown:
        raise ValueError(f"unknown slot(s) in candidates: {sorted(unknown)}")

    beam: list[_Partial] = [_Partial((), 0)]
    fallback_used = False
    pruned = 0
    for slot in base_template.slots:
        slot_candidates, truncated_slot = _slot_candidates(
            slot, candidates, cfg.max_candidates_per_slot
        )
        if not slot_candidates:
            raise ValueError(f"slot {slot.id!r} has no candidate")
        fallback_used = fallback_used or truncated_slot
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

    if not beam:
        # This is only reachable if the template has no slots; complete deterministically.
        assignment = _default_assignment(base_template, candidates)
        evaluation = evaluator(
            conn,
            for_date=for_date,
            base_template=base_template,
            assignment=dict(assignment),
            top_set_requested=top_set_requested,
            **working,
        )
        return BeamResult(
            best=evaluation,
            evaluated=(evaluation,),
            pruned=pruned,
            truncated=False,
            fallback_assignment=assignment,
            reason="empty template: evaluated the deterministic default",
        )

    final = beam
    truncated = len(final) > cfg.max_full_evaluations
    if truncated:
        final = final[: cfg.max_full_evaluations]
    evaluated: list[AssignmentEvaluation] = []
    for partial in final:
        evaluated.append(
            evaluator(
                conn,
                for_date=for_date,
                base_template=base_template,
                assignment=dict(partial.assignment),
                top_set_requested=top_set_requested,
                **working,
            )
        )
    best = min(
        evaluated,
        key=lambda result: (
            0 if result.feasible else 1,
            result.score,
            result.assignment,
        ),
    )
    reason = (
        f"evaluated {len(evaluated)} of {len(final)} final beam assignment(s)"
        if not truncated
        else f"full-evaluation budget capped at {cfg.max_full_evaluations}"
    )
    if fallback_used:
        reason += "; candidate pool or cap used a deterministic fallback"
    return BeamResult(
        best=best,
        evaluated=tuple(evaluated),
        pruned=pruned,
        truncated=truncated,
        fallback_assignment=(
            tuple(best.assignment) if best is not None
            else _default_assignment(base_template, candidates)
        ),
        reason=reason,
    )
