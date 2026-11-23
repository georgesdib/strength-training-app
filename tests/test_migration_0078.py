"""Migration 0078 scopes an issued plan to the pairing."""

from __future__ import annotations

import shutil

from strength_coach.store import db


def test_pairing_column_backfills_and_live_plans_collapse(tmp_path):
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith(("0078", "0079")):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn, partial)
        conn.execute(
            "INSERT INTO ios_device (device_id, label, token_hash, created_at) "
            "VALUES ('phone-1', 'Phone', 'h', '2026-11-23T08:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO ios_device "
            "(device_id, label, token_hash, created_at, kind, parent_device_id) "
            "VALUES ('watch-1', 'Watch', 'h2', '2026-11-23T08:01:00+00:00', 'watch', 'phone-1')"
        )
        conn.execute(
            "INSERT INTO ios_issued_plan "
            "(issued_plan_id, device_id, status, requested_session_type, for_date, "
            " created_at, request_expires_at, target_device_id, execution_target) "
            "VALUES ('phone-plan', 'phone-1', 'queued', 'auto', '2026-11-23', "
            "        '2026-11-23T08:10:00+00:00', '2026-11-23T08:20:00+00:00', "
            "        'phone-1', 'phone')"
        )
        conn.execute(
            "INSERT INTO ios_issued_plan "
            "(issued_plan_id, device_id, status, requested_session_type, for_date, "
            " created_at, request_expires_at, target_device_id, execution_target) "
            "VALUES ('watch-plan', 'phone-1', 'queued', 'auto', '2026-11-23', "
            "        '2026-11-23T08:11:00+00:00', '2026-11-23T08:21:00+00:00', "
            "        'watch-1', 'watch')"
        )
        conn.commit()

        db.migrate(conn)

        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(ios_issued_plan)")
        }
        assert "pairing_device_id" in columns
        assert "target_device_id" not in columns
        assert "execution_target" not in columns
        rows = conn.execute(
            "SELECT issued_plan_id, pairing_device_id, superseded_at "
            "FROM ios_issued_plan ORDER BY issued_plan_id"
        ).fetchall()
        assert {row["pairing_device_id"] for row in rows} == {"phone-1"}
        live = [row for row in rows if row["superseded_at"] is None]
        assert len(live) == 1
        assert live[0]["issued_plan_id"] == "watch-plan"
        indexes = {
            row["name"] for row in conn.execute("PRAGMA index_list(ios_issued_plan)")
        }
        assert "idx_ios_issued_plan_live" in indexes
    finally:
        conn.close()
