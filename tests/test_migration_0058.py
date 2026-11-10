"""Migration 0058 adds watch devices, plan targeting, ownership and idle without data loss."""

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
        if path.name.startswith("0058"):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    db.migrate(conn, partial)
    conn.execute(
        "INSERT INTO ios_device (device_id, label, token_hash, created_at) "
        "VALUES ('phone-1', 'iPhone', 'hash-1', '2026-01-02T09:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO ios_issued_plan "
        "(issued_plan_id, device_id, status, requested_session_type, session_type, "
        " for_date, plan_json, readiness_json, created_at, request_expires_at, "
        " plan_expires_at) "
        "VALUES ('plan-1', 'phone-1', 'ready', 'A', 'A', '2026-01-02', '{}', '{}', "
        "        '2026-01-02T09:00:00+00:00', '2026-01-02T09:15:00+00:00', "
        "        '2026-01-02T10:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO workout_session "
        "(workout_id, for_date, status, plan_json, readiness_json, started_at) "
        "VALUES ('w-1', '2026-01-02', 'in_progress', '{}', '{}', "
        "        '2026-01-02T10:00:00+00:00')"
    )
    conn.commit()
    return conn


def test_backfills_legacy_rows_and_adds_defaults(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        device = conn.execute("SELECT * FROM ios_device WHERE device_id = 'phone-1'").fetchone()
        assert device["kind"] == "phone"
        assert device["parent_device_id"] is None
        assert device["credential_epoch"] == 0

        plan = conn.execute("SELECT * FROM ios_issued_plan WHERE issued_plan_id = 'plan-1'").fetchone()
        assert plan["execution_target"] == "phone"
        assert plan["target_device_id"] == "phone-1"

        workout = conn.execute("SELECT * FROM workout_session WHERE workout_id = 'w-1'").fetchone()
        assert workout["owner_device_id"] is None
        assert workout["plan_revision"] == 0
        assert workout["last_activity_at"] == "2026-01-02T10:00:00+00:00"

        indexes = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "idx_ios_device_active_watch" in indexes
        assert "idx_ios_issued_plan_live" in indexes
        assert "idx_workout_idle" in indexes
    finally:
        conn.close()


def test_one_active_watch_per_parent(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        conn.execute(
            "INSERT INTO ios_device "
            "(device_id, label, token_hash, created_at, kind, parent_device_id, credential_epoch) "
            "VALUES ('watch-1', 'Watch', 'hash-2', '2026-01-02T09:00:00+00:00', "
            "        'watch', 'phone-1', 1)"
        )
        conn.commit()
        with pytest.raises(IntegrityError):
            conn.execute(
                "INSERT INTO ios_device "
                "(device_id, label, token_hash, created_at, kind, parent_device_id, credential_epoch) "
                "VALUES ('watch-2', 'Watch 2', 'hash-3', '2026-01-02T09:00:00+00:00', "
                "        'watch', 'phone-1', 2)"
            )
        conn.execute(
            "UPDATE ios_device SET revoked_at = '2026-01-02T09:05:00+00:00' "
            "WHERE device_id = 'watch-1'"
        )
        conn.execute(
            "INSERT INTO ios_device "
            "(device_id, label, token_hash, created_at, kind, parent_device_id, credential_epoch) "
            "VALUES ('watch-2', 'Watch 2', 'hash-3', '2026-01-02T09:00:00+00:00', "
            "        'watch', 'phone-1', 2)"
        )
        conn.commit()
    finally:
        conn.close()


def test_documented_rollback_drops_the_added_surface(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        conn.executescript(
            """
            BEGIN IMMEDIATE;
            DROP INDEX idx_workout_idle;
            ALTER TABLE workout_session DROP COLUMN last_activity_at;
            ALTER TABLE workout_session DROP COLUMN plan_revision;
            ALTER TABLE workout_session DROP COLUMN owner_device_id;
            DROP INDEX idx_ios_issued_plan_live;
            CREATE UNIQUE INDEX idx_ios_issued_plan_live
                ON ios_issued_plan(device_id)
                WHERE consumed_at IS NULL AND superseded_at IS NULL;
            ALTER TABLE ios_issued_plan DROP COLUMN execution_target;
            ALTER TABLE ios_issued_plan DROP COLUMN target_device_id;
            DROP INDEX idx_ios_device_parent;
            DROP INDEX idx_ios_device_active_watch;
            ALTER TABLE ios_device DROP COLUMN credential_epoch;
            ALTER TABLE ios_device DROP COLUMN parent_device_id;
            ALTER TABLE ios_device DROP COLUMN kind;
            COMMIT;
            """
        )
        assert "kind" not in {row[1] for row in conn.execute("PRAGMA table_info(ios_device)")}
        assert "execution_target" not in {
            row[1] for row in conn.execute("PRAGMA table_info(ios_issued_plan)")
        }
        assert "owner_device_id" not in {
            row[1] for row in conn.execute("PRAGMA table_info(workout_session)")
        }
    finally:
        conn.close()
