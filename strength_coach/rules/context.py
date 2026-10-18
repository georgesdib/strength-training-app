"""Everything a rule predicate is allowed to look at.

A single immutable context keeps predicates pure: they cannot query, mutate or reach for
global state, so the same rule evaluated twice on the same data gives the same verdict.

`from_store` is the only place rules touch persistence (they import `store`, never the
reverse -- see AGENTS.md §4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd

from strength_coach.features import derived
from strength_coach.store import queries
from strength_coach.utils import exercises


@dataclass(frozen=True)
class RuleContext:
    sets: pd.DataFrame
    sessions: pd.DataFrame
    entities: Mapping[str, Mapping[str, Any]]
    # Absent until the manual input exists (Q4). None means "not known", never "no flare".
    symptom_flare: bool | None = None
    # Absent until the athlete anchors the block (Q3).
    block_week_index: int | None = None
    # Supplied by the prescription engine in phase 5; empty here rather than guessed.
    rep_ranges: Mapping[str, tuple[int, int]] = field(default_factory=dict)

    def entity(self, exercise_id: str) -> Mapping[str, Any]:
        return self.entities.get(str(exercise_id), {})

    @classmethod
    def from_store(
        cls,
        conn,
        *,
        start: str | None = None,
        end: str | None = None,
        symptom_flare: bool | None = None,
        block_week_index: int | None = None,
        rep_ranges: Mapping[str, tuple[int, int]] | None = None,
    ) -> "RuleContext":
        sets = queries.clean_sets(conn, start=start, end=end)
        if not sets.empty:
            # Enrichment is required for e1RM (max-single detection) and for the shared
            # velocity/effort fields; it is the same transform the feature layer uses.
            sets = derived.enrich(sets)
        return cls(
            sets=sets,
            sessions=queries.sessions(conn, start=start, end=end),
            entities=exercises.taxonomy().entities,
            symptom_flare=symptom_flare,
            block_week_index=block_week_index,
            rep_ranges=rep_ranges or {},
        )
