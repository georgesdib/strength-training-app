"""Canonical readiness merge with Phase 3A HealthKit observations."""

from __future__ import annotations

import datetime as dt
import uuid

from strength_coach.features import readiness_score
from strength_coach.store import db, healthkit_readiness, queries, repositories

DEVICE_ID = "device-phase3a"


def _store():
    store = db.Store(":memory:")
    store.connection.execute(
        "INSERT INTO ios_device (device_id, label, token_hash, created_at) "
        "VALUES (?, ?, ?, ?)",
        (DEVICE_ID, "test", "hash", "2024-01-01T00:00:00+00:00"),
    )
    return store


def _observation(day: str, field: str, value: float, *, sample_id: str | None = None):
    return {
        "field": field,
        "value": value,
        "sample_id": sample_id or uuid.uuid4().hex,
        "sample_at": f"{day}T06:00:00+00:00",
        "source_name": "Apple Watch",
        "source_bundle_id": "com.apple.health",
        "source_class": "apple_watch",
        "source_model": "Watch6,18",
        "source_manufacturer": "Apple Inc.",
    }


def _base_day(conn, day: str, *, hrv: float = 40.0, rhr: float = 60.0):
    conn.execute(
        """
        INSERT INTO readiness_day
            (on_date, sleep, energy, mood, soreness, stress, hrv_ms, rhr_bpm)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (day, 4, 3, 4, 4, 3, hrv, rhr),
    )


def test_healthkit_values_flow_through_all_readiness_consumers():
    store = _store()
    try:
        conn = store.connection
        today = "2024-01-12"
        _base_day(conn, today)
        for offset in range(1, 12):
            day = (dt.date.fromisoformat(today) - dt.timedelta(days=offset)).isoformat()
            healthkit_readiness.record_observations(
                conn, device_id=DEVICE_ID, on_date=day,
                samples=[
                    _observation(day, "hrv_ms", 50.0 + offset),
                    _observation(day, "rhr_bpm", 50.0),
                ],
                imported_at="2024-01-12T07:00:00+00:00",
            )
        healthkit_readiness.record_observations(
            conn, device_id=DEVICE_ID, on_date=today,
            samples=[
                _observation(today, "hrv_ms", 55.0),
                _observation(today, "rhr_bpm", 50.0),
            ],
            imported_at="2024-01-12T07:00:00+00:00",
        )

        day = queries.readiness_day(conn, today)
        assert day["hrv_ms"] == 55.0
        assert day["rhr_bpm"] == 50.0
        assert day["sources"]["hrv_ms"] == "healthkit"
        assert day["sources"]["rhr_bpm"] == "healthkit"
        assert day["healthkit"]["hrv_ms"]["source_class"] == "apple_watch"
        assert day["sleep"] == 4.0
        assert day["sources"]["sleep"] == "import"
        assert conn.execute(
            "SELECT hrv_ms FROM readiness_day WHERE on_date = ?", (today,)
        ).fetchone()[0] == 40.0
        assert conn.execute("SELECT COUNT(*) FROM readiness_entry").fetchone()[0] == 0

        series = queries.readiness_series(conn, today, today, ("hrv_ms", "rhr_bpm"))
        assert series == [{
            "date": today,
            "hrv_ms": 55.0,
            "rhr_bpm": 50.0,
            "sources": {"hrv_ms": "healthkit", "rhr_bpm": "healthkit"},
            "healthkit": day["healthkit"],
        }]
        history = queries.readiness_history(conn, "2024-01-13", 28)
        assert any(row["on_date"] == today and row["hrv_ms"] == 55.0 for row in history)
        assert queries.readiness_dates(conn, today, today) == [today]

        assessment = readiness_score.compute(conn, today)
        assert assessment.status == "ready"
        assert any(c.field == "hrv_ms" and c.value == 55.0 for c in assessment.components)
        assert any(c.field == "rhr_bpm" and c.value == 50.0 for c in assessment.components)

        repositories.append_readiness_entry(conn, on_date=today, field="hrv_ms", value=60.0)
        manual = queries.readiness_day(conn, today)
        assert manual["hrv_ms"] == 60.0
        assert manual["sources"]["hrv_ms"] == "manual"
        assert manual["healthkit"]["hrv_ms"]["value"] == 55.0

        healthkit_readiness.record_observations(
            conn, device_id=DEVICE_ID, on_date=today,
            samples=[_observation(today, "hrv_ms", 56.0)],
            imported_at="2024-01-12T07:05:00+00:00",
        )
        after = queries.readiness_day(conn, today)
        assert after["hrv_ms"] == 60.0
        assert after["sources"]["hrv_ms"] == "manual"
        assert after["healthkit"]["hrv_ms"]["value"] == 56.0
    finally:
        store.close()
