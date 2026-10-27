"""The W5 prospective review is read-only and protocol-shaped."""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach.features import prospective
from strength_coach.store import db, importer, repositories


def _store():
    dates = [
        "2023-12-11", "2023-12-18", "2023-12-25", "2024-01-01",
        "2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29",
    ]
    loads = ["100", "102", "104", "106", "108", "110", "112", "114"]
    rows = [
        {"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": load,
         "RIR": "2", "Reps_Done": "5"}
        for day, load in zip(dates, loads, strict=True)
    ]
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_athlete_profile(
        store.connection, effective_from="2023-12-01", primary_goal="strength",
        goal_rank=["strength"], focus_lifts=["ssb_squat"],
        sessions_per_week_target=3,
    )
    return store


def test_prospective_report_is_read_only_and_protocol_shaped():
    store = _store()
    try:
        conn = store.connection
        before = conn.execute("SELECT COUNT(*) FROM clean_set").fetchone()[0]
        report = prospective.report(conn, weeks=8, on_date="2024-03-01")
        after = conn.execute("SELECT COUNT(*) FROM clean_set").fetchone()[0]
        assert before == after
        assert report["window"]["weeks"] == 8
        lift = next(row for row in report["strength"]["lifts"]
                    if row["exercise_id"] == "ssb_squat")
        assert lift["status"] == "up"
        assert lift["change_pct"] > 2.5
        assert lift["baseline_n"] >= 4
        assert lift["current_n"] >= 4
        assert report["attendance"]["target"] == 24
        assert report["work"]["status"] == "unknown"
        assert "no causal claim" in report["note"]
    finally:
        store.close()


def test_prospective_without_history_is_unknown():
    store = db.Store(":memory:")
    try:
        report = prospective.report(store.connection, weeks=4, on_date="2024-03-01")
        assert report["strength"]["lifts"] == []
        assert report["attendance"]["target"] is None
        assert report["rir"]["adherence"] is None
        assert report["duration"]["median_min"] is None
        assert report["symptoms"]["regions"] == {}
    finally:
        store.close()
