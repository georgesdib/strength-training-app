"""Store: migrations, append-only guarantees, and import idempotency.

The acceptance criterion for phase 3 is behavioural, not structural: cleaning an export
writes `clean_set` + `session` rows, and re-running it appends no duplicate artifacts. These
tests pin exactly that, plus the two invariants that are easy to lose afterwards --
append-only tables really refuse UPDATE/DELETE, and identical repeated sets are never
merged (DQ-DUP-01).
"""

from __future__ import annotations

import sqlite3

import pytest

from conftest import make_readiness, make_training
from strength_coach.store import db, importer
from strength_coach.store import repositories as repo


@pytest.fixture
def store(tmp_path):
    database = db.Store(tmp_path / "coach.db")
    yield database
    database.close()


@pytest.fixture
def conn(store):
    return store.connection


def build_frames(rows, readiness_rows=None):
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
    return training, readiness


def do_import(conn, training, readiness):
    return importer.import_export(
        conn,
        training,
        readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )


def count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])


# --- migrations ------------------------------------------------------------


def test_migrations_apply_every_table(store):
    tables = set(store.tables())
    expected = {
        "raw_row", "clean_set", "session", "quarantine", "readiness_day",
        "vbt_calibration", "rule_document", "rule", "prescription",
        "prescription_item", "critique", "rubric_score", "run", "run_event",
    }
    assert expected <= tables
    assert db.applied_migrations(store.connection) == {
        m.version: m.checksum for m in db.discover_migrations()
    }


def test_migrate_is_idempotent(conn):
    assert db.migrate(conn) == []
    assert count(conn, "schema_migration") == len(db.discover_migrations())


def test_edited_migration_is_rejected(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    script = migrations / "0001_first.sql"
    script.write_text("CREATE TABLE thing (id INTEGER PRIMARY KEY);", encoding="utf-8")

    connection = db.connect(":memory:")
    try:
        assert db.migrate(connection, migrations) == ["0001"]
        # Editing history after it was applied would let two databases claim the same
        # version while holding different schemas, so it must fail loudly.
        script.write_text("CREATE TABLE thing (id INTEGER PRIMARY KEY, extra TEXT);",
                          encoding="utf-8")
        with pytest.raises(db.MigrationError, match="edited after being applied"):
            db.migrate(connection, migrations)
    finally:
        connection.close()


def test_missing_migrations_directory_raises(tmp_path):
    with pytest.raises(db.MigrationError, match="not found"):
        db.discover_migrations(tmp_path / "nope")


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO clean_set (raw_id, session_id, occurred_on, exercise_id, load_basis,"
            " reps_unit, velocity_present, is_working_set) "
            "VALUES (999, '2024-01-01', '2024-01-01', 'squat', 'external', 'reps', 0, 1)"
        )


# --- append-only guards ----------------------------------------------------


def test_append_only_tables_reject_update_and_delete(conn):
    training, readiness = build_frames(
        [
            {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "3"},
            {"Date": "(null)", "Exercise": "Competition Squat", "Weight_Used": "100", "RIR": "2"},
        ]
    )
    do_import(conn, training, readiness)

    for statement in [
        "UPDATE raw_row SET source_row = 99",
        "UPDATE clean_set SET reps = 99",
        "DELETE FROM clean_set",
        "DELETE FROM quarantine",
        "DELETE FROM run_event",
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(statement)


def test_run_stays_mutable_so_it_can_finish(conn):
    run = repo.start_run(conn, input_hash="x", code_version="0.0.1-dev")
    assert conn.execute("SELECT finished_at FROM run WHERE run_id = ?",
                        (run.run_id,)).fetchone()["finished_at"] is None
    repo.finish_run(conn, run.run_id, status="llm_downgraded", llm_tokens=12)
    row = conn.execute("SELECT * FROM run WHERE run_id = ?", (run.run_id,)).fetchone()
    assert row["status"] == "llm_downgraded"
    assert row["finished_at"] is not None


# --- identity rules (DQ-DUP-01) -------------------------------------------


def test_raw_rows_are_identified_by_file_and_line(conn):
    training, _ = build_frames([{"Date": "2024-01-01"}])
    mapping, inserted = repo.store_raw_rows(
        conn, training, table_name="training", file_sha256="aaa"
    )
    assert inserted == 1 and mapping == {1: 1}

    _, again = repo.store_raw_rows(conn, training, table_name="training", file_sha256="aaa")
    assert again == 0
    assert count(conn, "raw_row") == 1


def test_same_rows_from_a_different_file_are_overlap(conn):
    training, _ = build_frames([{"Date": "2024-01-01"}])
    first, inserted = repo.store_raw_rows(conn, training, table_name="training", file_sha256="aaa")
    second, again = repo.store_raw_rows(conn, training, table_name="training", file_sha256="bbb")
    # A cumulative re-export reuses the existing raw row rather than duplicating it.
    assert inserted == 1 and again == 0
    assert first == second
    assert count(conn, "raw_row") == 1


def test_cumulative_export_appends_only_new_rows(conn):
    first_rows = [
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "3"},
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80", "RIR": "2"},
    ]
    second_rows = first_rows + [
        {"Date": "2024-01-02", "Exercise": "Trap Bar Deadlift", "Weight_Used": "155", "RIR": "3"},
    ]
    first_training, first_readiness = build_frames(first_rows)
    do_import(conn, first_training, first_readiness)
    second_training, second_readiness = build_frames(second_rows)
    report = do_import(conn, second_training, second_readiness)

    assert report.clean_sets_inserted == 1
    assert count(conn, "clean_set") == 3
    assert report.raw_rows_overlap >= 2


def test_identical_repeated_sets_survive(conn):
    rows = [
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "3"},
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "3"},
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "3"},
    ]
    training, readiness = build_frames(rows)
    report = do_import(conn, training, readiness)
    # DQ-DUP-01: identical repeated rows trace a real set structure; dedupe would delete volume.
    assert report.clean_sets_inserted == 3
    assert count(conn, "clean_set") == 3


