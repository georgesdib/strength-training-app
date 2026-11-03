"""Read-only helpers for the generated-session snapshot.

The snapshot is JSON on the immutable prescription row. Older prescriptions have NULL or a
pre-Step-6 payload without slot specs, so every reader keeps the legacy blueprint path. A
snapshot that claims to carry slots is validated strictly: malformed data must fail loudly
rather than silently becoming authoritative.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class SnapshotError(ValueError):
    """A generated-session snapshot is present but not structurally trustworthy."""


_MAX_TEXT = 200
_SLOT_FIELDS = (
    "id", "exercise_id", "sets", "reps_low", "reps_high", "rir_low", "rir_high",
    "rest_s", "essential", "load_source", "power", "quality_stop",
)


def load_snapshot(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise SnapshotError(f"generated-session snapshot is not valid JSON: {exc}") from exc
    if not isinstance(decoded, Mapping):
        raise SnapshotError("generated-session snapshot must be a JSON object")
    return dict(decoded)


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


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT:
        raise SnapshotError(f"slot {field} must be a non-empty string")
    return value


def _integer(value: Any, field: str, *, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SnapshotError(f"slot {field} must be an integer from {low} to {high}")
    return value


def _optional_integer(value: Any, field: str, *, low: int, high: int) -> int | None:
    if value is None:
        return None
    return _integer(value, field, low=low, high=high)


def _slot(item: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in _SLOT_FIELDS if field not in item]
    if missing:
        raise SnapshotError("slot is missing required field(s): " + ", ".join(missing))
    slot_id = _text(item["id"], "id")
    exercise_id = _text(item["exercise_id"], "exercise_id")
    sets = _integer(item["sets"], "sets", low=1, high=50)
    reps_low = _integer(item["reps_low"], "reps_low", low=1, high=100)
    reps_high = _integer(item["reps_high"], "reps_high", low=1, high=100)
    if reps_low > reps_high:
        raise SnapshotError("slot reps_low must not exceed reps_high")
    rir_low = _optional_integer(item["rir_low"], "rir_low", low=0, high=10)
    rir_high = _optional_integer(item["rir_high"], "rir_high", low=0, high=10)
    if rir_low is not None and rir_high is not None and rir_low > rir_high:
        raise SnapshotError("slot rir_low must not exceed rir_high")
    rest_s = _optional_integer(item["rest_s"], "rest_s", low=0, high=3600)
    essential = item["essential"]
    power = item["power"]
    if not isinstance(essential, bool) or not isinstance(power, bool):
        raise SnapshotError("slot essential/power must be booleans")
    load_source = _text(item["load_source"], "load_source")
    quality_stop = item["quality_stop"]
    if quality_stop is not None and not isinstance(quality_stop, str):
        raise SnapshotError("slot quality_stop must be a string or null")
    return {
        "id": slot_id,
        "exercise_id": exercise_id,
        "sets": sets,
        "reps_low": reps_low,
        "reps_high": reps_high,
        "rir_low": rir_low,
        "rir_high": rir_high,
        "rest_s": rest_s,
        "essential": essential,
        "load_source": load_source,
        "power": power,
        "quality_stop": quality_stop,
    }


def _bad_slot():
    raise SnapshotError("each slot must be an object")


def slot_specs(snapshot: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    """Return validated slot specs.

    A snapshot without a slots key is a supported pre-Step-6 legacy payload and returns an
    empty tuple. A snapshot that carries slots must be complete, unique and consistent with
    its assignment; anything else raises SnapshotError rather than falling back.
    """
    if snapshot is None:
        return ()
    if not isinstance(snapshot, Mapping):
        raise SnapshotError("generated-session snapshot must be an object")
    if "slots" not in snapshot:
        return ()
    raw = snapshot.get("slots")
    if not isinstance(raw, list) or not raw:
        raise SnapshotError("slots must be a non-empty list when present")
    out = tuple(_slot(item) if isinstance(item, Mapping) else _bad_slot() for item in raw)
    ids = [item["id"] for item in out]
    if len(set(ids)) != len(ids):
        raise SnapshotError("slot IDs must be unique")
    exercises = [item["exercise_id"] for item in out]
    if len(set(exercises)) != len(exercises):
        raise SnapshotError("generated exercise assignments must be unique")
    assigned = assignment(snapshot)
    if not assigned or set(assigned) != set(ids):
        raise SnapshotError("slot IDs must exactly match the assignment")
    for item in out:
        if assigned[item["id"]] != item["exercise_id"]:
            raise SnapshotError(
                f"slot {item['id']!r} exercise does not match the assignment"
            )
    return out


def slots_by_exercise(snapshot: Mapping[str, Any] | None) -> dict[str, Mapping[str, Any]]:
    return {item["exercise_id"]: item for item in slot_specs(snapshot)}


def validate_snapshot(snapshot: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    """Validate a newly built snapshot before it is persisted."""
    return slot_specs(snapshot)
