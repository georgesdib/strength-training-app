"""Migration 0082 opens readiness_entry.field for registry-defined metrics."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from strength_coach.store import db


def _partial(tmp_path):
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith("0082"):
            continue
        shutil.copy2(path, partial / path.name)
    return partial


def test_existing_rows_survive_and_new_fields_are_accepted(tmp_path):
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn, _partial(tmp_path))
        conn.execute(
            "INSERT INTO readiness_entry (entry_id, on_date, field, value, source) "
            "VALUES ('e1', '2026-11-01', 'sleep', 4, 'manual')"
        )
        db.migrate(conn)
        row = conn.execute(
            "SELECT field, value FROM readiness_entry WHERE entry_id = 'e1'"
        ).fetchone()
        assert (row["field"], row["value"]) == ("sleep", 4)

        conn.execute(
            "INSERT INTO readiness_entry (entry_id, on_date, field, value, source) "
            "VALUES ('e2', '2026-11-01', 'sleep_quality', 5, 'manual')"
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM readiness_entry WHERE field = 'sleep_quality'"
        ).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE readiness_entry SET value = 1 WHERE entry_id = 'e2'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM readiness_entry WHERE entry_id = 'e2'")
    finally:
        conn.close()
