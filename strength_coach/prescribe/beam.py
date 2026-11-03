"""Deterministic bounded beam over complete exercise assignments.

Step 4B is the search layer only. Candidate pools are supplied by the caller (later, the
generator); this module keeps partial assignments by a cheap deterministic candidate-rank order,
then runs the real read-only evaluator only on the final beam. The final build remains Step 4C.

This is not a globally optimal search and does not score partial prescriptions. When structural
metadata is supplied, partial expansion tracks required-pattern coverage and prunes only branches
that can no longer satisfy the policy; beam-width pruning then applies to the structurally viable
set. Only final complete assignments receive the real pipeline score.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from strength_coach.prescribe.evaluator import (
    AssignmentEvaluation,
    EvaluationInputs,
    candidate_ids,
    evaluate_assignment,
)
from strength_coach.prescribe.generator import patterns_assignable

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
    scored result for the caller, but it is never a successful generated session. truncated
    means a candidate cap or the full-evaluation budget removed options; partial beam pruning is
    counted separately by pruned, and structural dead ends by structural_pruned. Candidate cap
    selection retains candidates needed for required-pattern coverage before other truncation.
    """

    best: AssignmentEvaluation | None
    diagnostic: AssignmentEvaluation | None
    evaluated: tuple[AssignmentEvaluation, ...]
    pruned: int
    truncated: bool
    candidate_cap_applied: bool
    evaluation_budget_applied: bool
    candidate_ids_removed: int
    structural_pruned: int
    final_assignments_pruned: int
    exhaustive: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "best": self.best.as_dict() if self.best is not None else None,
            "diagnostic": (
                self.diagnostic.as_dict() if self.diagnostic is not None else None
            ),
            "evaluated": len(self.evaluated),
            "pruned": self.pruned,
            "candidate_ids_removed": self.candidate_ids_removed,
            "structural_pruned": self.structural_pruned,
            "final_assignments_pruned": self.final_assignments_pruned,
            "candidate_cap_applied": self.candidate_cap_applied,
            "evaluation_budget_applied": self.evaluation_budget_applied,
            "truncated": self.truncated,
            "exhaustive": self.exhaustive,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BeamStructure:
    """Required-pattern metadata used for partial-assignment feasibility.

    patterns_by_slot maps each slot to candidate -> materialised pattern key. It is supplied by
    the generator so the beam shares the same structural vocabulary as candidate-pool feasibility.
    """

    required_patterns: tuple[str, ...]
    patterns_by_slot: Mapping[str, Mapping[str, str | None]]


@dataclass(frozen=True)
class _Partial:
    assignment: tuple[tuple[str, str], ...]
    order_cost: int
    ranks: tuple[int, ...]
    covered: frozenset[int] = frozenset()


def _slot_candidates(
    slot,
    candidates: Mapping[str, Sequence[str]],
    cap: int,
    structure: BeamStructure | None,
) -> tuple[tuple[str, ...], int, bool]:
    raw = candidates.get(slot.id)
    if raw is None:
        raise BeamEligibilityError(slot.id, "eligible candidate pool is missing")
    try:
        unique = candidate_ids(raw, where=f"slot {slot.id!r}")
    except ValueError as exc:
        raise BeamEligibilityError(slot.id, str(exc)) from exc

    selected_indices = set(range(min(cap, len(unique))))
    if structure is not None:
        patterns = structure.patterns_by_slot.get(slot.id, {})
        for pattern in structure.required_patterns:
            if any(patterns.get(unique[index]) == pattern for index in selected_indices):
                continue
            for index, exercise_id in enumerate(unique):
                if patterns.get(exercise_id) == pattern:
                    selected_indices.add(index)
                    break
    selected = [unique[index] for index in sorted(selected_indices)]
    return (
        tuple(selected),
        max(0, len(unique) - len(selected)),
        len(unique) > cap,
    )


