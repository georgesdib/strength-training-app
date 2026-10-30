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
            store.connection, effective_from="2024-01-01",
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


def test_injury_free_state_persists_until_another_log():
    import datetime as dt

    from strength_coach.features import attendance

    store = db.Store(":memory:")
    try:
        repositories.append_symptom(
            store.connection, logged_on="2024-01-03", timing="pre_session",
            region="low_back", level=0,
        )
        repositories.append_symptom(
            store.connection, logged_on="2024-01-10", timing="pre_session",
            region="low_back", level=3,
        )
        result = attendance.summary(
            store.connection, start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 28),
            weeks=4, target_per_week=3,
        )
    finally:
        store.close()
    # Week 1 is free; the week-2 injury persists through week 4 (no recovery log).
    assert result["injury_free_weeks"] == 1
