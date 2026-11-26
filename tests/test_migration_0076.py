"""Migration 0076 gives an issued plan the execution it will become."""

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
        if path.name.startswith("0076"):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    db.migrate(conn, partial)
    for device_id, label in (("phone-1", "Phone"), ("phone-2", "Phone 2")):
        conn.execute(
            "INSERT INTO ios_device (device_id, label, token_hash, created_at) "
            "VALUES (?, ?, ?, '2026-11-23T08:00:00+00:00')",
            (device_id, label, f"hash-{device_id}"),
        )
    for issued_plan_id, device_id in (("plan-1", "phone-1"), ("plan-2", "phone-2")):
        conn.execute(
            "INSERT INTO ios_issued_plan "
            "(issued_plan_id, device_id, status, requested_session_type, for_date, "
            " created_at, request_expires_at) "
            "VALUES (?, ?, 'queued', 'auto', '2026-11-23', "
            "        '2026-11-23T08:00:00+00:00', '2026-11-23T08:10:00+00:00')",
            (issued_plan_id, device_id),
        )
    conn.commit()
    return conn


def test_execution_id_is_additive_and_legacy_rows_stay_null(tmp_path):
    conn = _connection(tmp_path)
    try:
        assert "execution_id" not in {
            row["name"] for row in conn.execute("PRAGMA table_info(ios_issued_plan)")
        }
        db.migrate(conn)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(ios_issued_plan)")
        }
        assert "execution_id" in columns
        rows = conn.execute(
            "SELECT issued_plan_id, execution_id FROM ios_issued_plan ORDER BY issued_plan_id"
        ).fetchall()
        assert [row["execution_id"] for row in rows] == [None, None]
    finally:
        conn.close()


def test_one_plan_per_execution(tmp_path):
    conn = _connection(tmp_path)
    try:
        db.migrate(conn)
        conn.execute(
            "UPDATE ios_issued_plan SET execution_id = 'exec-1' WHERE issued_plan_id = 'plan-1'"
        )
        conn.commit()
        with pytest.raises(IntegrityError):
            conn.execute(
                "UPDATE ios_issued_plan SET execution_id = 'exec-1' "
                "WHERE issued_plan_id = 'plan-2'"
            )
    finally:
        conn.close()
