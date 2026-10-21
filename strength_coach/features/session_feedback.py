"""Optional post-session feedback: session RPE and session length.

Why not derive it: volume load and hard-set counts can be computed from sets, but perceived
effort and elapsed time cannot. The export has no timestamps (`SESSION_DURATION` is
unmeasurable), and session RPE is a validated internal-load measure for resistance training
(Day 2004). It is captured at review, is skippable, and no model reads it yet.
"""

from __future__ import annotations

from typing import Any

from strength_coach.store import queries, repositories


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def record(
    conn,
    session_id: str,
    *,
    srpe: Any = None,
    duration_min: Any = None,
    note: str | None = None,
) -> dict | None:
    """Store optional feedback; return None when everything was left blank.

    Blank is not an error: the review must remain usable without these fields, and a missing
    value must stay unknown rather than becoming zero.
    """
    srpe_value = _number(srpe)
    duration_value = _number(duration_min)
    note_value = (note or "").strip() or None
    if srpe_value is None and duration_value is None and note_value is None:
        return None
    repositories.append_session_feedback(
        conn,
        session_id=session_id,
        srpe=srpe_value,
        duration_min=duration_value,
        note=note_value,
    )
    return queries.session_feedback(conn, session_id)


def latest(conn, session_id: str) -> dict | None:
    return queries.session_feedback(conn, session_id)
