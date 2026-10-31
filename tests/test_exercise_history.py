"""Per-exercise workout history is read-only and completed-session only."""

from __future__ import annotations

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import exercise_history
from strength_coach.store import db, importer

DATES = [
    "2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29", "2024-02-05",
]


def _store() -> db.Store:
    rows = [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "105",
         "RIR": "2", "Reps_Done": "5"},
        # A warm-up-only session is not history: RIR 6 is excluded from working volume.
        {"Date": "2024-01-15", "Exercise": "Safety Squat Bar", "Weight_Used": "110",
         "RIR": "6", "Reps_Done": "5"},
        {"Date": "2024-01-22", "Exercise": "Safety Squat Bar", "Weight_Used": "115",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-22", "Exercise": "Safety Squat Bar", "Weight_Used": "115",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-29", "Exercise": "Safety Squat Bar", "Weight_Used": "120",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-02-05", "Exercise": "Safety Squat Bar", "Weight_Used": "125",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-03-01", "Exercise": "Back Extension", "Weight_Used": "0",
         "RIR": "3", "Reps_Done": "12"},
        {"Date": "2024-03-08", "Exercise": "Hyperextensions", "Weight_Used": "0",
         "RIR": "3", "Reps_Done": "10"},
    ]
    store = db.Store(":memory:")
    training = make_training(rows)
    readiness = make_readiness([{"Date": item} for item in DATES])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_history_returns_sessions_newest_first_and_pages_by_session():
    store = _store()
    try:
        page = exercise_history.history(store.connection, "ssb_squat", limit=2)
        assert page["total"] == 5
        assert page["has_more"] is True
        assert [item["occurred_on"] for item in page["sessions"]] == [
            "2024-02-05", "2024-01-29",
        ]
        assert page["sessions"][0]["sets"] == [{
            "set_index": 1,
            "load_kg": 125.0,
            "load_basis": "external",
            "reps": 5,
            "reps_unit": "reps",
            "rir": 2,
        }]

        next_page = exercise_history.history(
            store.connection, "ssb_squat", limit=2, offset=2
        )
        assert [item["occurred_on"] for item in next_page["sessions"]] == [
            "2024-01-22", "2024-01-08",
        ]
        assert len(next_page["sessions"][0]["sets"]) == 2
        assert next_page["has_more"] is True
    finally:
        store.close()


def test_history_excludes_warmups_and_respects_the_workout_date():
    store = _store()
    try:
        page = exercise_history.history(
            store.connection, "ssb_squat", limit=10, on_or_before="2024-01-22"
        )
        assert page["total"] == 3
        assert [item["occurred_on"] for item in page["sessions"]] == [
            "2024-01-22", "2024-01-08", "2024-01-01",
        ]
        assert all(
            set_["rir"] != 6
            for session in page["sessions"]
            for set_ in session["sets"]
        )
        assert "2024-01-15" not in [item["occurred_on"] for item in page["sessions"]]
    finally:
        store.close()


def test_history_includes_declared_history_equivalents():
    store = _store()
    try:
        page = exercise_history.history(store.connection, "back_extension", limit=5)
        assert page["total"] == 2
        assert [item["id"] for item in page["included_exercises"]] == [
            "back_extension", "hyperextension",
        ]
        assert [item["occurred_on"] for item in page["sessions"]] == [
            "2024-03-08", "2024-03-01",
        ]
    finally:
        store.close()


def test_history_validates_inputs():
    store = _store()
    try:
        with pytest.raises(ValueError, match="unknown exercise"):
            exercise_history.history(store.connection, "not_a_lift")
        with pytest.raises(ValueError, match="on_or_before"):
            exercise_history.history(
                store.connection, "ssb_squat", on_or_before="22/01/2024"
            )
        with pytest.raises(ValueError, match="limit"):
            exercise_history.history(store.connection, "ssb_squat", limit=0)
    finally:
        store.close()
