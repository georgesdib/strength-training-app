"""Optional session RPE and length: append-only, skippable, captured at review."""

from __future__ import annotations

import sqlite3

import pytest
import yaml
from conftest import make_readiness, make_training

from strength_coach import cli
from strength_coach.features import session_feedback
from strength_coach.store import db, importer, queries

ROWS = [{"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "3"}]


def store_with_session():
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_optional_values_are_stored_and_blank_is_not_an_error():
    with store_with_session() as store:
        conn = store.connection
        assert session_feedback.record(conn, "2024-01-01") is None
        stored = session_feedback.record(
            conn, "2024-01-01", srpe=7, duration_min=75,
        )
        latest = session_feedback.latest(conn, "2024-01-01")

    assert stored["srpe"] == 7
    assert latest["duration_min"] == 75


@pytest.mark.parametrize("srpe,minutes", [(0, None), (11, None), (None, 0), (None, 700)])
def test_out_of_range_values_are_rejected(srpe, minutes):
    with store_with_session() as store, pytest.raises(ValueError):
        session_feedback.record(
            store.connection, "2024-01-01", srpe=srpe, duration_min=minutes,
        )


def test_feedback_is_append_only_and_latest_wins():
    with store_with_session() as store:
        conn = store.connection
        session_feedback.record(conn, "2024-01-01", srpe=7)
        session_feedback.record(conn, "2024-01-01", srpe=8)
        assert session_feedback.latest(conn, "2024-01-01")["srpe"] == 8
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE session_feedback SET srpe = 5")


def test_merged_feedback_keeps_latest_non_null_per_field():
    with store_with_session() as store:
        conn = store.connection
        session_feedback.record(conn, "2024-01-01", srpe=7, duration_min=75)
        session_feedback.record(conn, "2024-01-01", srpe=8)
        merged = session_feedback.merged(conn, "2024-01-01")
        latest = session_feedback.latest(conn, "2024-01-01")

    assert merged["srpe"] == 8
    assert merged["duration_min"] == 75
    assert merged["sources"]["duration_min"]["feedback_id"]
    assert latest["duration_min"] is None


def test_cli_review_flags_store_optional_detail(tmp_path):
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    path = tmp_path / "coach.db"
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    marks = tmp_path / "marks.yaml"
    marks.write_text(yaml.safe_dump({
        "sessions": {"2024-01-01": {"confidence": "high",
                                    "scores": {"RIR_ADHERENCE": 0.9}}}
    }), encoding="utf-8")
    assert cli.main(["--db", str(path), "review", "--session", "2024-01-01",
                     "--scores", str(marks), "--session-rpe", "7",
                     "--session-minutes", "75"]) == 0

    store = db.Store(path)
    try:
        feedback = queries.session_feedback(store.connection, "2024-01-01")
    finally:
        store.close()
    assert (feedback["srpe"], feedback["duration_min"]) == (7.0, 75.0)
