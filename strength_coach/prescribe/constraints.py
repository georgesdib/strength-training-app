"""Athlete constraints and suitability, applied deterministically.

This is where AGENTS.md §3.11 becomes code: a stored `hard_exclude` constraint vetoes a
proposed exercise whatever any agent says, and a suitability rating is surfaced rather than
silently ignored.

The empty case is deliberately *not* "no constraints": an unrecorded athlete state returns
`none_recorded`, which the prescription engine reports as a warning. Silence must not read as
permission (AGENTS.md §3.12).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from strength_coach.domain.athlete_state import suitability_values
from strength_coach.store import queries
from strength_coach.utils import exercises

STATUS_RECORDED = "recorded"
STATUS_NONE = "none_recorded"


@dataclass(frozen=True)
class ConstraintReport:
    status: str
    vetoes: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def vetoed_ids(self) -> tuple[str, ...]:
        return tuple(exercise_id for exercise_id, _reason in self.vetoes)

    @property
    def recorded(self) -> bool:
        return self.status == STATUS_RECORDED


def evaluate(conn, exercise_ids: list[str], *, as_of: str | None = None) -> ConstraintReport:
    """Apply stored constraints and suitability to a set of proposed exercises.

    `as_of` bounds both to the state recorded on or before that date, so a constraint or a
    rating entered later cannot veto (or permit) a retrospective selection (DEC-STATE-04).
    """
    rules = queries.athlete_constraints(conn, as_of=as_of)
    ratings = queries.exercise_suitability(conn, as_of=as_of)
    if not rules and not ratings:
        # Unrecorded state: report it, do not infer "nothing is wrong".
        return ConstraintReport(status=STATUS_NONE)

    taxonomy = exercises.taxonomy()
    vetoes: list[tuple[str, str]] = []
    warnings: list[str] = []

    for exercise_id in exercise_ids:
        entity = taxonomy.entities.get(exercise_id, {}) or {}
        pattern = entity.get("pattern")

        for rule in rules:
            if rule["severity"] != "hard_exclude":
                continue
            forbidden = set(json.loads(rule["forbidden_exercises"] or "[]"))
            patterns = set(json.loads(rule["forbidden_patterns"] or "[]"))
            if exercise_id in forbidden or (pattern and pattern in patterns):
                vetoes.append(
                    (exercise_id, f"hard_exclude constraint {rule['constraint_id']} "
                                  f"({rule['kind']} {rule['region']})")
                )

        rating = ratings.get(exercise_id)
        if rating is None:
            continue
        flags = suitability_values(rating)
        if not flags["can_do"]:
            vetoes.append((exercise_id, "suitability: can_do = 0"))
        elif not flags["will_do"]:
            warnings.append(f"{exercise_id}: you said you will not do it; a substitution is needed")
        elif flags["feels_bad"]:
            warnings.append(f"{exercise_id}: rated as feeling bad; consider a substitute")

    return ConstraintReport(status=STATUS_RECORDED, vetoes=tuple(vetoes), warnings=tuple(warnings))
