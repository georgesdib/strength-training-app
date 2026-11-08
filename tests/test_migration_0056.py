"""Migration 0056 — the R7 rebuild must preserve every Phase 2 issued-plan row.

The migration copies the whole table, so these tests pin the mapping documented in
docs/design/IOS-R7-CONTRACT.md §3.1: nothing is dropped, nothing is invented, and a corrupt
legacy row aborts instead of disappearing.
"""

from __future__ import annotations

import json
import shutil
import sqlite3

import pytest

from strength_coach.prescribe import persistence as prescription_persistence
from strength_coach.store import db

PLAN = {
    "for_date": "2026-01-02",
    "session_type": "squat",
    "fallback_level": "full",
    "rule_document_version": "test",
    "calibration_ids": [],
    "items": [
        {
            "exercise_id": "competition_squat",
            "sets": 3,
            "reps_low": 5,
            "reps_high": 5,
            "load_kg": 100.0,
            "load_basis": "external",
            "rir_target": 2,
            "essential": True,
        }
    ],
    "warnings": [],
    "notes": {},
}


def _legacy_connection(tmp_path):
    """A database at the Phase 2 schema (everything except 0056)."""
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith("0056"):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    db.migrate(conn, partial)
    return conn


def _device(conn, device_id="device-a"):
    conn.execute(
        "INSERT INTO ios_device (device_id, label, token_hash, created_at) "
        "VALUES (?, 'iPhone', ?, '2026-01-01T00:00:00+00:00')",
        (device_id, "hash-" + device_id),
    )


def _workout(conn, workout_id, prescription_id):
    conn.execute(
        "INSERT INTO workout_session "
        "(workout_id, prescription_id, for_date, session_type, status, plan_json, "
        " readiness_json, started_at) "
        "VALUES (?, ?, '2026-01-02', 'squat', 'in_progress', ?, '{}', "
        "        '2026-01-02T10:00:00+00:00')",
        (workout_id, prescription_id, json.dumps(PLAN)),
    )


def _legacy_plan(conn, *, plan_id, prescription_id, device="device-a",
                 created="2026-01-02T08:00:00+00:00",
                 expires="2026-01-02T09:00:00+00:00",
                 consumed=None, superseded=None, workout_id=None):
    conn.execute(
        "INSERT INTO ios_issued_plan "
        "(issued_plan_id, device_id, prescription_id, for_date, session_type, plan_json, "
        " readiness_json, readiness_ack, created_at, expires_at, consumed_at, "
        " superseded_at, workout_id) "
        "VALUES (?, ?, ?, '2026-01-02', 'squat', ?, '{}', 0, ?, ?, ?, ?, ?)",
        (plan_id, device, prescription_id, json.dumps(PLAN), created, expires,
         consumed, superseded, workout_id),
    )


def _migrate(conn):
    return db.migrate(conn)


# --- preservation ----------------------------------------------------------


