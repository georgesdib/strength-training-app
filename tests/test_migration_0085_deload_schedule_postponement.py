from __future__ import annotations

import shutil
import sqlite3

import pytest

from strength_coach.store import db, repositories


def _before_0085(tmp_path):
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if path.name.startswith("0085"):
            continue
        shutil.copy2(path, partial / path.name)
    return partial


def test_migration_preserves_existing_rows_and_adds_append_only_schedule(tmp_path):
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn, _before_0085(tmp_path))
        repositories.append_athlete_profile(
            conn,
            effective_from="2024-01-01",
            block_start_date="2024-01-01",
        )
        db.migrate(conn)

        profile = conn.execute(
            "SELECT block_start_date FROM athlete_profile"
        ).fetchone()
        assert profile["block_start_date"] == "2024-01-01"
        assert conn.execute(
            "SELECT COUNT(*) FROM scheduled_deload_postponement"
        ).fetchone()[0] == 0

        conn.execute(
            "INSERT INTO scheduled_deload_postponement "
            "(operation_id, recorded_on, postponed_until) VALUES (?, ?, ?)",
            ("op-1", "2024-02-05", "2024-04-01"),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE scheduled_deload_postponement "
                "SET postponed_until = '2024-04-02' WHERE operation_id = 'op-1'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "DELETE FROM scheduled_deload_postponement WHERE operation_id = 'op-1'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO scheduled_deload_postponement "
                "(operation_id, recorded_on, postponed_until) VALUES (?, ?, ?)",
                ("op-2", "2024-02-05", "2024-02-05"),
            )
    finally:
        conn.close()
