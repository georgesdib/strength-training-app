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

from strength_coach.domain.symptoms import flare_from as _flare_from
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
    # Days since the last stored session, or None when this is the first one.
    gap_days: int | None = None
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
        gap_days = _gap_days(conn, end)
        if block_week_index is None and profile and profile["block_start_date"] and end:
            block_week_index = trained_week_index(conn, profile["block_start_date"], end)
            # A long break steps the ramp back one stage: rest settles symptoms but does not
            # preserve load tolerance (DEC-CONTINUITY-01).
            if gap_days is not None and gap_days >= 56 and block_week_index:
                block_week_index = max(1, block_week_index - 1)

        return cls(
            sets=sets,
            sessions=queries.sessions(conn, start=start, end=end),
            entities=exercises.taxonomy().entities,
            symptom_flare=symptom_flare,
            symptom_level=level,
            symptom_on=on_date,
            block_week_index=block_week_index,
            gap_days=gap_days,
            rep_ranges=rep_ranges or {},
        )


def flare_from(level: int | None, settled_within_48h: int | None) -> bool | None:
    """Whether a symptom reading counts as a flare.

    Re-exported from `domain.symptoms` so callers keep one import path and the definition
    cannot drift between the rule context and the injury signal.
    """
    return _flare_from(level, settled_within_48h)


def _gap_days(conn, on_date: str | None) -> int | None:
    if on_date is None:
        return None
    row = conn.execute(
        "SELECT MAX(occurred_on) AS last FROM session WHERE occurred_on < ?", (on_date,)
    ).fetchone()
    if row is None or row["last"] is None:
        return None
    last = _dt.date.fromisoformat(str(row["last"])[:10])
    when = _dt.date.fromisoformat(str(on_date)[:10])
    return max(0, (when - last).days)


def trained_week_index(conn, start: str, on_date: str) -> int | None:
    """Weeks with at least one session (or measured test) since the anchor.

    Calendar weeks would let a missed week advance the DUP cycle and the ramp; the athlete
    asked for the opposite (DEC-CONTINUITY-01). A test week counts as a trained week.
    """
    try:
        first = _dt.date.fromisoformat(str(start)[:10])
        when = _dt.date.fromisoformat(str(on_date)[:10])
    except ValueError:
        return None
    if when < first:
        return None

    weeks: set[tuple[int, int]] = set()
    for row in conn.execute(
        "SELECT occurred_on FROM session WHERE occurred_on >= ? AND occurred_on <= ?",
        (str(first), str(when)),
    ):
        try:
            day = _dt.date.fromisoformat(str(row["occurred_on"])[:10])
        except ValueError:
            continue
        iso = day.isocalendar()
        weeks.add((iso[0], iso[1]))
    for row in conn.execute(
        "SELECT effective_from FROM e1rm_override "
        "WHERE source = 'measured' AND effective_from >= ? AND effective_from <= ?",
        (str(first), str(when)),
    ):
        try:
            day = _dt.date.fromisoformat(str(row["effective_from"])[:10])
        except ValueError:
            continue
        iso = day.isocalendar()
        weeks.add((iso[0], iso[1]))

    return max(1, len(weeks))


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
