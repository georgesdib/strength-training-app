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
    assert row["low_current"] == 0
    assert report["low_form_events"] == 0


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


def test_followup_counts_cumulative_low_form_events_and_due_date():
    rows = []
    for day in ("2026-11-01", "2026-11-08", "2026-11-15", "2026-11-22"):
        for exercise in ("Safety Squat Bar", "Competition Bench Press",
                         "Trap Bar Deadlift", "Back Extension"):
            rows.append({"Date": day, "Exercise": exercise, "Weight_Used": "50",
                         "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{"Date": "2026-11-01"}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        for day in ("2026-11-01", "2026-11-08", "2026-11-15", "2026-11-22"):
            for exercise in ("ssb_squat", "bench_press", "trap_bar_deadlift", "back_extension"):
                store.connection.execute(
                    "INSERT INTO session_form_rating (session_id, exercise_id, rating) "
                    "VALUES (?, ?, 2)", (day, exercise),
                )
        early = form_assessment.followup(store.connection, as_of="2026-11-23")
        ready = form_assessment.followup(store.connection, as_of="2027-01-20")
        late = form_assessment.followup(store.connection, as_of="2027-04-20")
    finally:
        store.close()
    assert early["status"] == "threshold_met_waiting"
    assert early["low_events"] == 16
    assert early["low_lifts"] == 4
    assert ready["status"] == "ready"
    assert ready["due_on"] == "2027-01-17"
    assert late["status"] == "ready"
