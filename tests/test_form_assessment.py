"""Form trend and review context are descriptive only."""

from __future__ import annotations

from conftest import make_readiness, make_training
from strength_coach.features import form_assessment
from strength_coach.store import db, importer


def _store():
    rows = [
        {"Date": "2024-01-10", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-20", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-02-10", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-02-20", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
    ]
    training = make_training(rows)
    readiness = make_readiness([{"Date": "2024-01-10"}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    for session_id, rating in (
        ("2024-01-10", 2), ("2024-01-20", 2),
        ("2024-02-10", 4), ("2024-02-20", 5),
    ):
        store.connection.execute(
            "INSERT INTO session_form_rating (session_id, exercise_id, rating) "
            "VALUES (?, 'ssb_squat', ?)", (session_id, rating),
        )
    return store


def test_form_trend_compares_adjacent_windows():
    store = _store()
    try:
        report = form_assessment.report(
            store.connection, weeks=4, on_date="2024-03-01"
        )
    finally:
        store.close()
    row = next(row for row in report["forms"] if row["exercise_id"] == "ssb_squat")
    assert row["baseline_avg"] == 2.0
    assert row["current_avg"] == 4.5
    assert row["change"] == 2.5
    assert row["status"] == "up"
    assert row["current_n"] == 2 and row["baseline_n"] == 2


def test_review_context_lists_prior_form_only():
    store = _store()
    try:
        context = form_assessment.review_context(store.connection, "2024-02-20")
    finally:
        store.close()
    form = context["forms"][0]
    assert form["rating"] == 5
    assert form["prior_n"] == 3
    assert form["prior_latest"] == 4
    assert form["prior_avg"] == 2.67