# --- import behaviour ------------------------------------------------------


def test_import_writes_sets_sessions_and_quarantine(conn):
    training, readiness = build_frames(
        [
            {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "3"},
            {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "140", "RIR": "4"},
            {"Date": "(null)", "Exercise": "Competition Squat", "Weight_Used": "100", "RIR": "2"},
        ]
    )
    report = do_import(conn, training, readiness)

    assert report.clean_sets_inserted == 2
    assert report.sessions_written == 1
    assert report.quarantined == 1
    assert report.window_start == report.window_end == "2024-01-01"

    session = conn.execute("SELECT * FROM session").fetchone()
    assert session["session_id"] == "2024-01-01"
    assert session["session_type"] == "hinge"     # the hinge is decisive
    assert session["set_count"] == 2
    assert count(conn, "quarantine") == 1


def test_reimport_writes_no_duplicate_rows(conn):
    training, readiness = build_frames(
        [
            {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "3"},
            {"Date": "2024-01-02", "Exercise": "Competition Squat", "Weight_Used": "100", "RIR": "2"},
        ]
    )
    first = do_import(conn, training, readiness)
    before = {t: count(conn, t) for t in ("raw_row", "clean_set", "session", "quarantine")}

    second = do_import(conn, training, readiness)

    assert first.clean_sets_inserted == 2
    assert second.clean_sets_inserted == 0
    assert second.raw_rows_inserted == 0
    assert second.clean_sets_existing == 2
    assert {t: count(conn, t) for t in before} == before
    # The trace still records the second attempt: two runs, one set of artifacts.
    assert count(conn, "run") == 2


def test_adding_a_session_updates_the_session_row(conn):
    day_one, readiness = build_frames(
        [{"Date": "2024-01-01", "Exercise": "Competition Squat", "Weight_Used": "100", "RIR": "2"}]
    )
    do_import(conn, day_one, readiness)

    day_two, _ = build_frames(
        [
            {"Date": "2024-01-01", "Exercise": "Competition Squat", "Weight_Used": "100", "RIR": "2"},
            {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80", "RIR": "2"},
        ]
    )
    do_import(conn, day_two, readiness)

    sessions = conn.execute("SELECT * FROM session").fetchall()
    assert len(sessions) == 1                    # derived state, recomputed not duplicated
    assert sessions[0]["set_count"] == 2
    assert sessions[0]["updated_at"] is not None


def test_import_records_a_replayable_trace(conn):
    training, readiness = build_frames([{"Date": "2024-01-01"}])
    report = do_import(conn, training, readiness)

    run = conn.execute("SELECT * FROM run WHERE run_id = ?", (report.run_id,)).fetchone()
    assert run["status"] == "ok"
    assert run["finished_at"] is not None
    assert run["input_hash"]
    assert run["code_version"]
    assert run["config_hash"]

    events = repo.run_events(conn, report.run_id)
    assert [event["kind"] for event in events] == ["input", "artifact"]
    assert [event["seq"] for event in events] == [1, 2]
    payload = events[1]["payload"]
    assert '"clean_sets_inserted": 1' in payload


def test_failed_import_leaves_the_run_marked_error(conn, monkeypatch):
    training, readiness = build_frames([{"Date": "2024-01-01"}])

    def explode(*args, **kwargs):
        raise RuntimeError("cleaner exploded")

    monkeypatch.setattr(importer.clean, "build_clean_sets", explode)
    with pytest.raises(RuntimeError, match="cleaner exploded"):
        do_import(conn, training, readiness)

    run = conn.execute("SELECT * FROM run").fetchone()
    assert run["status"] == "error"
    assert run["finished_at"] is not None


def test_flags_are_stored_as_a_json_list(conn):
    training, readiness = build_frames(
        [{"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "6"}]
    )
    do_import(conn, training, readiness)
    row = conn.execute("SELECT flags, is_working_set FROM clean_set").fetchone()
    assert '"WARMUP"' in row["flags"]          # DEC-RIR-01: RIR 6 is a warm-up
    assert row["is_working_set"] == 0


def test_velocity_presence_follows_the_telemetry_block(conn):
    training, readiness = build_frames(
        [
            {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift",
             "Weight_Used": "150", "RIR": "3", "Avg_velocity": "0.32"},
            {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift",
             "Weight_Used": "150", "RIR": "3", "Avg_velocity": "0.000000"},
        ]
    )
    do_import(conn, training, readiness)
    flags = [row["velocity_present"] for row in
             conn.execute("SELECT velocity_present FROM clean_set ORDER BY set_id")]
    assert flags == [1, 0]


def test_quarantine_reason_is_preserved(conn):
    training, readiness = build_frames(
        [{"Date": "(null)", "Exercise": "Competition Squat", "Weight_Used": "100", "RIR": "2"}]
    )
    do_import(conn, training, readiness)
    reasons = [row["reason"] for row in conn.execute("SELECT reason FROM quarantine")]
    assert reasons == ["null_date"]
