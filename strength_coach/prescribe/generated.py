"""Read-only helpers for the generated-session snapshot.

The snapshot is JSON on the immutable prescription row. Older prescriptions have NULL, so every
reader must keep the legacy blueprint path. No reader may require the snapshot to score or
display an existing session.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def load_snapshot(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return dict(decoded) if isinstance(decoded, Mapping) else None


def snapshot_for_prescription(conn, prescription_id: str | None) -> dict[str, Any] | None:
    if not prescription_id:
        return None
    row = conn.execute(
        "SELECT generated_session_json FROM prescription WHERE prescription_id = ?",
        (str(prescription_id),),
    ).fetchone()
    return load_snapshot(row["generated_session_json"]) if row is not None else None


def snapshot_for_session(conn, session_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT prescription_id FROM session WHERE session_id = ?",
        (str(session_id),),
    ).fetchone()
    if row is None:
        return None
    return snapshot_for_prescription(conn, row["prescription_id"])


def assignment(snapshot: Mapping[str, Any] | None) -> dict[str, str]:
    if not snapshot:
        return {}
    raw = snapshot.get("assignment")
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(slot): str(exercise)
        for slot, exercise in raw.items()
        if str(slot) and str(exercise)
    }


def slot_specs(snapshot: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    """Return validated slot specs; an old snapshot without specs is treated as legacy."""
    if not snapshot:
        return ()
    raw = snapshot.get("slots")
    if not isinstance(raw, list):
        return ()
    out = []
    for item in raw:
        if not isinstance(item, Mapping):
            return ()
        slot_id = item.get("id")
        exercise_id = item.get("exercise_id")
        if not slot_id or not exercise_id:
            return ()
        out.append(item)
    return tuple(out)


def slots_by_exercise(snapshot: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["exercise_id"]): item
        for item in slot_specs(snapshot)
    }
