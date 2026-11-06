"""Per-exercise workout history is read-only and completed-session only."""

from __future__ import annotations

import datetime as dt

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


def _store_many_sessions(count: int) -> tuple[db.Store, list[str]]:
    dates = [(dt.date(2024, 1, 1) + dt.timedelta(days=index)).isoformat()
             for index in range(count)]
    training = make_training([
        {"Date": date, "Exercise": "Safety Squat Bar", "Weight_Used": str(100 + index),
         "RIR": str(index % 5), "Reps_Done": "5"}
        for index, date in enumerate(dates)
    ])
    readiness = make_readiness([{"Date": date} for date in dates])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store, dates


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
            "tonnage_kg": 625.0,
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


def test_history_pages_past_50_with_range_wide_python_analytics():
    store, dates = _store_many_sessions(113)
    try:
        first = exercise_history.history(
            store.connection, "ssb_squat", limit=50, offset=0,
            start=dates[7], end=dates[106], include_analytics=True,
        )
        second = exercise_history.history(
            store.connection, "ssb_squat", limit=50, offset=50,
            start=dates[7], end=dates[106],
        )
        final = exercise_history.history(
            store.connection, "ssb_squat", limit=50, offset=100,
            start=dates[7], end=dates[106],
        )
        empty = exercise_history.history(
            store.connection, "ssb_squat", limit=50, offset=200,
            start=dates[7], end=dates[106],
        )
        assert first["total"] == 100
        assert first["has_more"] is True and second["has_more"] is False
        assert final["sessions"] == [] and final["has_more"] is False
        all_sessions = first["sessions"] + second["sessions"] + final["sessions"]
        ids = [item["session_id"] for item in all_sessions]
        assert len(ids) == len(set(ids)) == 100
        assert [item["occurred_on"] for item in all_sessions] == sorted(dates[7:107], reverse=True)
        assert all(item["occurred_on"] >= dates[7] and item["occurred_on"] <= dates[106]
                   for item in all_sessions)
        assert first["analytics"]["session_count"] == 100
        assert first["analytics"]["training_dates"] == 100
        assert first["analytics"]["working_sets"] == 100
        assert first["analytics"]["reps_observed_sets"] == 100
        assert first["analytics"]["rir_observed_sets"] == 100
        assert len(first["analytics"]["daily"]) == 100
        assert first["analytics"]["daily"][0]["date"] == dates[7]
        assert first["analytics"]["daily"][-1]["date"] == dates[106]
        assert empty["total"] == 100 and empty["sessions"] == []
    finally:
        store.close()


def test_history_range_validation_and_all_date_equivalent_filtering():
    store, dates = _store_many_sessions(5)
    try:
        bounded = exercise_history.history(
            store.connection, "ssb_squat", limit=50, start=dates[1], end=dates[3]
        )
        assert [item["occurred_on"] for item in bounded["sessions"]] == [dates[3], dates[2], dates[1]]
        assert bounded["start"] == dates[1] and bounded["end"] == dates[3]
        with pytest.raises(ValueError, match="start must be on or before end"):
            exercise_history.history(store.connection, "ssb_squat", start=dates[4], end=dates[0])
        with pytest.raises(ValueError, match="cannot specify different dates"):
            exercise_history.history(store.connection, "ssb_squat", end=dates[3], on_or_before=dates[4])
        with pytest.raises(ValueError, match="start must be YYYY-MM-DD"):
            exercise_history.history(store.connection, "ssb_squat", start="2024-1-2")
    finally:
        store.close()
