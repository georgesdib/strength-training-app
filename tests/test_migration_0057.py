"""Migration 0057 adds execution telemetry without touching existing workout data."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from strength_coach.store import db


def _connection(tmp_path):
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith("0057"):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    db.migrate(conn, partial)
    conn.execute(
        "INSERT INTO workout_session "
        "(workout_id, for_date, status, plan_json, readiness_json, started_at) "
        "VALUES ('w-1', '2026-01-02', 'in_progress', '{}', '{}', "
        "        '2026-01-02T10:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO workout_set "
        "(workout_id, exercise_id, set_index, load_kg, reps, rir) "
        "VALUES ('w-1', 'competition_squat', 1, 100, 5, 2)"
    )
    conn.commit()
    return conn


def test_migration_preserves_workout_rows_and_adds_append_only_table(tmp_path):
    conn = _connection(tmp_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM workout_session").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM workout_set").fetchone()[0] == 1
        db.migrate(conn)
        assert conn.execute("SELECT COUNT(*) FROM workout_session").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM workout_set").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM workout_execution_event").fetchone()[0] == 0
    finally:
        conn.close()


def test_execution_events_are_append_only(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        conn.execute(
            "INSERT INTO workout_execution_event "
            "(event_id, workout_id, event_type, occurred_at, received_at, device_id) "
            "VALUES ('e-1', 'w-1', 'set_started', "
            "        '2026-01-02T10:00:01+00:00', '2026-01-02T10:00:02+00:00', 'd-1')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE workout_execution_event SET event_type = 'set_completed' "
                "WHERE event_id = 'e-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM workout_execution_event WHERE event_id = 'e-1'")
    finally:
        conn.close()
