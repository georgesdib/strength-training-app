"""Readiness feedback is a descriptive follow-up, not tuning."""

from __future__ import annotations

from conftest import make_readiness, make_training
from strength_coach.features import readiness_feedback
from strength_coach.store import db, importer, repositories


def _store():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "110",
         "RIR": "2", "Reps_Done": "5"},
    ]
    training = make_training(rows)
    readiness = make_readiness([{"Date": "2024-01-02", "Sleep": 2, "Energy": 2}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def _event(store):
    conn = store.connection
    run = repositories.start_run(conn, input_hash="test", code_version="test")
    repositories.append_prescription(
        conn,
        prescription_id="p1",
        run_id=run.run_id,
        for_date="2024-01-02",
        session_type="squat",
        fallback_level="fatigue_reduced",
        rule_document_version="test",
        calibration_ids=(),
        approved_by="deterministic",
        items=[],
    )
    repositories.append_prescription_modifier(
        conn,
        prescription_id="p1",
        modifier_key="MOD-FAT-001",
        applied_on="2024-01-02",
        detail={"items": ["ssb_squat"], "readiness_trigger": "sleep"},
    )
    return "p1"


def test_feedback_without_events_is_explicit():
    store = db.Store(":memory:")
    try:
        report = readiness_feedback.report(store.connection, weeks=4, on_date="2024-01-31")
        assert report["events"] == []
        assert report["aggregate"]["n_events"] == 0
        assert any("Fewer than 8" in warning for warning in report["warnings"])
    finally:
        store.close()


def test_feedback_compares_next_session_with_prior_session():
    store = _store()
    try:
        conn = store.connection
        _event(store)
        before = conn.execute("SELECT COUNT(*) FROM prescription_modifier").fetchone()[0]
        report = readiness_feedback.report(conn, weeks=12, on_date="2024-01-31")
        after = conn.execute("SELECT COUNT(*) FROM prescription_modifier").fetchone()[0]
        assert before == after
        assert report["aggregate"]["n_events"] == 1
        event = report["events"][0]
        assert event["next_session_on"] == "2024-01-08"
        assert event["e1rm_after"] > event["e1rm_before"]
        assert event["e1rm_change_pct"] > 0
        assert event["symptom_flare_7d"] is None
        assert "Association only" in report["note"]
    finally:
        store.close()


def test_workout_start_path_is_used_and_adherence_is_compared():
    from strength_coach import workout

    store = _store()
    try:
        conn = store.connection
        plan = {
            "for_date": "2024-01-08",
            "session_type": "squat",
            "items": [{
                "exercise_id": "ssb_squat", "sets": 5, "reps_low": 5, "reps_high": 5,
                "load_kg": 100, "rir_target": 2, "refs": ["MOD-FAT-001"],
            }],
        }
        readiness = {
            "sleep": 2, "energy": 2, "mood": 3, "soreness": 4, "stress": 4,
            "nutrition": 4, "hydration": 4,
        }
        started = workout.start(conn, for_date="2024-01-08", plan=plan, readiness=readiness)
        workout.add_set(conn, started["workout_id"], exercise_id="ssb_squat",
                        load_kg=100, reps=5, rir=2)
        workout.end(conn, started["workout_id"], session_rpe=7, duration_min=50)
        report = readiness_feedback.report(conn, weeks=12, on_date="2024-01-31")
        event = report["events"][0]
        assert event["source"] == "workout"
        assert event["adherence"]["planned_sets"] == 5
        assert event["adherence"]["actual_sets"] == 1
        assert event["adherence"]["ratio"] == 0.2
        assert event["next"]["srpe"] == 7
        assert event["next"]["duration_min"] == 50
    finally:
        store.close()
