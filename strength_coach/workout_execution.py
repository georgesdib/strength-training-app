"""Append-only workout execution telemetry and read-only execution analytics.

Execution events are observational. They do not create or modify workout sets, prescriptions,
e1RM, volume or readiness. workout_set remains the canonical performed-set record and
workout_event remains the server mutation/audit stream.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from strength_coach.store import ios_workflow

EVENT_TYPES = {
    "set_started", "set_completed",
    "rest_started", "rest_completed", "rest_skipped", "rest_extended",
    "exercise_started", "exercise_completed",
    "workout_paused", "workout_resumed",
}
MAX_EVENTS = 100
MAX_PAYLOAD_BYTES = 8192


def _error(status: int, code: str, message: str, **kwargs) -> ios_workflow.IOSWorkflowError:
    return ios_workflow.IOSWorkflowError(status, code, message, **kwargs)


def _parse_timestamp(value: str, field: str) -> datetime.datetime:
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _error(400, "validation_failed", f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise _error(400, "validation_failed", f"{field} must include a timezone")
    return parsed.astimezone(datetime.UTC)


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _workout_row(conn, workout_id: str):
    return conn.execute(
        "SELECT * FROM workout_session WHERE workout_id = ?", (workout_id,)
    ).fetchone()


def _owns_workout(conn, workout_id: str, device_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM ios_issued_plan WHERE workout_id = ? AND device_id = ? LIMIT 1",
        (workout_id, device_id),
    ).fetchone()
    return row is not None


def _validate_payload(event_type: str, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _error(400, "validation_failed", "payload must be an object")
    encoded = _canonical_json(raw)
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise _error(400, "validation_failed", "payload is too large")
    if event_type == "rest_started":
        value = raw.get("prescribed_rest_s")
        if value is not None:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not 0 <= value <= 3600
                    or (isinstance(value, float) and not value.is_integer())):
                raise _error(400, "validation_failed", "prescribed_rest_s must be 0-3600")
            raw["prescribed_rest_s"] = int(value)
    if event_type == "rest_extended":
        value = raw.get("added_s")
        if value is not None:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not 1 <= value <= 3600
                    or (isinstance(value, float) and not value.is_integer())):
                raise _error(400, "validation_failed", "added_s must be 1-3600")
            raw["added_s"] = int(value)
    if event_type in {"workout_paused", "workout_resumed"}:
        reason = raw.get("reason")
        if reason is not None and (not isinstance(reason, str) or len(reason) > 200):
            raise _error(400, "validation_failed", "reason must be a short string")
    return raw


def record_events(conn, *, workout_id: str, device_id: str, events: Any) -> dict[str, Any]:
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise _error(400, "validation_failed", f"events must contain 1-{MAX_EVENTS} items")
    workout = _workout_row(conn, workout_id)
    if workout is None or not _owns_workout(conn, workout_id, device_id):
        raise _error(404, "workout_not_found", "workout not found")
    started = _parse_timestamp(str(workout["started_at"]), "workout.started_at")
    ended = (
        _parse_timestamp(str(workout["ended_at"]), "workout.ended_at")
        if workout["ended_at"] else None
    )
    now = datetime.datetime.now(datetime.UTC)
    accepted: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise _error(400, "validation_failed", f"events[{index}] must be an object")
        unknown = sorted(set(raw) - {
            "event_id", "event_type", "plan_item_index", "set_id",
            "local_set_id", "occurred_at", "payload",
        })
        if unknown:
            raise _error(
                400, "unknown_field",
                f"unknown event field(s): {', '.join(unknown)}",
                fields={key: "not accepted" for key in unknown},
            )
        event_id = raw.get("event_id")
        try:
            parsed_id = uuid.UUID(str(event_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise _error(400, "validation_failed", f"events[{index}].event_id must be a UUID") from exc
        event_id = str(parsed_id)
        if event_id in seen:
            raise _error(409, "event_conflict", "duplicate event_id in batch")
        seen.add(event_id)
        event_type = raw.get("event_type")
        if event_type not in EVENT_TYPES:
            raise _error(400, "validation_failed", f"events[{index}].event_type is not supported")
        occurred = _parse_timestamp(
            str(raw.get("occurred_at") or ""), f"events[{index}].occurred_at"
        )
        if occurred < started - datetime.timedelta(seconds=2):
            raise _error(409, "timestamp_out_of_bounds", "event predates the workout")
        if occurred > now + datetime.timedelta(minutes=5):
            raise _error(409, "timestamp_out_of_bounds", "event is too far in the future")
        if ended is not None and occurred > ended + datetime.timedelta(seconds=2):
            raise _error(409, "timestamp_out_of_bounds", "event postdates the workout")
        if workout["status"] != "in_progress" and ended is None:
            raise _error(409, "workout_not_active", "workout has no end timestamp")
        plan_item_index = raw.get("plan_item_index")
        if plan_item_index is not None and (
            isinstance(plan_item_index, bool) or not isinstance(plan_item_index, int)
            or plan_item_index < 0
        ):
            raise _error(400, "validation_failed", "plan_item_index must be non-negative")
        set_id = raw.get("set_id")
        if set_id is not None:
            if isinstance(set_id, bool) or not isinstance(set_id, int) or set_id < 1:
                raise _error(400, "validation_failed", "set_id must be a positive integer")
            exists = conn.execute(
                "SELECT 1 FROM workout_set WHERE workout_id = ? AND set_id = ?",
                (workout_id, set_id),
            ).fetchone()
            if exists is None:
                raise _error(409, "set_not_found", "set does not belong to this workout")
        local_set_id = raw.get("local_set_id")
        if local_set_id is not None and (
            not isinstance(local_set_id, str) or not local_set_id or len(local_set_id) > 64
        ):
            raise _error(400, "validation_failed", "local_set_id must be a short string")
        payload = _validate_payload(str(event_type), raw.get("payload"))
        payload_json = _canonical_json(payload)
        existing = conn.execute(
            "SELECT * FROM workout_execution_event WHERE event_id = ?", (event_id,)
        ).fetchone()
        if existing is not None:
            same = (
                existing["workout_id"] == workout_id
                and existing["event_type"] == event_type
                and existing["occurred_at"] == str(raw.get("occurred_at"))
                and existing["plan_item_index"] == plan_item_index
                and existing["set_id"] == set_id
                and existing["local_set_id"] == local_set_id
                and existing["payload_json"] == payload_json
                and existing["device_id"] == device_id
            )
            if not same:
                raise _error(409, "event_conflict", "event_id was already used for different data")
            duplicates.append(event_id)
            continue
        conn.execute(
            "INSERT INTO workout_execution_event "
            "(event_id, workout_id, event_type, plan_item_index, set_id, local_set_id, "
            " occurred_at, received_at, device_id, source, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ios', ?)",
            (
                event_id, workout_id, event_type, plan_item_index, set_id, local_set_id,
                str(raw.get("occurred_at")), now.isoformat(), device_id, payload_json,
            ),
        )
        accepted.append(event_id)
    return {
        "workout_id": workout_id,
        "accepted": accepted,
        "duplicates": duplicates,
        "received_at": now.isoformat(),
    }


def _seconds(start: str, end: str) -> float | None:
    try:
        value = (
            _parse_timestamp(end, "end") - _parse_timestamp(start, "start")
        ).total_seconds()
    except ios_workflow.IOSWorkflowError:
        return None
    return round(value, 3) if value >= 0 else None


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def analytics(conn, workout_id: str, device_id: str) -> dict[str, Any] | None:
    workout = _workout_row(conn, workout_id)
    if workout is None or not _owns_workout(conn, workout_id, device_id):
        return None
    events = []
    for row in conn.execute(
        "SELECT * FROM workout_execution_event WHERE workout_id = ? "
        "ORDER BY occurred_at, received_at, event_id",
        (workout_id,),
    ):
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        events.append(item)
    started = _parse_timestamp(str(workout["started_at"]), "started_at")
    ended = (
        _parse_timestamp(str(workout["ended_at"]), "ended_at")
        if workout["ended_at"] else datetime.datetime.now(datetime.UTC)
    )
    total = max(0.0, (ended - started).total_seconds())

    sets: list[dict[str, Any]] = []
    open_sets: dict[str, dict[str, Any]] = {}
    rests: list[dict[str, Any]] = []
    open_rest: dict[str, Any] | None = None
    exercises: list[dict[str, Any]] = []
    open_exercise: dict[str, Any] | None = None

    for event in events:
        event_type = str(event["event_type"])
        occurred = str(event["occurred_at"])
        identity = event.get("local_set_id") or str(event.get("set_id") or "")
        if event_type == "set_started":
            key = identity or f"event:{event['event_id']}"
            open_sets[key] = {
                "set_id": event.get("set_id"),
                "local_set_id": event.get("local_set_id"),
                "plan_item_index": event.get("plan_item_index"),
                "started_at": occurred,
            }
        elif event_type == "set_completed":
            key = identity or f"event:{event['event_id']}"
            start = open_sets.pop(key, None)
            if start is not None:
                duration = _seconds(start["started_at"], occurred)
                if duration is not None:
                    sets.append({
                        **start,
                        "completed_at": occurred,
                        "duration_s": duration,
                    })
        elif event_type == "rest_started":
            if open_rest is not None:
                open_rest = None
            payload = event.get("payload") or {}
            prescribed = payload.get("prescribed_rest_s")
            open_rest = {
                "started_at": occurred,
                "prescribed_rest_s": prescribed,
                "plan_item_index": event.get("plan_item_index"),
            }
        elif event_type in {"rest_completed", "rest_skipped"} and open_rest is not None:
            duration = _seconds(open_rest["started_at"], occurred)
            if duration is not None:
                prescribed = open_rest.get("prescribed_rest_s")
                rests.append({
                    **open_rest,
                    "ended_at": occurred,
                    "actual_rest_s": duration,
                    "outcome": "skipped" if event_type == "rest_skipped" else "completed",
                    "deviation_s": (
                        round(duration - prescribed, 3)
                        if isinstance(prescribed, (int, float)) else None
                    ),
                    "deviation_pct": (
                        round((duration - prescribed) / prescribed * 100, 1)
                        if isinstance(prescribed, (int, float)) and prescribed > 0 else None
                    ),
                })
            open_rest = None
        elif event_type == "rest_extended" and open_rest is not None:
            payload = event.get("payload") or {}
            added = payload.get("added_s")
            if isinstance(added, int) and not isinstance(added, bool):
                current = open_rest.get("prescribed_rest_s")
                if isinstance(current, int):
                    open_rest["prescribed_rest_s"] = current + added
        elif event_type == "exercise_started":
            open_exercise = {
                "plan_item_index": event.get("plan_item_index"),
                "started_at": occurred,
            }
        elif event_type == "exercise_completed" and open_exercise is not None:
            duration = _seconds(open_exercise["started_at"], occurred)
            if duration is not None:
                exercises.append({
                    **open_exercise,
                    "ended_at": occurred,
                    "duration_s": duration,
                })
            open_exercise = None

    active_intervals = [
        (_parse_timestamp(item["started_at"], "started_at").timestamp(),
         _parse_timestamp(item["completed_at"], "completed_at").timestamp())
        for item in sets
    ]
    rest_intervals = [
        (_parse_timestamp(item["started_at"], "started_at").timestamp(),
         _parse_timestamp(item["ended_at"], "ended_at").timestamp())
        for item in rests
    ]
    transition_intervals = []
    for previous, current in zip(exercises, exercises[1:], strict=False):
        start = _parse_timestamp(previous["ended_at"], "ended_at").timestamp()
        end = _parse_timestamp(current["started_at"], "started_at").timestamp()
        if end > start:
            transition_intervals.append((start, end))
    active = sum(end - start for start, end in _merge(active_intervals))
    recovery = sum(end - start for start, end in _merge(rest_intervals))
    transitions = sum(end - start for start, end in _merge(transition_intervals))
    counted = _merge(active_intervals + rest_intervals + transition_intervals)
    counted_total = sum(end - start for start, end in counted)
    return {
        "workout_id": workout_id,
        "status": workout["status"],
        "started_at": workout["started_at"],
        "ended_at": workout["ended_at"],
        "total_elapsed_s": round(total, 3),
        "events": events,
        "sets": sets,
        "rests": rests,
        "exercises": exercises,
        "summary": {
            "active_lifting_s": round(active, 3),
            "recorded_recovery_s": round(recovery, 3),
            "exercise_transition_s": round(transitions, 3),
            "unclassified_s": round(max(0.0, total - counted_total), 3),
            "total_elapsed_s": round(total, 3),
        },
        "data_quality": {
            "event_count": len(events),
            "set_started_events": sum(
                1 for item in events if item["event_type"] == "set_started"
            ),
            "set_completed_events": sum(
                1 for item in events if item["event_type"] == "set_completed"
            ),
            "rest_started_events": sum(
                1 for item in events if item["event_type"] == "rest_started"
            ),
            "rest_ended_events": sum(
                1 for item in events
                if item["event_type"] in {"rest_completed", "rest_skipped"}
            ),
            "exercise_started_events": sum(
                1 for item in events if item["event_type"] == "exercise_started"
            ),
            "exercise_completed_events": sum(
                1 for item in events if item["event_type"] == "exercise_completed"
            ),
            "sets_with_duration": len(sets),
            "rests_with_actual": len(rests),
            "rests_without_prescribed": sum(
                1 for item in rests if item.get("prescribed_rest_s") is None
            ),
            "workout_has_end": workout["ended_at"] is not None,
        },
    }
