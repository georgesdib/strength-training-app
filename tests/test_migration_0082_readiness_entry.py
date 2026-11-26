"""Migration 0082 opens readiness_entry.field for registry-defined metrics."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from strength_coach.store import db


def _partial(tmp_path, *, variant: str | None = None):
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith("0082"):
            continue
        shutil.copy2(path, partial / path.name)
    if variant is not None:
        original = source / "0082_readiness_entry_open_field.sql"
        (partial / original.name).write_text(variant, encoding="utf-8")
    return partial


def _seed_entries(conn):
    rows = [
        ("e1", "2026-11-01", "sleep", 4, "manual"),
        ("e2", "2026-11-01", "energy", 3, "import"),
        ("e3", "2026-11-01", "mood", 5, "preset"),
    ]
    conn.executemany(
        "INSERT INTO readiness_entry (entry_id, on_date, field, value, source) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    return rows


def test_existing_rows_survive_and_new_fields_are_accepted(tmp_path):
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn, _partial(tmp_path))
        expected = _seed_entries(conn)
        db.migrate(conn)

        rows = conn.execute(
            "SELECT entry_id, on_date, field, value, source FROM readiness_entry "
            "ORDER BY entry_id"
        ).fetchall()
        assert [tuple(row) for row in rows] == expected
        assert conn.execute(
            "SELECT COUNT(*) FROM readiness_entry WHERE source = 'preset'"
        ).fetchone()[0] == 1

        conn.execute(
            "INSERT INTO readiness_entry (entry_id, on_date, field, value, source) "
            "VALUES ('e4', '2026-11-01', 'sleep_quality', 5, 'manual')"
        )
        assert conn.execute(
            "SELECT COUNT(*) FROM readiness_entry WHERE field = 'sleep_quality'"
        ).fetchone()[0] == 1

        indexes = {
            row["name"] for row in conn.execute("PRAGMA index_list('readiness_entry')")
        }
        assert "idx_readiness_entry_date" in indexes
        triggers = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'readiness_entry'"
            )
        }
        assert triggers == {"readiness_entry_no_update", "readiness_entry_no_delete"}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE readiness_entry SET value = 1 WHERE entry_id = 'e4'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM readiness_entry WHERE entry_id = 'e4'")
    finally:
        conn.close()


def test_a_failed_rebuild_rolls_back(tmp_path):
    source = db.MIGRATIONS_DIR / "0082_readiness_entry_open_field.sql"
    variant = source.read_text(encoding="utf-8").replace(
        "COMMIT;", "INSERT INTO no_such_table VALUES (1);\nCOMMIT;", 1,
    )
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn, _partial(tmp_path))
        _seed_entries(conn)
        variant_dir = tmp_path / "variant"
        variant_dir.mkdir()
        (variant_dir / source.name).write_text(variant, encoding="utf-8")
        with pytest.raises(db.MigrationError):
            db.migrate(conn, variant_dir)
        assert conn.in_transaction is False
        assert conn.execute(
            "SELECT COUNT(*) FROM readiness_entry"
        ).fetchone()[0] == 3
        table = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'readiness_entry'"
        ).fetchone()["sql"]
        assert "CHECK (field IN" in table
    finally:
        conn.close()
