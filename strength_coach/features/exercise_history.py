"""Read-only per-exercise history for the active-workout panel.

Only completed/imported sessions are history: sets logged in the live workout stay in
`workout_set` until the workout ends. Corrections remain the append-only History editor's
job, so this module never writes.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from strength_coach.utils import exercises

# Mirror of history.CURRENT for clean_set aliased as cs. Features cannot import the
# higher-level corrections module, and a superseded row must never appear in a log view.
_CURRENT_SET = (
    "cs.voided = 0 AND NOT EXISTS "
    "(SELECT 1 FROM clean_set child WHERE child.supersedes_id = cs.set_id)"
)

MAX_LIMIT = 50


def _validated(exercise_id: str, limit: int, offset: int,
               on_or_before: str | None) -> tuple[str, tuple[str, ...], str | None]:
    requested = str(exercise_id or "").strip()
    if not requested or requested not in exercises.taxonomy().entities:
        raise ValueError(f"unknown exercise: {exercise_id}")
    if not 1 <= int(limit) <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    if int(offset) < 0:
        raise ValueError("offset must be non-negative")
    before = None if on_or_before in (None, "") else str(on_or_before)
    if before is not None:
        try:
            dt.date.fromisoformat(before)
        except ValueError as exc:
            raise ValueError("on_or_before must be YYYY-MM-DD") from exc
    return requested, exercises.history_equivalents(requested), before


def history(conn, exercise_id: str, *, limit: int = 5, offset: int = 0,
            on_or_before: str | None = None) -> dict[str, Any]:
    """Return completed sessions containing the exercise, newest first.

    `limit` counts sessions, not sets: the panel shows the last five sessions and its
    "Show more" control asks for the next page. Declared history equivalents (currently
    back extension and hyperextension) are included and reported back to the caller.
    """
    requested, included, before = _validated(exercise_id, limit, offset, on_or_before)
    placeholders = ",".join("?" for _ in included)
    where = [
        "s.voided = 0",
        "EXISTS (SELECT 1 FROM clean_set cs WHERE cs.session_id = s.session_id "
        f"AND cs.exercise_id IN ({placeholders}) AND cs.is_working_set = 1 "
        f"AND {_CURRENT_SET})",
    ]
    params: list[Any] = list(included)
    if before is not None:
        where.append("s.occurred_on <= ?")
        params.append(before)
    clause = " AND ".join(where)

    total = int(conn.execute(
        f"SELECT COUNT(*) AS n FROM session s WHERE {clause}", params
    ).fetchone()["n"])
    rows = conn.execute(
        "SELECT s.session_id, s.occurred_on, s.session_type FROM session s "
        f"WHERE {clause} ORDER BY s.occurred_on DESC, s.session_id DESC LIMIT ? OFFSET ?",
        params + [int(limit), int(offset)],
    ).fetchall()

    sessions: list[dict[str, Any]] = []
    if rows:
        session_ids = [str(row["session_id"]) for row in rows]
        session_placeholders = ",".join("?" for _ in session_ids)
        set_rows = conn.execute(
            "SELECT cs.session_id, cs.set_id, cs.load_kg, cs.load_basis, cs.reps, "
            "cs.reps_unit, cs.rir FROM clean_set cs "
            f"WHERE cs.session_id IN ({session_placeholders}) "
            f"AND cs.exercise_id IN ({placeholders}) AND cs.is_working_set = 1 "
            f"AND {_CURRENT_SET} "
            "ORDER BY cs.session_id, COALESCE(cs.raw_id, cs.set_id), cs.set_id",
            session_ids + list(included),
        ).fetchall()
        by_session: dict[str, list[dict[str, Any]]] = {key: [] for key in session_ids}
        for row in set_rows:
            by_session[str(row["session_id"])].append({
                "set_index": len(by_session[str(row["session_id"])]) + 1,
                "load_kg": row["load_kg"],
                "load_basis": row["load_basis"],
                "reps": row["reps"],
                "reps_unit": row["reps_unit"],
                "rir": row["rir"],
            })
        for row in rows:
            session_id = str(row["session_id"])
            sessions.append({
                "session_id": session_id,
                "occurred_on": str(row["occurred_on"])[:10],
                "session_type": row["session_type"],
                "sets": by_session[session_id],
            })

    entities = exercises.taxonomy().entities
    return {
        "exercise_id": requested,
        "included_exercises": [
            {
                "id": item,
                "display": str(entities.get(item, {}).get("display") or item),
            }
            for item in included
        ],
        "limit": int(limit),
        "offset": int(offset),
        "total": total,
        "has_more": int(offset) + len(sessions) < total,
        "sessions": sessions,
    }
