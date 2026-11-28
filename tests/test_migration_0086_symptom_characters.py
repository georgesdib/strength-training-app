"""0086 adds description to the symptom log without touching what it measures.

The scale stays 0-3, existing rows keep their level, and the new child table is append-only.
"""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from strength_coach.store import db, queries


def _before_0086(tmp_path):
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if path.name.startswith("0086"):
            continue
        shutil.copy2(path, partial / path.name)
    return partial


def test_migration_preserves_readings_and_adds_append_only_description(tmp_path):
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn, _before_0086(tmp_path))
        # A historical reading in the pre-0086 shape: no side, no characters.
        conn.execute(
            "INSERT INTO symptom_log (logged_on, timing, region, level, settled_within_48h, "
            "note) VALUES (?, ?, ?, ?, ?, ?)",
            ("2024-01-25", "pre_session", "low_back", 3, 0, "old row"),
        )
        legacy_id = int(
            conn.execute("SELECT log_id FROM symptom_log").fetchone()["log_id"]
        )

        db.migrate(conn)

        row = conn.execute("SELECT * FROM symptom_log WHERE log_id = ?", (legacy_id,)).fetchone()
        assert row["level"] == 3
        assert row["note"] == "old row"
        assert row["settled_within_48h"] == 0
        assert row["side"] is None
        assert conn.execute("SELECT COUNT(*) FROM symptom_character").fetchone()[0] == 0

        # The read path tolerates a historical row with no description.
        entries = queries.symptom_entries(conn)
        assert entries[0]["characters"] == []
        assert entries[0]["side"] is None

        conn.execute(
            "INSERT INTO symptom_character (log_id, character_id) VALUES (?, ?)",
            (legacy_id, "pain"),
        )
        assert queries.symptom_entries(conn)[0]["characters"] == ["pain"]

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO symptom_character (log_id, character_id) VALUES (?, ?)",
                (legacy_id, "pain"),   # one label per reading
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO symptom_character (log_id, character_id) VALUES (?, ?)",
                (9999, "pain"),        # no orphan labels
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE symptom_character SET character_id = 'sharp_pain'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM symptom_character")
    finally:
        conn.close()
