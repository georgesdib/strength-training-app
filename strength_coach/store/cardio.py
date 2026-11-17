"""Canonical cardio corpus: workouts, samples, links and status events.

The schema is migration 0064. This module is the only writer: it owns identity, idempotency and
the link-event rules so callers never assemble SQL against these tables themselves.

Two rules that are easy to get wrong and expensive to fix later:

1. Identity is `external_key`, not a row id and not a device. A re-run over the same export, or a
   re-paired phone re-uploading the same workout, must collapse onto one row.
2. A link is an event. The current state of a workout is its latest link event, so unlinking never
   rewrites a row and the history of who claimed what stays auditable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from strength_coach.store import db

ORIGINS = ("export", "healthkit")
METHODS = ("explicit", "interval_overlap", "day_containment", "manual")
SAMPLE_KINDS = ("heart_rate", "cycling_power", "running_power")
ASSOCIATIONS = ("workout", "tail", "none")
STATUSES = (
    "absent_from_source",
    "source_unavailable",
    "access_unconfirmed",
    "partial_result",
    "confirmed_deleted",
    "reappeared",
)

# Fields that must never change for a given key. A change means the source reused an identity,
# which is a conflict rather than an update: history is append-only.
_WORKOUT_IMMUTABLE = (
    "origin",
    "activity_type",
    "started_at",
    "ended_at",
    "duration_s",
    "source_name",
)
_SAMPLE_IMMUTABLE = ("kind", "sampled_at", "value", "unit", "source_name")


class CardioIngestError(ValueError):
    """A row cannot be written as given."""


class CardioConflict(ValueError):
    """An identity was reused with different immutable data."""


def utc_iso(value: str, *, field: str) -> str:
    """Normalise an ISO-8601 timestamp to UTC; reject anything without an offset.

    Two reasons this is a normaliser and not a validator. A naive timestamp would be read as
    local time by SQLite comparisons and would silently shift every windowed metric. And stored
    values are compared as strings, so a `+02:00` row would sort wrongly against a `+00:00` one:
    converting to UTC is what makes lexicographic order equal chronological order.

    The Apple export writes `2026-11-10 08:00:00 +0000` (space before the offset), which
    `fromisoformat` does not accept directly; the offset is closed up first.
    """
    text = str(value).strip()
    if not text:
        raise CardioIngestError(f"{field} is required")
    candidate = text.replace("Z", "+00:00")
    if " +" in candidate:
        candidate = candidate.replace(" +", "+", 1)
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise CardioIngestError(f"{field} is not ISO-8601: {text!r}") from exc
    if parsed.tzinfo is None:
        raise CardioIngestError(f"{field} must carry a UTC offset: {text!r}")
    return parsed.astimezone(dt.UTC).isoformat()


def _text(value: str | bytes | None) -> str:
    """Render a key for a message; keys are stored as digests, so log them as hex."""
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def content_key(
    *,
    activity_type: str,
    started_at: str,
    ended_at: str,
    duration_s: int,
    source_bundle_id: str | None = None,
) -> bytes:
    """Deterministic identity for a row that has no HealthKit UUID.

    Export records carry no sample UUIDs, so the key is built from the fields that make a workout
    the same workout. Changing the composition changes identity for every row, which is why it is
    one function rather than a format string at the call site.

    Returns the 32-byte digest: hex is a display concern and belongs in logging, not in the row
    and its indexes.
    """
    payload = "|".join(
        [
            str(activity_type),
            str(started_at),
            str(ended_at),
            str(int(duration_s)),
            str(source_bundle_id or ""),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).digest()


def sample_content_key(
    *,
    kind: str,
    sampled_at: str,
    value: float,
    unit: str,
    source_bundle_id: str | None = None,
) -> bytes:
    """Identity for a sample that has no HealthKit UUID.

    The value and unit are part of the key on purpose: two devices can record a sample in the
    same second, and a key without them collapses those into a "conflict" that is really two
    different measurements.
    """
    payload = "|".join(
        [str(kind), str(sampled_at), f"{float(value):.6f}", str(unit), str(source_bundle_id or "")]
    )
    return hashlib.sha256(payload.encode("utf-8")).digest()


def get_workout(conn: sqlite3.Connection, external_key: bytes | str) -> dict[str, Any] | None:
    """Look up by identity key, which is what a re-import supplies."""
    row = conn.execute(
        "SELECT * FROM external_workout WHERE external_key = ?", (external_key,)
    ).fetchone()
    return dict(row) if row is not None else None


def get_workout_by_id(conn: sqlite3.Connection, external_workout_id: str) -> dict[str, Any] | None:
    """Look up by row id, which is what a link or status event references."""
    row = conn.execute(
        "SELECT * FROM external_workout WHERE external_workout_id = ?", (external_workout_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def record_workout(
    conn: sqlite3.Connection,
    *,
    external_key: bytes | str,
    origin: str,
    activity_type: str,
    started_at: str,
    ended_at: str,
    duration_s: int,
    source_name: str,
    imported_at: str,
    timezone: str | None = None,
    source_bundle_id: str | None = None,
    source_version: str | None = None,
    device: str | None = None,
    avg_heart_rate: int | None = None,
    max_heart_rate: int | None = None,
    active_energy_kj: float | None = None,
    distance_m: float | None = None,
    avg_mets: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert one workout; return (row, created).

    Re-recording an unchanged workout is a no-op. Re-recording the same key with different
    immutable data raises :class:`CardioConflict` instead of overwriting history.
    """
    if origin not in ORIGINS:
        raise CardioIngestError(f"unknown origin {origin!r}")
    if not str(activity_type).strip():
        raise CardioIngestError("activity_type is required")
    started = utc_iso(started_at, field="started_at")
    ended = utc_iso(ended_at, field="ended_at")
    if started >= ended:
        raise CardioIngestError("started_at must precede ended_at")
    if int(duration_s) <= 0:
        raise CardioIngestError("duration_s must be positive")
    if avg_heart_rate is not None and max_heart_rate is not None and avg_heart_rate > max_heart_rate:
        raise CardioIngestError("avg_heart_rate cannot exceed max_heart_rate")

    payload = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))
    values = {
        "origin": origin,
        "activity_type": activity_type,
        "started_at": started,
        "ended_at": ended,
        "duration_s": int(duration_s),
        "source_name": source_name,
    }
    if isinstance(external_key, str):
        external_key = external_key.encode("utf-8")
    existing = get_workout(conn, external_key)
    if existing is not None:
        changed = [field for field in _WORKOUT_IMMUTABLE if existing[field] != values[field]]
        if changed:
            raise CardioConflict(
                f"workout {_text(external_key)} already exists with different {', '.join(changed)}"
            )
        return existing, False

    workout_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO external_workout (
            external_workout_id, external_key, origin, activity_type, started_at, ended_at,
            timezone, duration_s, source_name, source_bundle_id, source_version, device,
            avg_heart_rate, max_heart_rate, active_energy_kj, distance_m, avg_mets,
            imported_at, metadata_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            workout_id,
            external_key,
            origin,
            activity_type,
            started,
            ended,
            timezone,
            int(duration_s),
            source_name,
            source_bundle_id,
            source_version,
            device,
            avg_heart_rate,
            max_heart_rate,
            active_energy_kj,
            distance_m,
            avg_mets,
            utc_iso(imported_at, field="imported_at"),
            payload,
        ),
    )
    stored = get_workout(conn, external_key)
    assert stored is not None
    return stored, True


