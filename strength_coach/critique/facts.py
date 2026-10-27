"""Facts the critique is allowed to score.

A rubric item must be able to say *which row* produced its score, so this layer turns a stored
session into a small immutable object that carries its own evidence: the session's sets, the
history before it, the week's spinal cost, and the template the day was supposed to follow.

Nothing here judges. Judging is `rubric.py`'s job, and the split keeps the numbers auditable:
if a score looks wrong, the fact that fed it is inspectable without re-running the rubric.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from strength_coach.prescribe import SessionTemplate, TemplateError
from strength_coach.prescribe.templates import SESSION_TYPES
from strength_coach.rules import RuleContext, load_document, registry
from strength_coach.store import queries


class UnknownSessionError(KeyError):
    """The requested session is not in the store."""


@dataclass(frozen=True)
class CritiqueFacts:
    session_id: str
    occurred_on: str
    session_type: str
    workout_label: str | None
    sets: pd.DataFrame
    prior_sets: pd.DataFrame
    # Duration is only scoreable when the live workout recorded it; imported rows stay unknown.
    duration_min: float | None
    duration_basis: str
    # Optional post-lift form ratings, exercise -> 1-5; empty means not assessed.
    form_ratings: Mapping[str, int]
    sessions: pd.DataFrame
    week: str
    week_cost: float
    spine_cap: float
    essential_slots: tuple[tuple[str, tuple[str, ...]], ...]
    rep_ranges: Mapping[str, tuple[int, int]]
    # Exercises whose load is progressed by double progression rather than from an e1RM.
    accessory_ranges: Mapping[str, tuple[int, int]]
    taxonomy: Mapping[str, Mapping[str, Any]]
    context: RuleContext = field(repr=False)

    @property
    def has_template(self) -> bool:
        return bool(self.essential_slots)

    def entity(self, exercise_id: str) -> Mapping[str, Any]:
        return self.taxonomy.get(str(exercise_id), {})

    def facts_hash(self) -> str:
        """A stable fingerprint of the facts, stored on the critique row."""
        payload = {
            "session_id": self.session_id,
            "session_type": self.session_type,
            "sets": int(len(self.sets)),
            "working_sets": int(self.sets["is_working_set"].sum()),
            "exercises": sorted({str(e) for e in self.sets["exercise_id"].unique()}),
            "duration_min": self.duration_min,
            "duration_basis": self.duration_basis,
            "form_ratings": dict(sorted(self.form_ratings.items())),
            "week": self.week,
            "week_cost": round(self.week_cost, 4),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()


def build_facts(
    conn,
    session_id: str,
    *,
    document=None,
    template_loader=SessionTemplate.load,
) -> CritiqueFacts:
    """Assemble everything the rubric may look at, for one stored session."""
    document = document or load_document()
    # Session IDs are dates for imported rows, but live workouts use a UUID. Resolve the
    # calendar date first so history is cut at `occurred_on`, not at the identifier.
    session_row = conn.execute(
        "SELECT occurred_on FROM session WHERE session_id = ?", (str(session_id),)
    ).fetchone()
    if session_row is None:
        raise UnknownSessionError(f"no session {session_id!r} in the store")
    occurred_on = str(session_row["occurred_on"])[:10]
    sessions = queries.sessions(conn, end=occurred_on)
    if sessions.empty:
        raise UnknownSessionError(f"no session {session_id!r} in the store")
    matches = sessions[sessions["session_id"].astype(str) == str(session_id)]
    if matches.empty:
        raise UnknownSessionError(f"no session {session_id!r} in the store")
    row = matches.iloc[0]

    session_type = str(row["session_type"])
    template = _template_for(session_type, template_loader)
    rep_ranges = template.rep_ranges() if template is not None else {}

    # History is cut at the session date: a critique that could see the future would grade
    # the athlete against information they did not have.
    context = RuleContext.from_store(conn, end=occurred_on, rep_ranges=rep_ranges)

    sets = context.sets[context.sets["session_id"].astype(str) == str(session_id)]
    prior = context.sets[context.sets["session_id"].astype(str) != str(session_id)]
    form_rows = conn.execute(
        "SELECT exercise_id, rating FROM session_form_rating f "
        "WHERE f.session_id = ? AND NOT EXISTS ("
        "SELECT 1 FROM session_form_rating child WHERE child.supersedes_id = f.form_id) "
        "ORDER BY f.form_id",
        (str(session_id),),
    ).fetchall()
    form_ratings = {str(row["exercise_id"]): int(row["rating"]) for row in form_rows}

    spine_rule = document.rule("PRG-SPINE-001")
    costs = registry.weekly_spinal_costs(spine_rule, context)
    week = registry.iso_week(occurred_on)
    week_cost = float(costs.get(week, {}).get("cost", 0.0))

    essential: list[tuple[str, tuple[str, ...]]] = []
    accessories: dict[str, tuple[int, int]] = {}
    if template is not None:
        essential = [
            (slot.id, slot.exercises) for slot in template.slots if slot.essential
        ]
        accessories = {
            exercise_id: (slot.reps_low, slot.reps_high)
            for slot in template.slots
            if slot.load_source == "double_progression"
            for exercise_id in slot.exercises
        }

    return CritiqueFacts(
        session_id=str(session_id),
        occurred_on=str(row["occurred_on"])[:10],
        session_type=session_type,
        workout_label=(str(row["workout_label"]) if pd.notna(row["workout_label"]) else None),
        sets=sets,
        prior_sets=prior,
        duration_min=(float(row["duration_min"]) if pd.notna(row.get("duration_min")) else None),
        duration_basis=str(row.get("duration_basis") or "unavailable"),
        form_ratings=form_ratings,
        sessions=sessions,
        week=week,
        week_cost=week_cost,
        spine_cap=float(spine_rule.params.get("cap", 3)),
        essential_slots=tuple(essential),
        rep_ranges=rep_ranges,
        accessory_ranges=accessories,
        taxonomy=context.entities,
        context=context,
    )


def _template_for(session_type: str, loader) -> SessionTemplate | None:
    """The session template, or None when the imported session type is unknown."""
    if session_type not in SESSION_TYPES:
        return None
    try:
        return loader(session_type)
    except TemplateError:
        return None
