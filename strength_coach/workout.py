"""Live workout session: the link between a prescription snapshot and actual sets.

The prescription is immutable. A workout copies its plan so a later regeneration cannot rewrite
what the athlete saw when they started. Actual sets are append-only; removal is an event, not a
delete, so the audit trail survives an in-session correction.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any, Mapping

REQUIRED_READINESS = (
    "sleep", "energy", "mood", "soreness", "stress", "nutrition", "hydration",
)
OPTIONAL_READINESS = ("hrv_ms", "rhr_bpm", "bodyweight_kg", "fat_pct", "wearable_score")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def validate_readiness(values: Mapping[str, Any]) -> dict[str, float]:
    """The seven self-report fields are required; device fields stay optional."""
    clean: dict[str, float] = {}
    for key in REQUIRED_READINESS:
        value = values.get(key)
        if value in (None, ""):
            raise ValueError(f"readiness.{key} is required")
        number = float(value)
        if not 1 <= number <= 5:
            raise ValueError(f"readiness.{key} must be between 1 and 5")
        clean[key] = number
    for key in OPTIONAL_READINESS:
        value = values.get(key)
        if value not in (None, ""):
            clean[key] = float(value)
    return clean


def _plan(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("plan must be an object")
    items = value.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("plan.items must be a non-empty list")
    return value


def start(
    conn,
    *,
    for_date: str,
    plan: Mapping[str, Any],
    readiness: Mapping[str, Any],
    session_type: str | None = None,
    prescription_id: str | None = None,
    note: str | None = None,
) -> dict:
    active = active_workout(conn)
    if active is not None:
        raise ValueError("a workout is already in progress; end or abandon it first")
    plan_data = _plan(plan)
    readiness_data = validate_readiness(readiness)
    day = str(plan_data.get("session_day") or "").upper()
    if day not in {"A", "B", "C"}:
        raise ValueError("plan.session_day must be A, B or C")
    workout_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO workout_session
            (workout_id, prescription_id, for_date, session_type, session_day, status,
             plan_json, readiness_json, started_at, notes)
        VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?, ?, ?)
        """,
        (
            workout_id, prescription_id, for_date,
            session_type or plan_data.get("session_type"),
            day, json.dumps(plan_data, separators=(",", ":")),
            json.dumps(readiness_data, separators=(",", ":")),
            _now(), note,
        ),
    )
    _event(conn, workout_id, "start", {"readiness": readiness_data})
    return get(conn, workout_id)


def active_workout(conn) -> dict | None:
    row = conn.execute(
        "SELECT workout_id FROM workout_session WHERE status = 'in_progress' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return get(conn, row["workout_id"]) if row else None


def get(conn, workout_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM workout_session WHERE workout_id = ?", (workout_id,)
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["plan"] = json.loads(data.pop("plan_json"))
    data["readiness"] = json.loads(data.pop("readiness_json"))
    data["sets"] = _sets(conn, workout_id)
    data["elapsed_seconds"] = _elapsed(data)
    return data


def _sets(conn, workout_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.* FROM workout_set s
        WHERE s.workout_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM workout_event e
            WHERE e.workout_id = s.workout_id
              AND e.event_type = 'remove_set'
              AND e.target_set_id = s.set_id
          )
        ORDER BY s.set_id
        """,
        (workout_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _elapsed(data: Mapping[str, Any]) -> int:
    start = _parse(data.get("started_at"))
    if start is None:
        return 0
    end = _parse(data.get("ended_at")) or dt.datetime.now(dt.timezone.utc)
    return max(0, int((end - start).total_seconds()))


def _event(conn, workout_id: str, event_type: str, payload: dict,
           target_set_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO workout_event (workout_id, event_type, target_set_id, payload_json) "
        "VALUES (?, ?, ?, ?)",
        (workout_id, event_type, target_set_id,
         json.dumps(payload, separators=(",", ":"))),
    )


def add_set(
    conn,
    workout_id: str,
    *,
    exercise_id: str,
    load_kg: float | None = None,
    reps: int | None = None,
    rir: int | None = None,
    velocity: float | None = None,
    source: str = "manual",
) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    if not exercise_id:
        raise ValueError("exercise_id is required")
    if source not in {"manual", "import", "device"}:
        raise ValueError("source must be manual, import or device")
    row = conn.execute(
        "SELECT COALESCE(MAX(set_index), 0) AS n FROM workout_set WHERE workout_id = ? "
        "AND exercise_id = ?",
        (workout_id, exercise_id),
    ).fetchone()
    set_index = int(row["n"]) + 1
    item_index = next(
        (index for index, item in enumerate(workout["plan"]["items"])
         if item.get("exercise_id") == exercise_id),
        None,
    )
    cursor = conn.execute(
        """
        INSERT INTO workout_set
            (workout_id, exercise_id, set_index, load_kg, reps, rir, velocity, source,
             prescription_item_index)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (workout_id, exercise_id, set_index, load_kg, reps, rir, velocity, source,
         item_index),
    )
    _event(conn, workout_id, "add_set", {"exercise_id": exercise_id,
                                          "set_index": set_index},
           target_set_id=int(cursor.lastrowid))
    return get(conn, workout_id)


def remove_set(conn, workout_id: str, set_id: int) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    row = conn.execute(
        "SELECT set_id FROM workout_set WHERE workout_id = ? AND set_id = ?",
        (workout_id, set_id),
    ).fetchone()
    if row is None:
        raise ValueError("set not found")
    _event(conn, workout_id, "remove_set", {"set_id": int(set_id)},
           target_set_id=int(set_id))
    return get(conn, workout_id)


def end(
    conn,
    workout_id: str,
    *,
    session_rpe: float | None,
    not_recorded: bool = False,
    duration_min: float | None = None,
    notes: str | None = None,
) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    if duration_min is not None:
        duration = float(duration_min)
        if duration <= 0:
            raise ValueError("duration_min must be positive")
        source = "manual"
    else:
        duration = _elapsed(workout) / 60.0
        source = "measured"
    if session_rpe is not None:
        rpe = float(session_rpe)
        if not 1 <= rpe <= 10:
            raise ValueError("session_rpe must be between 1 and 10")
    elif not_recorded:
        rpe = None
    else:
        raise ValueError("session_rpe is required, or mark it not recorded")
    ended = _now()
    conn.execute(
        """
        UPDATE workout_session
        SET status = 'completed', ended_at = ?, duration_measured_s = ?,
            duration_min = ?, duration_source = ?, session_rpe = ?,
            session_rpe_recorded = ?, notes = COALESCE(?, notes)
        WHERE workout_id = ?
        """,
        (ended, _elapsed(workout), duration, source, rpe, 0 if not_recorded else 1,
         notes, workout_id),
    )
    _event(conn, workout_id, "end", {"duration_min": duration,
                                      "session_rpe": rpe,
                                      "not_recorded": bool(not_recorded)})
    return get(conn, workout_id)


def abandon(conn, workout_id: str) -> dict:
    workout = get(conn, workout_id)
    if workout is None:
        raise ValueError("workout not found")
    if workout["status"] != "in_progress":
        raise ValueError("workout is not in progress")
    conn.execute(
        "UPDATE workout_session SET status = 'abandoned', ended_at = ?, "
        "duration_measured_s = ? WHERE workout_id = ?",
        (_now(), _elapsed(workout), workout_id),
    )
    _event(conn, workout_id, "abandon", {})
    return get(conn, workout_id)
