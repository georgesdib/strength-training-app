"""Migration 0073 adds performed-set attribution and the execution-change identity."""

from __future__ import annotations

import shutil
from sqlite3 import IntegrityError

import pytest

from strength_coach.store import db


def _connection(tmp_path):
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith("0073"):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    db.migrate(conn, partial)
    conn.execute(
        "INSERT INTO workout_session "
        "(workout_id, for_date, status, plan_json, readiness_json, started_at) "
        "VALUES ('w-1', '2026-11-01', 'in_progress', '{}', '{}', "
        "        '2026-11-01T10:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO workout_set "
        "(workout_id, exercise_id, set_index, load_kg, reps, rir, source, "
        " prescription_item_index, set_role) "
        "VALUES ('w-1', 'ssb_squat', 1, 120.0, 5, 1, 'manual', 0, 'top_set')"
    )
    conn.execute(
        "INSERT INTO workout_event (workout_id, event_type, payload_json) "
        "VALUES ('w-1', 'add_set', '{\"exercise_id\": \"ssb_squat\"}')"
    )
    conn.commit()
    return conn


def test_columns_and_index_are_additive_and_legacy_rows_survive(tmp_path):
    conn = _connection(tmp_path)
    try:
        assert "substitutes_plan_item_index" not in {
            row["name"] for row in conn.execute("PRAGMA table_info(workout_set)")
        }
        db.migrate(conn)
        set_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(workout_set)")
        }
        clean_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(clean_set)")
        }
        assert "substitutes_plan_item_index" in set_columns
        assert "substitutes_plan_item_index" in clean_columns
        row = conn.execute("SELECT * FROM workout_set").fetchone()
        assert row["substitutes_plan_item_index"] is None
        assert row["set_role"] == "top_set"
        event = conn.execute("SELECT * FROM workout_event").fetchone()
        assert event["payload_json"] == '{"exercise_id": "ssb_squat"}'
        indexes = {
            record[0] for record in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "idx_workout_event_client_change" in indexes
    finally:
        conn.close()


def test_a_client_change_identity_is_unique_per_workout(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        conn.execute(
            "INSERT INTO workout_event (workout_id, event_type, payload_json) "
            "VALUES ('w-1', 'substitution', "
            "        '{\"client_event_id\": \"e-1\", \"plan_item_index\": 0}')"
        )
        with pytest.raises(IntegrityError):
            conn.execute(
                "INSERT INTO workout_event (workout_id, event_type, payload_json) "
                "VALUES ('w-1', 'addition', "
                "        '{\"client_event_id\": \"e-1\", \"after_item_index\": 0}')"
            )
        # Legacy rows with no client identity are never blocked by the index.
        conn.rollback()
        conn.execute(
            "INSERT INTO workout_event (workout_id, event_type, payload_json) "
            "VALUES ('w-1', 'add_set', '{}')"
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM workout_event"
        ).fetchone()[0] >= 2
    finally:
        conn.close()
