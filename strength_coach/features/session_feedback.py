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
    productivity: Any = None,
    note: str | None = None,
) -> dict | None:
    """Store optional feedback; return None when everything was left blank.

    Blank is not an error: the review must remain usable without these fields, and a missing
    value must stay unknown rather than becoming zero.
    """
    srpe_value = _number(srpe)
    duration_value = _number(duration_min)
    productivity_value = None if productivity in (None, "") else int(productivity)
    note_value = (note or "").strip() or None
    if (
        srpe_value is None
        and duration_value is None
        and productivity_value is None
        and note_value is None
    ):
        return None
    repositories.append_session_feedback(
        conn,
        session_id=session_id,
        srpe=srpe_value,
        duration_min=duration_value,
        productivity=productivity_value,
        note=note_value,
    )
    return queries.session_feedback(conn, session_id)


def merged(conn, session_id: str) -> dict | None:
    """Latest non-null value per field, without changing the append-only history.

    A later row that records only sRPE must not hide an earlier duration or note. This read is
    for monitoring; existing callers of latest() keep their row-wise behaviour.
    """
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM session_feedback WHERE session_id = ? "
            "ORDER BY recorded_at, rowid",
            (str(session_id),),
        )
    ]
    if not rows:
        return None
    result: dict[str, Any] = {
        "session_id": str(session_id),
        "srpe": None,
        "duration_min": None,
        "productivity": None,
        "note": None,
        "recorded_at": rows[-1]["recorded_at"],
        "sources": {},
    }
    for row in rows:
        for field in ("srpe", "duration_min", "productivity", "note"):
            if row.get(field) is not None:
                result[field] = row[field]
                result["sources"][field] = {
                    "feedback_id": row["feedback_id"],
                    "recorded_at": row["recorded_at"],
                }
    return result


def latest(conn, session_id: str) -> dict | None:
    return queries.session_feedback(conn, session_id)
