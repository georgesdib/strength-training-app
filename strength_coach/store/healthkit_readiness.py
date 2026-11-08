"""Append-only HealthKit HRV/RHR observations for Phase 3A.

The canonical readiness query reads the latest observation per date/field. This module never
merges readiness and never computes a score; it only stores and returns observations/provenance.
"""

from __future__ import annotations

import uuid
from typing import Any

FIELDS = ("hrv_ms", "rhr_bpm")
SOURCE_CLASSES = ("apple_watch", "non_apple_watch", "unknown")

_IMMUTABLE_FIELDS = (
    "value",
    "sample_at",
    "source_name",
    "source_bundle_id",
    "source_class",
    "source_model",
    "source_manufacturer",
)


class HealthKitObservationConflict(ValueError):
    """A HealthKit sample identity was reused with changed immutable data."""


def provenance(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": row["value"],
        "sample_id": row["sample_id"],
        "sample_at": row["sample_at"],
        "source_name": row["source_name"],
        "source_bundle_id": row["source_bundle_id"],
        "source_class": row["source_class"],
        "source_model": row["source_model"],
        "source_manufacturer": row["source_manufacturer"],
        "imported_at": row["imported_at"],
    }


def latest_observations(conn, start: str, end: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Latest observation per date/field in the inclusive window, with provenance.

    Ordering is stable: sample timestamp, then import time, then observation id. The last row for
    a date/field is therefore the effective observation for that field.
    """
    rows = conn.execute(
        """
        SELECT * FROM healthkit_readiness
         WHERE on_date BETWEEN ? AND ?
         ORDER BY on_date, field, sample_at, imported_at, observation_id
        """,
        (str(start), str(end)),
    ).fetchall()
    latest: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        latest.setdefault(str(item["on_date"]), {})[str(item["field"])] = item
    return latest


def latest_for_date(conn, on_date: str) -> dict[str, dict[str, Any]]:
    rows = latest_observations(conn, str(on_date), str(on_date))
    return {
        field: provenance(item)
        for field, item in rows.get(str(on_date), {}).items()
    }


def record_observations(
    conn,
    *,
    device_id: str,
    on_date: str,
    samples: list[dict[str, Any]],
    imported_at: str,
) -> int:
    """Insert accepted observations after checking every identity.

    All checks run before any insert. The caller owns the surrounding transaction, so a conflict
    also prevents an operation receipt from being stored.
    """
    seen_fields: set[str] = set()
    existing_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for sample in samples:
        field = str(sample["field"])
        if field in seen_fields:
            raise ValueError("duplicate HealthKit field in request")
        seen_fields.add(field)
        if field not in FIELDS:
            raise ValueError(f"unknown HealthKit field {field!r}")
        row = conn.execute(
            "SELECT * FROM healthkit_readiness WHERE device_id = ? AND field = ? AND sample_id = ?",
            (str(device_id), field, str(sample["sample_id"])),
        ).fetchone()
        if row is None:
            continue
        existing = dict(row)
        if existing["on_date"] != str(on_date) or any(
            existing[name] != sample[name] for name in _IMMUTABLE_FIELDS
        ):
            raise HealthKitObservationConflict(
                f"HealthKit sample {sample['sample_id']} conflicts with its stored observation"
            )
        existing_by_key[(field, str(sample["sample_id"]))] = existing

    inserted = 0
    for sample in samples:
        key = (str(sample["field"]), str(sample["sample_id"]))
        if key in existing_by_key:
            continue
        conn.execute(
            """
            INSERT INTO healthkit_readiness (
                observation_id, device_id, on_date, field, value, sample_id, sample_at,
                source_name, source_bundle_id, source_class, source_model,
                source_manufacturer, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                str(device_id),
                str(on_date),
                str(sample["field"]),
                float(sample["value"]),
                str(sample["sample_id"]),
                str(sample["sample_at"]),
                str(sample["source_name"]),
                sample.get("source_bundle_id"),
                str(sample["source_class"]),
                sample.get("source_model"),
                sample.get("source_manufacturer"),
                str(imported_at),
            ),
        )
        inserted += 1
    return inserted
