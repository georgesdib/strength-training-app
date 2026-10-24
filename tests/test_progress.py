"""The descriptive progress dashboard reads, but never changes, a prescription."""

from __future__ import annotations

from conftest import make_readiness, make_training
from strength_coach.features import progress
from strength_coach.store import db, importer, repositories


def test_dashboard_reports_coverage_performance_and_volume():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-08", "Exercise": "Trap Bar Deadlift", "Weight_Used": "155",
         "RIR": "2", "Reps_Done": "5"},
    ]
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        repositories.append_session_feedback(
            store.connection, session_id="2024-01-08", srpe=6, duration_min=45,
        )
        repositories.append_athlete_profile(
            store.connection, effective_from="2024-01-01", primary_goal="strength",
            goal_rank=["strength"], focus_lifts=["ssb_squat"],
            sessions_per_week_target=3,
        )
        report = progress.dashboard(store.connection, "2024-01-08")
    finally:
        store.close()
    assert report["coverage"]["with_srpe"] == 1
    assert report["performance"]["n"] == 1
    assert report["performance"]["latest"]["ratio"] > 1.0
    assert any(row["pattern"] == "hinge" for row in report["volume"])
    assert report["attendance"]["completed"] == 2
    assert report["attendance"]["target"] == 24
    assert report["attendance"]["families"]["hinge"] == 2
    assert report["attendance"]["injury_free_weeks"] is None
