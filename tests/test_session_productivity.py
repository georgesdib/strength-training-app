"""Approved session_feedback productivity migration and append-only behaviour."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from strength_coach.features import session_feedback
from strength_coach.store import db, repositories


def _session(conn, session_id="s1"):
    conn.execute(
        "INSERT INTO session (session_id, occurred_on, set_count, exercise_count) "
        "VALUES (?, '2024-01-01', 1, 1)",
        (session_id,),
    )


def test_productivity_only_feedback_is_accepted_and_merged():
    with db.Store(":memory:") as store:
        conn = store.connection
        _session(conn)
        session_feedback.record(conn, "s1", productivity=4)
        session_feedback.record(conn, "s1", srpe=7)
        merged = session_feedback.merged(conn, "s1")

    assert merged["productivity"] == 4
    assert merged["srpe"] == 7
    assert merged["duration_min"] is None


def test_productivity_out_of_range_is_rejected():
    with db.Store(":memory:") as store:
        _session(store.connection)
        with pytest.raises(ValueError, match="productivity"):
            repositories.append_session_feedback(
                store.connection, session_id="s1", productivity=6
            )


def test_productivity_is_append_only():
    with db.Store(":memory:") as store:
        conn = store.connection
        _session(conn)
        session_feedback.record(conn, "s1", productivity=4)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE session_feedback SET productivity = 5")


def test_migration_preserves_existing_rows_and_adds_productivity(tmp_path):
    before = tmp_path / "before"
    before.mkdir()
    for path in Path(db.MIGRATIONS_DIR).glob("*.sql"):
        version = int(path.stem.split("_", 1)[0])
        if version < 45:
            shutil.copy(path, before / path.name)

    path = tmp_path / "coach.db"
    store = db.Store(path, auto_migrate=False)
    try:
        db.migrate(store.connection, before)
        conn = store.connection
        conn.execute(
            "INSERT INTO session (session_id, occurred_on, set_count, exercise_count) "
            "VALUES ('s1', '2024-01-01', 1, 1)"
        )
        conn.execute(
            "INSERT INTO session_feedback "
            "(feedback_id, session_id, srpe, duration_min, note, recorded_at) "
            "VALUES ('old-1', 's1', 7, 75, 'old note', '2024-01-02T10:00:00.000Z')"
        )
        db.migrate(conn, db.MIGRATIONS_DIR)
        row = dict(conn.execute(
            "SELECT * FROM session_feedback WHERE feedback_id = 'old-1'"
        ).fetchone())
        assert row == {
            "feedback_id": "old-1",
            "session_id": "s1",
            "srpe": 7.0,
            "duration_min": 75.0,
            "productivity": None,
            "note": "old note",
            "recorded_at": "2024-01-02T10:00:00.000Z",
        }
        session_feedback.record(conn, "s1", productivity=4)
        assert session_feedback.merged(conn, "s1")["productivity"] == 4
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM session_feedback WHERE feedback_id = 'old-1'")
    finally:
        store.close()