def search(
    conn,
    *,
    for_date: str,
    base_template,
    candidates: Mapping[str, Sequence[str]],
    config: BeamConfig | None = None,
    structure: BeamStructure | None = None,
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

    required = structure.required_patterns if structure is not None else ()
    slot_specs = []
    candidate_ids_removed = 0
    candidate_cap_applied = False
    for slot in base_template.slots:
        slot_candidates, removed, capped = _slot_candidates(
            slot, candidates, cfg.max_candidates_per_slot, structure
        )
        slot_specs.append((slot, slot_candidates))
        candidate_ids_removed += removed
        candidate_cap_applied = candidate_cap_applied or capped

    capped_patterns: dict[str, set[str]] = {}
    capped_lookup: dict[str, dict[str, str | None]] = {}
    if structure is not None:
        for slot, slot_candidates in slot_specs:
            candidate_patterns = structure.patterns_by_slot.get(slot.id, {})
            capped_lookup[slot.id] = {
                exercise_id: candidate_patterns.get(exercise_id)
                for exercise_id in slot_candidates
            }
            capped_patterns[slot.id] = {
                pattern
                for pattern in capped_lookup[slot.id].values()
                if pattern is not None
            }
        if not patterns_assignable(required, capped_patterns):
            raise BeamError(
                "candidate pools cannot satisfy required patterns after truncation"
            )

    beam: list[_Partial] = [_Partial((), 0, (), frozenset())]
    pruned = 0
    structural_pruned = 0
    for position, (slot, slot_candidates) in enumerate(slot_specs):
        expanded: list[_Partial] = []
        for partial in beam:
            for rank, exercise_id in enumerate(slot_candidates):
                covered = partial.covered
                if structure is not None:
                    pattern = capped_lookup[slot.id].get(exercise_id)
                    if pattern is not None:
                        for required_index, required_pattern in enumerate(required):
                            if (
                                required_index not in covered
                                and required_pattern == pattern
                            ):
                                covered = covered | {required_index}
                                break
                expanded.append(
                    _Partial(
                        partial.assignment + ((slot.id, exercise_id),),
                        partial.order_cost + rank,
                        partial.ranks + (rank,),
                        covered,
                    )
                )
        if structure is not None:
            future_patterns = {
                future.id: capped_patterns[future.id]
                for future in base_template.slots[position + 1:]
            }
            viable: list[_Partial] = []
            for item in expanded:
                outstanding = [
                    required[index]
                    for index in range(len(required))
                    if index not in item.covered
                ]
                if patterns_assignable(outstanding, future_patterns):
                    viable.append(item)
                else:
                    structural_pruned += 1
            expanded = viable
        expanded.sort(
            key=lambda item: (item.order_cost, item.ranks, item.assignment)
        )
        pruned += max(0, len(expanded) - cfg.width)
        beam = expanded[: cfg.width]
        if not beam:
            raise BeamError(
                "no partial assignment can satisfy the remaining required patterns"
            )

    if structure is not None:
        before = len(beam)
        beam = [
            item for item in beam
            if len(item.covered) == len(required)
        ]
        structural_pruned += before - len(beam)
        if not beam:
            raise BeamError(
                "no complete assignment satisfies the required patterns"
            )

    final_assignments_pruned = max(0, len(beam) - cfg.max_full_evaluations)
    evaluation_budget_applied = final_assignments_pruned > 0
    final = beam[: cfg.max_full_evaluations]
    ranks_by_assignment = {
        partial.assignment: partial.ranks for partial in final
    }
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

    def result_key(result: AssignmentEvaluation) -> tuple:
        return (
            result.score,
            ranks_by_assignment.get(tuple(result.assignment), (99,)),
            result.assignment,
        )

    feasible = [result for result in evaluated if result.feasible]
    best = min(feasible, key=result_key) if feasible else None
    diagnostic = min(evaluated, key=result_key)
    exhaustive = (
        pruned == 0
        and candidate_ids_removed == 0
        and final_assignments_pruned == 0
    )
    truncated = candidate_ids_removed > 0 or final_assignments_pruned > 0

    if best is None:
        if exhaustive:
            reason = (
                f"exhaustive search found no feasible assignment among "
                f"{len(evaluated)} evaluated"
            )
        else:
            reason = (
                f"no feasible assignment found among {len(evaluated)} evaluated; "
                f"search was not exhaustive (best diagnostic score "
                f"{diagnostic.score:.4f})"
            )
    else:
        reason = f"selected a feasible assignment from {len(evaluated)} evaluated"
    if pruned:
        reason += f"; {pruned} partial assignment(s) pruned by beam width"
    if structural_pruned:
        reason += f"; {structural_pruned} partial assignment(s) pruned as structurally impossible"
    if candidate_ids_removed:
        reason += f"; {candidate_ids_removed} candidate(s) removed by slot cap"
    if final_assignments_pruned:
        reason += (
            f"; {final_assignments_pruned} final assignment(s) removed by "
            f"evaluation budget {cfg.max_full_evaluations}"
        )
    structural_reasons = getattr(diagnostic, "structural_violations", ())
    if best is None and structural_reasons:
        reason += "; structural: " + "; ".join(structural_reasons)

    return BeamResult(
        best=best,
        diagnostic=diagnostic,
        evaluated=tuple(evaluated),
        pruned=pruned,
        truncated=truncated,
        candidate_cap_applied=candidate_cap_applied,
        evaluation_budget_applied=evaluation_budget_applied,
        candidate_ids_removed=candidate_ids_removed,
        structural_pruned=structural_pruned,
        final_assignments_pruned=final_assignments_pruned,
        exhaustive=exhaustive,
        reason=reason,
    )
