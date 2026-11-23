"""Late reconciliation of events that arrive after a workout is completed (D8).

A phone may finish before it has received a watch's sets. Completion must not discard them, so the
session stays open for a bounded window: late sets are appended with their original timestamps,
derived metrics recompute on read, and an arrival after the window is preserved as a rejected event
rather than deleted. The window is configuration, not a constant (D8, owner decision 2026-11-23).
"""

from __future__ import annotations

import datetime as dt
import json

EVENT_OPEN = "late_reconciliation"
EVENT_CLOSED = "reconciliation_closed"
EVENT_LATE_SET = "late_set"
EVENT_REJECTED = "late_rejected"

WINDOW_DAYS = 7
MIN_WINDOW_DAYS = 1
MAX_WINDOW_DAYS = 30


class WindowClosed(ValueError):
    """A late arrival after the reconciliation window closed.

    Carries the attempted payload so the caller can preserve it as a rejected event outside the
    transaction that rejected it, and never delete it.
    """

    def __init__(self, message: str, payload: dict | None = None) -> None:
        super().__init__(message)
        self.payload = dict(payload or {})


def window_days(conn=None) -> int:
    """The configured window, defaulting to seven days when the config cannot be read."""
    if conn is None:
        return WINDOW_DAYS
    try:
        from strength_coach import ios_config

        value = int(ios_config.load_config().reconciliation_window_days)
    except Exception:  # a broken config must not turn a preserved event into a lost one
        return WINDOW_DAYS
    return max(MIN_WINDOW_DAYS, min(MAX_WINDOW_DAYS, value))


def _events(conn, workout_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, event_type, payload_json, created_at FROM workout_event "
        "WHERE workout_id = ? AND event_type IN (?, ?) ORDER BY event_id",
        (workout_id, EVENT_OPEN, EVENT_CLOSED),
    ).fetchall()
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            payload = {}
        out.append({
            "event_id": int(row["event_id"]),
            "type": str(row["event_type"]),
            "payload": payload,
            "created_at": str(row["created_at"]),
        })
    return out


def state(conn, workout_id: str, now: dt.datetime | None = None) -> dict:
    """The reconciliation state of one workout; pure, so a read never writes.

    `none` means no window was opened (a session with no other device pending),
    `open` means late events are still accepted, `closed` means they are preserved as
    rejected. A window whose deadline has passed reports closed even before the closing event
    is written.
    """
    latest_open = None
    latest_closed = None
    for event in _events(conn, workout_id):
        if event["type"] == EVENT_OPEN:
            latest_open = event
        elif latest_open is not None and event["event_id"] > latest_open["event_id"]:
            latest_closed = event
    if latest_open is None:
        return {"state": "none", "pending_devices": [], "closes_at": None}
    closes_at = latest_open["payload"].get("closes_at")
    pending = list(latest_open["payload"].get("pending_devices") or [])
    if latest_closed is not None:
        return {
            "state": "closed", "pending_devices": pending, "closes_at": closes_at,
            "closed_at": latest_closed["payload"].get("closed_at"),
        }
    moment = now or dt.datetime.now(dt.UTC)
    deadline = _parse(closes_at)
    if deadline is not None and moment > deadline:
        return {"state": "closed", "pending_devices": pending, "closes_at": closes_at}
    return {"state": "open", "pending_devices": pending, "closes_at": closes_at}


def open_window(
    conn,
    workout_id: str,
    *,
    pending_devices: list[str],
    ended_at: str,
) -> dict:
    """Open the window for devices whose events have not arrived yet. Idempotent."""
    current = state(conn, workout_id)
    if current["state"] != "none":
        return current
    devices = sorted({str(device) for device in pending_devices if str(device).strip()})
    if not devices:
        return current
    deadline = _parse(ended_at)
    if deadline is None:
        deadline = dt.datetime.now(dt.UTC)
    closes_at = (deadline + dt.timedelta(days=window_days(conn))).isoformat(
        timespec="seconds"
    )
    payload = {"pending_devices": devices, "closes_at": closes_at}
    conn.execute(
        "INSERT INTO workout_event (workout_id, event_type, payload_json) VALUES (?, ?, ?)",
        (workout_id, EVENT_OPEN, json.dumps(payload, separators=(",", ":"))),
    )
    return {"state": "open", "pending_devices": devices, "closes_at": closes_at}


def close_if_elapsed(conn, workout_id: str, now: dt.datetime | None = None) -> bool:
    """Append the closing event once the deadline has passed; True when written."""
    current = state(conn, workout_id, now=now)
    if current["state"] != "closed" or current.get("closed_at"):
        return False
    payload = {
        "closed_at": (now or dt.datetime.now(dt.UTC)).isoformat(timespec="seconds"),
        "reason": "window_elapsed",
        "closes_at": current["closes_at"],
    }
    conn.execute(
        "INSERT INTO workout_event (workout_id, event_type, payload_json) VALUES (?, ?, ?)",
        (workout_id, EVENT_CLOSED, json.dumps(payload, separators=(",", ":"))),
    )
    return True


def record_rejection(conn, workout_id: str, payload: dict) -> None:
    """Preserve a late arrival that can no longer be applied. Never silent, never deleted."""
    body = dict(payload)
    body.setdefault("reason", "reconciliation_window_closed")
    conn.execute(
        "INSERT INTO workout_event (workout_id, event_type, payload_json) VALUES (?, ?, ?)",
        (workout_id, EVENT_REJECTED, json.dumps(body, separators=(",", ":"), default=str)),
    )


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)
