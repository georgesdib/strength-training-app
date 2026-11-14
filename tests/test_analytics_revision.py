"""Analytics revision ledger: transactional with source mutations, append-only and durable."""

from __future__ import annotations

import json
import sqlite3

import pytest
from conftest import make_readiness, make_training

from strength_coach import history, workout
from strength_coach.analytics import (
    current_revision,
    record_dependency_change,
    record_mutation,
)
from strength_coach.store import db, importer

PLAN = {
    "for_date": "2024-01-01",
    "session_type": "hinge",
    "items": [
        {"exercise_id": "trap_bar_deadlift", "sets": 3, "reps_low": 3,
         "reps_high": 5, "load_kg": 100, "rir_target": 2},
    ],
}
READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
             "nutrition": 4, "hydration": 4}


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def import_rows(conn, rows=None):
    training = make_training(rows or [
        {"Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "2"},
    ])
    readiness = make_readiness([{}])
    return importer.import_export(
        conn, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )


def kinds(conn) -> list[str]:
    return [row["kind"] for row in conn.execute(
        "SELECT kind FROM analytics_revision ORDER BY revision_id"
    )]


def test_record_requires_the_mutation_transaction(conn):
    with pytest.raises(RuntimeError):
        record_mutation(conn, "import")
    assert current_revision(conn) == 0


def test_import_commits_one_revision_for_the_batch(conn):
    import_rows(conn)
    assert current_revision(conn) == 1
    assert kinds(conn) == ["import"]
    row = conn.execute("SELECT * FROM analytics_revision").fetchone()
    assert row["session_id"] is None
    assert json.loads(row["detail_json"]) == {"sessions": 1, "sets": 1}


def test_reimport_of_identical_content_does_not_append_a_revision(conn):
    import_rows(conn)
    before = current_revision(conn)
    import_rows(conn)
    assert current_revision(conn) == before


def test_rollback_leaves_neither_source_row_nor_revision(conn):
    with pytest.raises(RuntimeError), db.transaction(conn):
        conn.execute(
            "INSERT INTO raw_row (table_name, source_row, file_sha256, payload) "
            "VALUES ('training', 1, 'test', '{}')"
        )
        record_mutation(conn, "import")
        raise RuntimeError("simulated failure")
    assert current_revision(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM raw_row").fetchone()[0] == 0


def test_workout_end_appends_one_revision(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=40)
    rows = conn.execute("SELECT * FROM analytics_revision").fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "workout_end"
    assert rows[0]["session_id"] == started["workout_id"]


def test_correction_and_tombstones_append_one_revision(conn):
    import_rows(conn)
    session_id = conn.execute("SELECT session_id FROM session").fetchone()[0]
    before = current_revision(conn)
    detail = history.detail(conn, session_id)
    sets = [
        {"exercise_id": item["exercise_id"], "load_kg": item["load_kg"],
         "reps": item["reps"], "rir": item["rir"]}
        for item in detail["sets"][:1]
    ]
    history.edit_session(conn, session_id, sets=sets)
    assert current_revision(conn) == before + 1
    assert kinds(conn)[-1] == "correction"


def test_void_and_unvoid_append_revisions(conn):
    import_rows(conn)
    session_id = conn.execute("SELECT session_id FROM session").fetchone()[0]
    before = current_revision(conn)
    history.void_session(conn, session_id, reason="test")
    history.void_session(conn, session_id, unvoid=True)
    assert current_revision(conn) == before + 2
    assert kinds(conn)[-2:] == ["void", "unvoid"]
    assert conn.execute(
        "SELECT voided FROM session WHERE session_id = ?", (session_id,)
    ).fetchone()[0] == 0


def test_revision_rows_are_append_only(conn):
    import_rows(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE analytics_revision SET kind = 'void'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM analytics_revision")
    assert current_revision(conn) == 1


def test_analytics_tables_exist_after_migration(conn):
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('analytics_revision', 'analytics_build')"
        )
    }
    assert names == {"analytics_revision", "analytics_build"}


def test_dependency_revision_records_digest(conn):
    record_dependency_change(
        conn, "config", config_digest="sha256:taxonomy", families=["probe_family"]
    )
    row = conn.execute("SELECT * FROM analytics_revision").fetchone()
    assert row["kind"] == "config"
    assert row["session_id"] is None
    assert row["config_digest"] == "sha256:taxonomy"
