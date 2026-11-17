"""Migration 0064 adds the cardio corpus without touching existing rows."""

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
        if path.name.startswith("0064"):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    db.migrate(conn, partial)
    conn.execute(
        "INSERT INTO session (session_id, occurred_on, set_count, exercise_count) "
        "VALUES ('s-1', '2026-11-10', 20, 4)"
    )
    conn.execute(
        "INSERT INTO measurement (measurement_id, metric_key, measured_on, value, method, source) "
        "VALUES ('m-1', 'body_fat_pct', '2026-11-01', 18.4, 'caliper', 'user')"
    )
    conn.commit()
    return conn


def _workout(conn, key="k-0123456789abcdef", activity="HKWorkoutActivityTypeRunning"):
    conn.execute(
        "INSERT INTO external_workout (external_workout_id, external_key, origin, activity_type, "
        "started_at, ended_at, duration_s, source_name, imported_at) "
        "VALUES ('w-1', ?, 'export', ?, '2026-11-10T08:00:00+00:00', "
        "        '2026-11-10T08:40:00+00:00', 2400, 'Apple Watch', "
        "        '2026-11-17T18:00:00+00:00')",
        (key, activity),
    )


def test_preserves_existing_rows_and_adds_columns(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        assert conn.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1
        rows = conn.execute(
            "SELECT measurement_id, value, external_id, measured_at FROM measurement"
        ).fetchall()
        assert [row["measurement_id"] for row in rows] == ["m-1"]
        assert rows[0]["external_id"] is None
        assert rows[0]["measured_at"] is None
        assert rows[0]["value"] == pytest.approx(18.4)
    finally:
        conn.close()


def test_measurement_external_id_is_idempotent_but_tolerant_of_null(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        # Definitions are seeded per environment, not by migration; declare the one we use.
        conn.execute(
            "INSERT INTO metric_definition (metric_key, label, higher_is_better, aggregation, unit) "
            "VALUES ('vo2max', 'VO2max estimate', 1, 'last', 'ml/kg/min')"
        )
        insert = (
            "INSERT INTO measurement (measurement_id, metric_key, measured_on, value, source, "
            "external_id) VALUES (?, 'vo2max', '2026-11-02', 51.2, 'device', ?)"
        )
        conn.execute(insert, ("m-2", None))
        conn.execute(insert, ("m-3", None))  # NULLs do not collide
        conn.execute(insert, ("m-4", "sample-abc"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("m-5", "sample-abc"))
    finally:
        conn.close()


def test_append_only_triggers(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        _workout(conn)
        conn.execute(
            "INSERT INTO workout_link (link_id, external_workout_id, session_id, action, method, "
            "band_version) VALUES ('l-1', 'w-1', 's-1', 'link', 'explicit', 'link_v1')"
        )
        conn.execute(
            "INSERT INTO external_status_event (external_workout_id, status) "
            "VALUES ('w-1', 'absent_from_source')"
        )
        for statement in (
            "UPDATE external_workout SET duration_s = 1",
            "DELETE FROM external_workout",
            "UPDATE workout_link SET method = 'manual'",
            "DELETE FROM workout_link",
            "UPDATE external_status_event SET status = 'reappeared'",
            "DELETE FROM external_status_event",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(statement)
    finally:
        conn.close()


def test_sample_association_must_agree_with_workout_id(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        _workout(conn)
        insert = (
            "INSERT INTO health_sample (sample_key, external_workout_id, kind, sampled_at, value, "
            "unit, association, source_name, imported_at) "
            "VALUES (?, ?, 'heart_rate', '2026-11-10T08:20:00+00:00', ?, 'count/min', ?, "
            "        'Apple Watch', '2026-11-17T18:00:00+00:00')"
        )
        conn.execute(insert, ("s-a", "w-1", 150.0, "workout"))
        conn.execute(insert, ("s-b", "w-1", 120.0, "tail"))
        conn.execute(insert, ("s-c", None, 70.0, "none"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("s-d", None, 140.0, "workout"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("s-e", "w-1", 140.0, "none"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("s-f", None, 400.0, "none"))  # impossible heart rate
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("s-g", "missing", 140.0, "workout"))  # FK enforced
    finally:
        conn.close()


def test_link_events_encode_action_consistency(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        _workout(conn)
        insert = (
            "INSERT INTO workout_link (link_id, external_workout_id, session_id, action, method, "
            "band_version, supersedes_id) VALUES (?, 'w-1', 's-1', ?, 'day_containment', "
            "        'link_v1', ?)"
        )
        conn.execute(insert, ("l-1", "link", None))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("l-2", "link", "l-1"))
        conn.execute(insert, ("l-3", "unlink", "l-1"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("l-4", "unlink", None))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO workout_link (link_id, external_workout_id, session_id, action, "
                "method, band_version) VALUES ('l-5', 'w-1', 'missing', 'link', 'explicit', 'v1')"
            )
    finally:
        conn.close()


def test_sync_state_is_mutable_while_history_is_not(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        conn.execute(
            "INSERT INTO cardio_sync_state (name, value, updated_at) "
            "VALUES ('history_cutoff', '2026-11-17T17:49:34+00:00', '2026-11-17T18:00:00+00:00')"
        )
        conn.execute(
            "UPDATE cardio_sync_state SET value = '2026-11-17T18:30:00+00:00' "
            "WHERE name = 'history_cutoff'"
        )
        assert conn.execute(
            "SELECT value FROM cardio_sync_state WHERE name = 'history_cutoff'"
        ).fetchone()[0] == "2026-11-17T18:30:00+00:00"
    finally:
        conn.close()
