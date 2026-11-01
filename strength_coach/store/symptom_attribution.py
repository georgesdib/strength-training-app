"""Validation for the optional symptom-to-session attribution.

Attribution is the athlete's suspicion, not a cause: the injury signal and every prescription
path ignore these fields (DEC-INJURY-06). The rules live here so the CLI, API and repository
share one implementation.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

import yaml

from strength_coach.utils import exercises, paths

CONFIDENCES = ("possible", "likely", "strong")
TIMINGS = ("pre_session", "post_session", "next_morning")
DEFAULT_LOOKBACK_DAYS = 7


class AttributionError(ValueError):
    """A field-specific validation failure for a symptom attribution."""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date(value: str, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise AttributionError(f"{field} must be YYYY-MM-DD", field) from exc


def lookback_days() -> int:
    """Configured capture window; a convenience, not a clinical threshold."""
    try:
        raw = yaml.safe_load(paths.injuries_yaml().read_text(encoding="utf-8")) or {}
        value = int(raw.get("attribution_lookback_days", DEFAULT_LOOKBACK_DAYS))
    except (OSError, TypeError, ValueError):
        return DEFAULT_LOOKBACK_DAYS
    return value if value > 0 else DEFAULT_LOOKBACK_DAYS


def _session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT session_id, occurred_on, session_type, source, voided "
        "FROM session WHERE session_id = ?",
        (session_id,),
    ).fetchone()


def _performed_exercises(conn: sqlite3.Connection, session_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT exercise_id FROM clean_set "
        "WHERE session_id = ? AND voided = 0 "
        "AND NOT EXISTS (SELECT 1 FROM clean_set child "
        "WHERE child.supersedes_id = clean_set.set_id)",
        (session_id,),
    ).fetchall()
    return {str(row["exercise_id"]) for row in rows}


def validate(
    conn: sqlite3.Connection,
    *,
    logged_on: str,
    timing: str,
    attributed_session_id: str | None = None,
    attributed_exercise_id: str | None = None,
    onset_on: str | None = None,
    attribution_confidence: str | None = None,
) -> dict[str, str | None] | None:
    """Validate and normalise attribution fields; return None when none are supplied."""
    values = {
        "attributed_session_id": _clean(attributed_session_id),
        "attributed_exercise_id": _clean(attributed_exercise_id),
        "onset_on": _clean(onset_on),
        "attribution_confidence": _clean(attribution_confidence),
    }
    if not any(values.values()):
        return None
    if values["attributed_session_id"] is None:
        raise AttributionError(
            "a completed session is required when any attribution field is set",
            "attributed_session_id",
        )
    if values["onset_on"] is None:
        raise AttributionError(
            "an onset date is required when a session is attributed", "onset_on"
        )
    if values["attribution_confidence"] is None:
        raise AttributionError(
            "a confidence label is required when a session is attributed",
            "attribution_confidence",
        )
    if values["attribution_confidence"] not in CONFIDENCES:
        raise AttributionError(
            "attribution_confidence must be possible, likely or strong",
            "attribution_confidence",
        )
    if timing not in TIMINGS:
        raise AttributionError(
            "timing must be pre_session, post_session or next_morning", "timing"
        )
    read_day = _date(logged_on, "date")
    onset = _date(values["onset_on"], "onset_on")
    if onset > read_day:
        raise AttributionError("onset_on cannot be after the reading date", "onset_on")

    session = _session(conn, str(values["attributed_session_id"]))
    if session is None or int(session["voided"] or 0):
        raise AttributionError(
            "attributed_session_id must name a completed session",
            "attributed_session_id",
        )
    session_day = _date(str(session["occurred_on"]), "attributed_session_id")
    if timing == "pre_session":
        if session_day >= onset:
            raise AttributionError(
                "a pre-session reading cannot point at a session on the onset date",
                "attributed_session_id",
            )
    elif session_day > onset:
        raise AttributionError(
            "the attributed session cannot be after onset_on", "attributed_session_id"
        )
    if (onset - session_day).days > lookback_days():
        raise AttributionError(
            f"the attributed session is outside the {lookback_days()}-day lookback",
            "attributed_session_id",
        )

    exercise_id = values["attributed_exercise_id"]
    if exercise_id is not None:
        performed = _performed_exercises(conn, str(session["session_id"]))
        if exercise_id not in performed:
            raise AttributionError(
                "the attributed exercise was not performed in that session",
                "attributed_exercise_id",
            )
    return values


def candidates(
    conn: sqlite3.Connection,
    *,
    onset_on: str,
    timing: str = "pre_session",
) -> list[dict[str, Any]]:
    """Completed sessions and performed lifts the form may offer for one onset date."""
    onset = _date(onset_on, "onset_on")
    if timing not in TIMINGS:
        raise AttributionError(
            "timing must be pre_session, post_session or next_morning", "timing"
        )
    lookback = lookback_days()
    start = (onset - dt.timedelta(days=lookback)).isoformat()
    end = (
        (onset - dt.timedelta(days=1)).isoformat()
        if timing == "pre_session" else onset.isoformat()
    )
    rows = conn.execute(
        "SELECT session_id, occurred_on, session_type, source FROM session "
        "WHERE occurred_on >= ? AND occurred_on <= ? AND voided = 0 "
        "ORDER BY occurred_on DESC, created_at DESC, session_id DESC",
        (start, end),
    ).fetchall()
    taxonomy = exercises.taxonomy().entities
    out = []
    for row in rows:
        session_id = str(row["session_id"])
        lifts = []
        for exercise_id in sorted(_performed_exercises(conn, session_id)):
            entity = taxonomy.get(exercise_id) or {}
            lifts.append({
                "exercise_id": exercise_id,
                "label": str(entity.get("display") or exercise_id),
                "known": bool(entity),
            })
        out.append({
            "session_id": session_id,
            "occurred_on": str(row["occurred_on"])[:10],
            "session_type": str(row["session_type"] or "unknown"),
            "source": str(row["source"] or ""),
            "lifts": lifts,
        })
    return out


def events_for_session(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM symptom_log WHERE attributed_session_id = ? "
        "ORDER BY logged_on DESC, log_id DESC",
        (str(session_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def counts_for_sessions(conn: sqlite3.Connection, session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in session_ids)
    rows = conn.execute(
        f"SELECT attributed_session_id, COUNT(*) AS n FROM symptom_log "
        f"WHERE attributed_session_id IN ({placeholders}) GROUP BY attributed_session_id",
        session_ids,
    ).fetchall()
    return {str(row["attributed_session_id"]): int(row["n"]) for row in rows}
