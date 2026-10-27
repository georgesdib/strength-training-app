"""Declared breaks: a trained week that must not advance the cycle (DEC-CONTINUITY-04)."""

from __future__ import annotations

import sqlite3

import pytest
from conftest import make_readiness, make_training

from strength_coach import cli
from strength_coach.features import breaks
from strength_coach.rules.context import trained_week_index
from strength_coach.store import db, importer

WEEKS = ("2024-01-01", "2024-01-08", "2024-01-15")


def _store(days=WEEKS):
    rows = [
        {"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for day in days
    ]
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_a_break_validates_its_dates_and_reason():
    with _store() as store:
        conn = store.connection
        with pytest.raises(ValueError, match="ends_on"):
            breaks.record(conn, starts_on="2024-01-10", ends_on="2024-01-09",
                          reason="holiday")
        with pytest.raises(ValueError, match="reason"):
            breaks.record(conn, starts_on="2024-01-10", ends_on="2024-01-12",
                          reason="sabbatical")


def test_a_break_is_active_only_inside_its_dates():
    with _store() as store:
        conn = store.connection
        break_id = breaks.record(conn, starts_on="2024-01-08", ends_on="2024-01-10",
                                 reason="test")
        assert [item.break_id for item in breaks.active_on(conn, "2024-01-09")] == [break_id]
        assert breaks.active_on(conn, "2024-01-07") == []
        assert breaks.active_on(conn, "2024-01-11") == []


def test_a_break_freezes_a_week_that_was_trained():
    # Three trained weeks; the middle one is declared a test week and must not advance the
    # cycle, so the index stays at 2 instead of 3.
    with _store() as store:
        conn = store.connection
        assert trained_week_index(conn, "2024-01-01", "2024-01-21") == 3
        breaks.record(conn, starts_on="2024-01-08", ends_on="2024-01-10", reason="test")
        assert trained_week_index(conn, "2024-01-01", "2024-01-21") == 2


def test_cancelling_appends_and_the_original_stays_visible():
    with _store() as store:
        conn = store.connection
        break_id = breaks.record(conn, starts_on="2024-01-08", ends_on="2024-01-10",
                                 reason="holiday")
        breaks.cancel(conn, break_id)
        rows = breaks.all_breaks(conn)
        assert [row.cancelled for row in rows] == [True]
        assert breaks.active_on(conn, "2024-01-09") == []
        # The frozen week is released again.
        assert trained_week_index(conn, "2024-01-01", "2024-01-21") == 3
        with pytest.raises(ValueError, match="already cancelled"):
            breaks.cancel(conn, break_id)


def test_break_rows_are_append_only():
    with _store() as store:
        conn = store.connection
        breaks.record(conn, starts_on="2024-01-08", ends_on="2024-01-10", reason="holiday")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE declared_break SET reason = 'test'")


def test_cli_records_lists_and_cancels(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main(["--db", str(path), "break", "--from", "2024-01-08",
                     "--to", "2024-01-10", "--reason", "test"]) == 0
    assert "its weeks are frozen" in capsys.readouterr().out

    assert cli.main(["--db", str(path), "break", "--show"]) == 0
    out = capsys.readouterr().out
    assert "2024-01-08" in out and "test" in out

    assert cli.main(["--db", str(path), "break", "--cancel", "1"]) == 0
    assert "cancelled" in capsys.readouterr().out
    assert cli.main(["--db", str(path), "break", "--show"]) == 0
    assert "cancelled" in capsys.readouterr().out
