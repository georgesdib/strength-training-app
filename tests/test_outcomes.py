"""The outcome review is descriptive and read-only."""

from __future__ import annotations

from conftest import make_readiness, make_training
from strength_coach.features import outcomes
from strength_coach.store import db, importer, repositories


def _store(rows=None):
    if rows is None:
        rows = [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "105",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-15", "Exercise": "Safety Squat Bar", "Weight_Used": "110",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
         "RIR": "2", "Reps_Done": "5"},
    ]
    training = make_training(rows)
    readiness = make_readiness([{"Date": d, "Sleep": 4, "Energy": 4, "Mood": 4}
                                for d in ("2024-01-01", "2024-01-08", "2024-01-15")])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_athlete_profile(
        store.connection, effective_from="2024-01-01", primary_goal="longevity",
        goal_rank=["longevity", "strength"], focus_lifts=[], sessions_per_week_target=3,
    )
    return store


def test_outcome_review_reports_strength_and_coverage():
    store = _store()
    try:
        conn = store.connection
        before = conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0]
        report = outcomes.report(conn, weeks=8, on_date="2024-01-31")
        after = conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0]
        assert before == after
        assert report["window"]["weeks"] == 8
        lifts = {row["exercise_id"]: row for row in report["strength"]["main_lifts"]}
        assert lifts["ssb_squat"]["n"] == 3
        assert lifts["ssb_squat"]["change_kg"] > 0
        assert report["strength"]["attendance"]["target"] == 24
        assert report["strength"]["attendance"]["completed"] == 3
        assert report["coverage"]["strength_lifts"] == 2
        assert report["longevity"]["cardio"]["sessions"] == 0
        assert report["note"].startswith("Descriptive")
    finally:
        store.close()


def test_outcome_review_marks_missing_data_unknown():
    store = db.Store(":memory:")
    try:
        report = outcomes.report(store.connection, weeks=8, on_date="2024-01-31")
        assert report["strength"]["main_lifts"] == []
        assert report["strength"]["sRPE"]["average"] is None
        assert report["strength"]["duration"]["average_min"] is None
        assert report["strength"]["symptoms"]["regions"] == {}
        assert report["strength"]["attendance"]["completed"] == 0
    finally:
        store.close()


def test_modifier_provenance_is_extracted_without_guessing():
    from types import SimpleNamespace
    from strength_coach.features import prescription_provenance

    prescription = SimpleNamespace(
        for_date="2024-01-01",
        notes={"deload": {"reason": "test"}, "fatigue_trigger": "sleep"},
        items=[
            SimpleNamespace(exercise_id="ssb_squat",
                            rationale_refs=("MOD-DELOAD-001", "MOD-FAT-001")),
        ],
    )
    events = dict(prescription_provenance.extract(prescription))
    assert set(events) == {"MOD-DELOAD-001", "MOD-FAT-001"}
    assert "ssb_squat" in events["MOD-DELOAD-001"]["items"]