def test_migration_preserves_every_legacy_row(tmp_path):
    conn = _legacy_connection(tmp_path)
    try:
        # One live row per device is enforced by the partial unique index, so each legacy row
        # gets its own device unless it is consumed/superseded.
        for device in ("device-a", "device-b", "device-c", "device-d"):
            _device(conn, device)
        live_prescription = prescription_persistence.store_plan(conn, PLAN)
        consumed_prescription = prescription_persistence.store_plan(conn, PLAN)
        superseded_prescription = prescription_persistence.store_plan(conn, PLAN)
        expired_prescription = prescription_persistence.store_plan(conn, PLAN)
        _workout(conn, "workout-1", consumed_prescription)

        _legacy_plan(conn, plan_id="live", prescription_id=live_prescription,
                     device="device-a", expires="2999-01-01T00:00:00+00:00")
        _legacy_plan(conn, plan_id="consumed", prescription_id=consumed_prescription,
                     device="device-b", consumed="2026-01-02T08:30:00+00:00",
                     workout_id="workout-1")
        _legacy_plan(conn, plan_id="superseded", prescription_id=superseded_prescription,
                     device="device-c", superseded="2026-01-02T08:10:00+00:00")
        _legacy_plan(conn, plan_id="expired", prescription_id=expired_prescription,
                     device="device-d")

        before_prescriptions = conn.execute(
            "SELECT prescription_id, run_id, for_date, session_type FROM prescription "
            "ORDER BY prescription_id"
        ).fetchall()
        before_prescription_ids = [row[0] for row in before_prescriptions]
        before_items = conn.execute(
            "SELECT COUNT(*) FROM prescription_item"
        ).fetchone()[0]

        assert _migrate(conn) == ["0056"]

        rows = {
            row["issued_plan_id"]: dict(row)
            for row in conn.execute("SELECT * FROM ios_issued_plan")
        }
        assert set(rows) == {"live", "consumed", "superseded", "expired"}

        # Every legacy row produced a plan, so every one is 'ready'.
        assert {row["status"] for row in rows.values()} == {"ready"}
        # The deadlines are reused, never extended: a legacy plan keeps the life it had.
        for row in rows.values():
            assert row["request_expires_at"] == row["plan_expires_at"]

        assert rows["live"]["consumed_at"] is None
        assert rows["live"]["superseded_at"] is None
        assert rows["live"]["prescription_id"] == live_prescription
        assert rows["live"]["plan_expires_at"] == "2999-01-01T00:00:00+00:00"

        assert rows["consumed"]["consumed_at"] == "2026-01-02T08:30:00+00:00"
        assert rows["consumed"]["workout_id"] == "workout-1"
        assert rows["consumed"]["prescription_id"] == consumed_prescription

        assert rows["superseded"]["superseded_at"] == "2026-01-02T08:10:00+00:00"
        assert rows["superseded"]["prescription_id"] == superseded_prescription

        # An expired-but-unstarted row is copied verbatim and is simply inert.
        assert rows["expired"]["plan_expires_at"] == "2026-01-02T09:00:00+00:00"
        assert rows["expired"]["consumed_at"] is None

        # Prescriptions are untouched: same ids, same rows, no duplication.
        after_prescriptions = conn.execute(
            "SELECT prescription_id, run_id, for_date, session_type FROM prescription "
            "ORDER BY prescription_id"
        ).fetchall()
        assert [row[0] for row in after_prescriptions] == before_prescription_ids
        assert conn.execute("SELECT COUNT(*) FROM prescription_item").fetchone()[0] == before_items
    finally:
        conn.close()


def test_migration_keeps_receipts_and_the_live_index(tmp_path):
    conn = _legacy_connection(tmp_path)
    try:
        _device(conn)
        prescription_id = prescription_persistence.store_plan(conn, PLAN)
        _legacy_plan(conn, plan_id="plan-1", prescription_id=prescription_id)
        conn.execute(
            "INSERT INTO ios_operation_receipt "
            "(device_id, operation_id, route, request_hash, response_status, response_json, "
            " created_at, expires_at) "
            "VALUES ('device-a', 'op-1', 'POST /api/ios/v1/prescriptions', 'digest', 200, "
            "        '{\"issued_plan_id\":\"plan-1\"}', "
            "        '2026-01-01T00:00:00+00:00', '2999-01-01T00:00:00+00:00')"
        )

        assert _migrate(conn) == ["0056"]

        receipt = conn.execute(
            "SELECT response_status, response_json FROM ios_operation_receipt "
            "WHERE operation_id = 'op-1'"
        ).fetchone()
        assert receipt["response_status"] == 200
        assert json.loads(receipt["response_json"]) == {"issued_plan_id": "plan-1"}

        # One live row per device is still enforced by the partial unique index.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ios_issued_plan "
                "(issued_plan_id, device_id, status, requested_session_type, settings_json, "
                " build_inputs_json, for_date, readiness_json, readiness_ack, created_at, "
                " request_expires_at) "
                "VALUES ('plan-2', 'device-a', 'queued', 'auto', '{}', '{}', '2026-01-02', "
                "        '{}', 0, '2026-01-02T09:00:00+00:00', "
                "        '2026-01-02T09:15:00+00:00')"
            )
    finally:
        conn.close()


def test_migration_aborts_on_a_dangling_prescription(tmp_path):
    conn = _legacy_connection(tmp_path)
    try:
        _device(conn, "device-a")
        _device(conn, "device-b")
        prescription_id = prescription_persistence.store_plan(conn, PLAN)
        _legacy_plan(conn, plan_id="good", prescription_id=prescription_id)
        # Simulate corruption that Phase 2 could not have produced but a manual edit can.
        conn.execute("PRAGMA foreign_keys = OFF")
        _legacy_plan(conn, plan_id="bad", prescription_id="missing-prescription",
                     device="device-b")
        conn.execute("PRAGMA foreign_keys = ON")

        with pytest.raises(db.MigrationError):
            _migrate(conn)

        # The rebuild rolled back: the Phase 2 table is intact, with both rows.
        rows = conn.execute(
            "SELECT issued_plan_id FROM ios_issued_plan ORDER BY issued_plan_id"
        ).fetchall()
        assert [row[0] for row in rows] == ["bad", "good"]
        applied = [row[0] for row in conn.execute(
            "SELECT version FROM schema_migration WHERE version = '0056'"
        )]
        assert applied == []
    finally:
        conn.close()
