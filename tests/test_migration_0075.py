"""Migration 0075 splits the Bulgarian split squat out and merges wide-grip bench."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from strength_coach.store import db


def _connection(tmp_path):
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith("0075"):
            continue
        shutil.copy2(path, partial / path.name)
    conn = db.connect(tmp_path / "coach.db")
    db.migrate(conn, partial)
    conn.execute(
        "INSERT INTO session (session_id, occurred_on, set_count, exercise_count) "
        "VALUES ('s-1', '2026-11-01', 4, 4)"
    )
    rows = [
        # (raw_exercise, exercise_id)
        ("Bulgarian Split Squat", "split_squat"),
        ("Split Squat", "split_squat"),
        # imported and live-logged wide-grip bench rows
        ("Bench Press (wide grip)", "bench_press_wide_grip"),
        ("bench_press_wide_grip", "bench_press_wide_grip"),
    ]
    for index, (raw, exercise_id) in enumerate(rows, start=1):
        conn.execute(
            "INSERT INTO raw_row (table_name, source_row, file_sha256, payload) "
            "VALUES ('training', ?, 'test', '{}')",
            (index,),
        )
        conn.execute(
            "INSERT INTO clean_set (raw_id, session_id, occurred_on, exercise_id, "
            " raw_exercise, load_basis, reps_unit, velocity_present, is_working_set) "
            "VALUES (?, 's-1', '2026-11-01', ?, ?, 'external', 'reps', 0, 1)",
            (index, exercise_id, raw),
        )
    conn.commit()
    return conn, partial


def _apply(conn, partial):
    source = db.MIGRATIONS_DIR
    for path in sorted(source.glob("0075*.sql")):
        shutil.copy2(path, partial / path.name)
    db.migrate(conn, partial)


def test_bulgarian_and_wide_grip_rows_move_and_are_audited(tmp_path):
    conn, partial = _connection(tmp_path)
    try:
        _apply(conn, partial)
        rows = {
            row["raw_exercise"]: row["exercise_id"]
            for row in conn.execute("SELECT raw_exercise, exercise_id FROM clean_set")
        }
        assert rows["Bulgarian Split Squat"] == "bulgarian_split_squat"
        assert rows["Split Squat"] == "split_squat"
        assert rows["Bench Press (wide grip)"] == "bench_press"
        assert rows["bench_press_wide_grip"] == "bench_press"

        audited = {
            (row["old_exercise_id"], row["new_exercise_id"]): row["n"]
            for row in conn.execute(
                "SELECT old_exercise_id, new_exercise_id, COUNT(*) AS n "
                "FROM exercise_remap_log GROUP BY 1, 2"
            )
        }
        assert audited[("split_squat", "bulgarian_split_squat")] == 1
        assert audited[("bench_press_wide_grip", "bench_press")] == 2
        # Raw rows keep what was logged.
        assert conn.execute(
            "SELECT COUNT(*) FROM raw_row"
        ).fetchone()[0] == 4
    finally:
        conn.close()


def test_append_only_guard_is_restored(tmp_path):
    conn, partial = _connection(tmp_path)
    try:
        _apply(conn, partial)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE clean_set SET reps = 99")
    finally:
        conn.close()
