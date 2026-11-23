"""Migration 0077 adds the load catalogue to an issued plan."""

from __future__ import annotations

import shutil

from strength_coach.store import db


def test_catalogue_column_is_additive(tmp_path):
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith("0077"):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn, partial)
        assert "load_catalogue_json" not in {
            row["name"] for row in conn.execute("PRAGMA table_info(ios_issued_plan)")
        }
        db.migrate(conn)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(ios_issued_plan)")
        }
        assert "load_catalogue_json" in columns
        conn.execute(
            "INSERT INTO ios_device (device_id, label, token_hash, created_at) "
            "VALUES ('phone-1', 'Phone', 'h', '2026-11-23T08:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO ios_issued_plan "
            "(issued_plan_id, device_id, status, requested_session_type, for_date, "
            " created_at, request_expires_at) "
            "VALUES ('plan-1', 'phone-1', 'queued', 'auto', '2026-11-23', "
            "        '2026-11-23T08:00:00+00:00', '2026-11-23T08:10:00+00:00')"
        )
        row = conn.execute(
            "SELECT load_catalogue_json FROM ios_issued_plan WHERE issued_plan_id = 'plan-1'"
        ).fetchone()
        assert row["load_catalogue_json"] is None
    finally:
        conn.close()
