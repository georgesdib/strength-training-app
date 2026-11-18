"""Append-only recovery-HRV observations.

One row per night: the median SDNN of the samples the client selected in that night's window.
The client computes the value (it owns the HealthKit query and the night window); this module only
stores and returns the series, exactly like `healthkit_readiness` does for raw samples.
"""

from __future__ import annotations

from typing import Any

SOURCE_CLASSES = ("apple_watch", "non_apple_watch", "unknown")

_IMMUTABLE_FIELDS = ("on_date", "value", "sample_at", "source_name", "source_class")


class HRVRecoveryConflict(ValueError):
    """A recovery sample id was reused with changed immutable data."""


def provenance(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "value": row["value"],
        "sample_id": row["sample_id"],
        "sample_at": row["sample_at"],
        "source_name": row["source_name"],
        "source_class": row["source_class"],
        "sample_count": row["sample_count"],
        "imported_at": row["imported_at"],
    }


def latest_by_date(conn, start: str, end: str) -> dict[str, dict[str, Any]]:
    """The winning observation per date in the inclusive window.

    A later import wins, except that a night computed from more samples wins over a partial one:
    a truncated query window produces a valid-looking median from fewer readings, and that must
    not displace the complete night. Ties fall back to sample id for determinism.
    """
    rows = conn.execute(
        """
        SELECT * FROM hrv_recovery
         WHERE on_date BETWEEN ? AND ?
         ORDER BY on_date, sample_count, imported_at, sample_id
        """,
        (str(start), str(end)),
    ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[str(row["on_date"])] = dict(row)
    return latest


def record_samples(
    conn,
    *,
    device_id: str,
    samples: list[dict[str, Any]],
    imported_at: str,
) -> tuple[list[str], list[str]]:
    """Insert samples, returning (accepted, duplicates).

    All identity checks run before any insert. The caller owns the transaction, so a conflict also
    prevents an operation receipt from being stored.
    """
    seen: set[str] = set()
    existing_ids: set[str] = set()
    for sample in samples:
        sample_id = str(sample["sample_id"])
        if sample_id in seen:
            raise ValueError("duplicate sample_id in request")
        seen.add(sample_id)
        row = conn.execute(
            "SELECT * FROM hrv_recovery WHERE device_id = ? AND sample_id = ?",
            (str(device_id), sample_id),
        ).fetchone()
        if row is None:
            continue
        existing = dict(row)
        changed = [
            name for name in _IMMUTABLE_FIELDS if existing[name] != sample[name]
        ]
        if changed:
            raise HRVRecoveryConflict(
                f"recovery sample {sample_id} conflicts with its stored observation "
                f"on {', '.join(changed)}"
            )
        existing_ids.add(sample_id)

    accepted: list[str] = []
    duplicates: list[str] = []
    for sample in samples:
        sample_id = str(sample["sample_id"])
        if sample_id in existing_ids:
            duplicates.append(sample_id)
            continue
        conn.execute(
            """
            INSERT INTO hrv_recovery (
                sample_id, device_id, on_date, value, sample_at,
                source_name, source_class, sample_count, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                str(device_id),
                str(sample["on_date"]),
                float(sample["value"]),
                str(sample["sample_at"]),
                str(sample["source_name"]),
                str(sample["source_class"]),
                int(sample.get("sample_count") or 0),
                str(imported_at),
            ),
        )
        accepted.append(sample_id)
    return accepted, duplicates
