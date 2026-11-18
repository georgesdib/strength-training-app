"""Canonical readiness merge with Phase 3A HealthKit observations."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from strength_coach.features import readiness_score
from strength_coach.store import db, healthkit_readiness, hrv_recovery, queries, repositories

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


def _recovery(day: str, value: float, *, sample_id: str | None = None,
              source_class: str = "apple_watch"):
    return {
        "sample_id": sample_id or f"recovery-{day}",
        "on_date": day,
        "value": value,
        "sample_at": f"{day}T07:00:00+00:00",
        "source_name": "Apple Watch",
        "source_class": source_class,
        "sample_count": 3,
    }


def _base_day(conn, day: str, *, hrv: float | None = 40.0, rhr: float = 60.0):
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
            # Readiness reads the recovery series, so each night the baseline needs is here too.
            hrv_recovery.record_samples(
                conn, device_id=DEVICE_ID, samples=[_recovery(day, 40.0 + offset)],
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
        hrv_recovery.record_samples(
            conn, device_id=DEVICE_ID, samples=[_recovery(today, 48.0)],
            imported_at="2024-01-12T07:00:00+00:00",
        )

        day = queries.readiness_day(conn, today)
        assert day["hrv_ms"] == 48.0, "readiness takes the recovery value, not the newest sample"
        assert day["rhr_bpm"] == 50.0
        assert day["sources"]["hrv_ms"] == "hrv_recovery"
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
            "hrv_ms": 48.0,
            "rhr_bpm": 50.0,
            "sources": {"hrv_ms": "hrv_recovery", "rhr_bpm": "healthkit"},
            "healthkit": day["healthkit"],
        }]
        history = queries.readiness_history(conn, "2024-01-13", 28)
        assert any(row["on_date"] == today and row["hrv_ms"] == 48.0 for row in history)
        assert queries.readiness_dates(conn, today, today) == [today]

        assessment = readiness_score.compute(conn, today)
        assert assessment.status == "ready"
        assert any(c.field == "hrv_ms" and c.value == 48.0 for c in assessment.components)
        assert any(c.field == "rhr_bpm" and c.value == 50.0 for c in assessment.components)

        repositories.append_readiness_entry(conn, on_date=today, field="hrv_ms", value=60.0)
        manual = queries.readiness_day(conn, today)
        assert manual["hrv_ms"] == 60.0
        assert manual["sources"]["hrv_ms"] == "manual"
        assert manual["healthkit"]["hrv_ms"]["value"] == 48.0

        healthkit_readiness.record_observations(
            conn, device_id=DEVICE_ID, on_date=today,
            samples=[_observation(today, "hrv_ms", 56.0)],
            imported_at="2024-01-12T07:05:00+00:00",
        )
        after = queries.readiness_day(conn, today)
        # A newer raw sample changes the audit series only; readiness still reads the night's
        # recovery value and the manual entry still wins.
        assert after["hrv_ms"] == 60.0
        assert after["sources"]["hrv_ms"] == "manual"
        assert after["healthkit"]["hrv_ms"]["value"] == 48.0
    finally:
        store.close()


def test_same_sample_after_midnight_is_skipped_not_conflicted():
    store = _store()
    try:
        conn = store.connection
        first = _observation("2024-01-12", "hrv_ms", 55.0, sample_id="sample-midnight")
        inserted = healthkit_readiness.record_observations(
            conn, device_id=DEVICE_ID, on_date="2024-01-12",
            samples=[first], imported_at="2024-01-12T23:55:00+00:00",
        )
        assert inserted == 1

        # The app imports again after midnight and may select the same 48-hour HRV sample.
        again = healthkit_readiness.record_observations(
            conn, device_id=DEVICE_ID, on_date="2024-01-13",
            samples=[first], imported_at="2024-01-13T00:05:00+00:00",
        )
        assert again == 0
        assert conn.execute("SELECT COUNT(*) FROM healthkit_readiness").fetchone()[0] == 1
        row = conn.execute("SELECT on_date FROM healthkit_readiness").fetchone()
        assert row["on_date"] == "2024-01-12"
        assert queries.readiness_day(conn, "2024-01-13") is None
    finally:
        store.close()


def test_raw_healthkit_hrv_is_suppressed_without_a_recovery_night():
    store = _store()
    try:
        conn = store.connection
        today = "2024-01-12"
        _base_day(conn, today, hrv=None)
        healthkit_readiness.record_observations(
            conn, device_id=DEVICE_ID, on_date=today,
            samples=[
                _observation(today, "hrv_ms", 55.0),
                _observation(today, "rhr_bpm", 50.0),
            ],
            imported_at="2024-01-12T07:00:00+00:00",
        )

        day = queries.readiness_day(conn, today)
        assert day["hrv_ms"] is None, "no recovery night means no HRV input"
        assert "hrv_ms" not in day["sources"]
        assert day["rhr_bpm"] == 50.0
        assert conn.execute(
            "SELECT COUNT(*) FROM healthkit_readiness WHERE field = 'hrv_ms'"
        ).fetchone()[0] == 1, "the raw series keeps the sample for audit"

        assessment = readiness_score.compute(conn, today)
        assert not any(c.field == "hrv_ms" for c in assessment.components)
    finally:
        store.close()


def test_recovery_samples_are_idempotent_and_conflict_on_a_changed_value():
    store = _store()
    try:
        conn = store.connection
        today = "2024-01-12"
        accepted, duplicates = hrv_recovery.record_samples(
            conn, device_id=DEVICE_ID, samples=[_recovery(today, 48.0, sample_id="night-1")],
            imported_at="2024-01-12T08:00:00+00:00",
        )
        assert accepted == ["night-1"] and duplicates == []

        again, repeated = hrv_recovery.record_samples(
            conn, device_id=DEVICE_ID, samples=[_recovery(today, 48.0, sample_id="night-1")],
            imported_at="2024-01-12T08:05:00+00:00",
        )
        assert again == [] and repeated == ["night-1"]

        with pytest.raises(hrv_recovery.HRVRecoveryConflict):
            hrv_recovery.record_samples(
                conn, device_id=DEVICE_ID,
                samples=[_recovery(today, 52.0, sample_id="night-1")],
                imported_at="2024-01-12T08:10:00+00:00",
            )
        assert conn.execute("SELECT COUNT(*) FROM hrv_recovery").fetchone()[0] == 1
    finally:
        store.close()


def test_a_later_recovery_sample_for_the_same_night_wins():
    store = _store()
    try:
        conn = store.connection
        today = "2024-01-12"
        hrv_recovery.record_samples(
            conn, device_id=DEVICE_ID, samples=[_recovery(today, 48.0, sample_id="night-1")],
            imported_at="2024-01-12T08:00:00+00:00",
        )
        hrv_recovery.record_samples(
            conn, device_id=DEVICE_ID,
            samples=[{
                **_recovery(today, 52.0, sample_id="night-1b"),
                "sample_at": f"{today}T09:00:00+00:00",
            }],
            imported_at="2024-01-12T09:05:00+00:00",
        )
        latest = hrv_recovery.latest_by_date(conn, today, today)
        assert latest[today]["value"] == 52.0
        assert conn.execute("SELECT COUNT(*) FROM hrv_recovery").fetchone()[0] == 2
    finally:
        store.close()
