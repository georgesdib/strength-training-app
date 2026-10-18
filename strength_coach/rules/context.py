"""Everything a rule predicate is allowed to look at.

A single immutable context keeps predicates pure: they cannot query, mutate or reach for
global state, so the same rule evaluated twice on the same data gives the same verdict.

`from_store` is the only place rules touch persistence (they import `store`, never the
reverse -- see AGENTS.md §4).
"""

from __future__ import annotations

import datetime as _dt
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
    symptom_level: int | None = None
    symptom_on: str | None = None
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
        """Build the context, deriving symptom state and block week when possible.

        Explicit arguments win, which keeps tests able to present a specific state. Otherwise
        the latest logged symptom at or before `end` is used, and the block week is measured
        from the declared `block_start_date` — never inferred.
        """
        sets = queries.clean_sets(conn, start=start, end=end)
        if not sets.empty:
            # Enrichment is required for e1RM (max-single detection) and for the shared
            # velocity/effort fields; it is the same transform the feature layer uses.
            sets = derived.enrich(sets)
        symptom = queries.latest_symptom(conn, end) if end else None
        level = int(symptom["level"]) if symptom is not None else None
        on_date = str(symptom["logged_on"]) if symptom is not None else None
        if symptom_flare is None:
            symptom_flare = flare_from(level, symptom["settled_within_48h"]
                                       if symptom is not None else None)

        profile = queries.athlete_profile(conn)
        if block_week_index is None and profile and profile["block_start_date"] and end:
            block_week_index = block_week(profile["block_start_date"], end)

        return cls(
            sets=sets,
            sessions=queries.sessions(conn, start=start, end=end),
            entities=exercises.taxonomy().entities,
            symptom_flare=symptom_flare,
            symptom_level=level,
            symptom_on=on_date,
            block_week_index=block_week_index,
            rep_ranges=rep_ranges or {},
        )


def flare_from(level: int | None, settled_within_48h: int | None) -> bool | None:
    """Whether a symptom reading counts as a flare.

    `level` is the agreed 0-3 back scale. A level of 2 or more is a flare; a level of 1 is a
    flare only if it did not settle within 48 hours, which is the constitution's wording. With
    no reading at all the answer is None -- unknown, never "no flare" (DEC-SYMPTOM-02).
    """
    if level is None:
        return None
    if level >= 2:
        return True
    if level == 1:
        return settled_within_48h == 0
    return False


def block_week(start: str, on_date: str) -> int | None:
    """Week index of the declared block, 1-based; None before it starts."""
    try:
        first = _dt.date.fromisoformat(str(start))
        when = _dt.date.fromisoformat(str(on_date))
    except ValueError:
        return None
    if when < first:
        return None
    return (when - first).days // 7 + 1