def record_sample(
    conn: sqlite3.Connection,
    *,
    sample_key: str,
    kind: str,
    sampled_at: str,
    value: float,
    unit: str,
    source_name: str,
    imported_at: str,
    external_workout_id: str | None = None,
    association: str = "none",
    source_bundle_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    if kind not in SAMPLE_KINDS:
        raise CardioIngestError(f"unknown sample kind {kind!r}")
    if association not in ASSOCIATIONS:
        raise CardioIngestError(f"unknown association {association!r}")
    if (association == "none") != (external_workout_id is None):
        raise CardioIngestError("association and external_workout_id must agree")
    if kind == "heart_rate" and not 20 <= float(value) <= 260:
        raise CardioIngestError(f"impossible heart rate {value!r}")
    if isinstance(sample_key, str):
        sample_key = sample_key.encode("utf-8")

    row = conn.execute(
        "SELECT * FROM health_sample WHERE sample_key = ?", (sample_key,)
    ).fetchone()
    if row is not None:
        existing = dict(row)
        changed = [f for f in _SAMPLE_IMMUTABLE if existing[f] != {
            "kind": kind, "sampled_at": sampled_at, "value": float(value),
            "unit": unit, "source_name": source_name,
        }[f]]
        if changed:
            raise CardioConflict(
                f"sample {_text(sample_key)} already exists with different {', '.join(changed)}"
            )
        return existing, False

    conn.execute(
        """
        INSERT INTO health_sample (
            sample_key, external_workout_id, kind, sampled_at, value, unit,
            association, source_name, source_bundle_id, imported_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            sample_key,
            external_workout_id,
            kind,
            utc_iso(sampled_at, field="sampled_at"),
            float(value),
            unit,
            association,
            source_name,
            source_bundle_id,
            utc_iso(imported_at, field="imported_at"),
        ),
    )
    stored = conn.execute(
        "SELECT * FROM health_sample WHERE sample_key = ?", (sample_key,)
    ).fetchone()
    assert stored is not None
    return dict(stored), True


def active_link(conn: sqlite3.Connection, external_workout_id: str) -> dict[str, Any] | None:
    """The workout's current link, or None when it has none or was unlinked.

    Ordered by rowid, not by `created_at`: a link and its unlink can be written inside the same
    transaction and therefore share a millisecond. Deletes are blocked by trigger, so rowid never
    regresses and insertion order is the event order.
    """
    row = conn.execute(
        """
        SELECT * FROM workout_link
        WHERE external_workout_id = ?
        ORDER BY rowid DESC
        LIMIT 1
        """,
        (external_workout_id,),
    ).fetchone()
    if row is None or row["action"] != "link":
        return None
    return dict(row)


def link_workout(
    conn: sqlite3.Connection,
    *,
    external_workout_id: str,
    session_id: str,
    method: str,
    band_version: str,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Link a workout to a session. One active link per workout; relinking needs an unlink first."""
    if method not in METHODS:
        raise CardioIngestError(f"unknown method {method!r}")
    if confidence is not None and not 0 <= confidence <= 1:
        raise CardioIngestError("confidence must be within 0..1")
    with db.transaction(conn):
        if get_workout_by_id(conn, external_workout_id) is None:
            raise CardioIngestError(f"unknown workout {external_workout_id!r}")
        current = active_link(conn, external_workout_id)
        if current is not None:
            raise CardioIngestError(
                f"workout {external_workout_id} is already linked to {current['session_id']}"
            )
        link_id = uuid.uuid4().hex
        try:
            conn.execute(
                """
                INSERT INTO workout_link (
                    link_id, external_workout_id, session_id, action, method, band_version,
                    confidence
                ) VALUES (?,?,?, 'link', ?,?,?)
                """,
                (link_id, external_workout_id, session_id, method, band_version, confidence),
            )
        except sqlite3.IntegrityError as exc:
            raise CardioIngestError(f"cannot link to session {session_id!r}: {exc}") from exc
    row = conn.execute("SELECT * FROM workout_link WHERE link_id = ?", (link_id,)).fetchone()
    assert row is not None
    return dict(row)


def unlink_workout(conn: sqlite3.Connection, *, external_workout_id: str) -> dict[str, Any]:
    """Retire the workout's active link by appending an unlink event."""
    with db.transaction(conn):
        current = active_link(conn, external_workout_id)
        if current is None:
            raise CardioIngestError(f"workout {external_workout_id} has no active link")
        link_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO workout_link (
                link_id, external_workout_id, session_id, action, method, band_version,
                supersedes_id
            ) VALUES (?,?,?, 'unlink', ?,?,?)
            """,
            (
                link_id,
                external_workout_id,
                current["session_id"],
                current["method"],
                current["band_version"],
                current["link_id"],
            ),
        )
    row = conn.execute("SELECT * FROM workout_link WHERE link_id = ?", (link_id,)).fetchone()
    assert row is not None
    return dict(row)


def record_status(
    conn: sqlite3.Connection,
    *,
    external_workout_id: str,
    status: str,
    detail: str | None = None,
) -> int:
    """Append an absence/deletion/reappearance event; return its event id."""
    if status not in STATUSES:
        raise CardioIngestError(f"unknown status {status!r}")
    if get_workout_by_id(conn, external_workout_id) is None:
        raise CardioIngestError(f"unknown workout {external_workout_id!r}")
    cursor = conn.execute(
        "INSERT INTO external_status_event (external_workout_id, status, detail) VALUES (?,?,?)",
        (external_workout_id, status, detail),
    )
    return int(cursor.lastrowid or 0)


def current_status(conn: sqlite3.Connection, external_workout_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT status FROM external_status_event
        WHERE external_workout_id = ?
        ORDER BY event_id DESC
        LIMIT 1
        """,
        (external_workout_id,),
    ).fetchone()
    return str(row["status"]) if row is not None else None


def set_sync_state(conn: sqlite3.Connection, name: str, value: str, *, updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO cardio_sync_state (name, value, updated_at) VALUES (?,?,?)
        ON CONFLICT(name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (name, str(value), utc_iso(updated_at, field="updated_at")),
    )


def get_sync_state(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT value FROM cardio_sync_state WHERE name = ?", (name,)).fetchone()
    return str(row["value"]) if row is not None else None


# VO2max is a periodic outcome, not daily state, so it lives in `measurement` beside body-fat and
# steps (#0064 added external_id/measured_at for exactly this). The declaration matches the
# existing config metric so a machine that already has it is left alone.
VO2MAX_METRIC = {
    "metric_key": "vo2max",
    "label": "VO2max estimate",
    "higher_is_better": 1,
    "aggregation": "last",
    "scale_min": 10.0,
    "scale_max": 90.0,
    "unit": "ml/kg/min",
}


def record_vo2max(
    conn: sqlite3.Connection,
    *,
    external_id: str,
    measured_at: str,
    value: float,
    method: str,
    noted_at: str,
) -> bool:
    """Record one VO2max estimate; return True when it is new.

    Idempotency is `measurement.external_id`, because `measurement_id` is a fresh uuid per insert
    and a re-run would otherwise duplicate the whole series. `method` carries the source ("Apple
    Watch", "Athlytic") so two algorithms never merge into one trend.
    """
    if not 0 < float(value) < 100:
        raise CardioIngestError(f"implausible VO2max {value!r}")
    when = utc_iso(measured_at, field="measured_at")
    conn.execute(
        """
        INSERT OR IGNORE INTO metric_definition (
            metric_key, label, scale_min, scale_max, higher_is_better, aggregation, unit, source
        ) VALUES (:metric_key, :label, :scale_min, :scale_max, :higher_is_better,
                  :aggregation, :unit, 'config')
        """,
        VO2MAX_METRIC,
    )
    # INSERT OR IGNORE, not ON CONFLICT: the uniqueness this relies on is a *partial* index, and
    # SQLite only accepts a partial-index conflict target with its predicate spelled out. The only
    # other unique constraint is the random primary key, so ignoring is unambiguous here.
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO measurement (
            measurement_id, metric_key, measured_on, value, method, source, external_id,
            measured_at
        ) VALUES (?, 'vo2max', ?, ?, ?, 'device', ?, ?)
        """,
        (uuid.uuid4().hex, when[:10], float(value), method, external_id, when),
    )
    return cursor.rowcount == 1
