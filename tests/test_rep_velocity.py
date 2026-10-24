"""Descriptive per-rep velocity report; never a prescription input."""

from __future__ import annotations

from strength_coach import workout
from strength_coach.features import rep_velocity
from strength_coach.store import db

PLAN = {
    "for_date": "2024-01-01",
    "session_type": "hinge",
    "items": [{"exercise_id": "trap_bar_deadlift", "sets": 1, "reps_low": 3,
               "reps_high": 5, "load_kg": 100, "rir_target": 2}],
}
READINESS = {
    "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
    "nutrition": 4, "hydration": 4,
}
CSV = """Exercise,Set,RPE,Value,Weight,Reps
Trap Bar Deadlift,1,5,0.72m/s,100kg,3
"""
REPS = """Exercise Name,Set Number,Metric Name,Rep Number,Velocity
Trap Bar Deadlift,1,Mean Concentric Velocity,,0.720
Trap Bar Deadlift,1,Mean Concentric Velocity,1,0.760
Trap Bar Deadlift,1,Mean Concentric Velocity,2,0.720
Trap Bar Deadlift,1,Mean Concentric Velocity,3,0.670
"""


def test_report_after_materialisation():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
        workout.import_csv(conn, started["workout_id"], CSV, apply=True, rep_text=REPS)
        workout.end(conn, started["workout_id"], session_rpe=7, duration_min=20)
        report = rep_velocity.session_report(conn, started["workout_id"])
        assert report["available"] is True
        assert report["set_count"] == 1
        item = report["sets"][0]
        assert item["exercise_id"] == "trap_bar_deadlift"
        assert item["summary"]["count"] == 3
        assert item["summary"]["first"] == 0.76
        assert item["summary"]["last"] == 0.67
        assert "descriptive" in report["note"].lower()
    finally:
        store.close()


def test_analysis_links_sessions_and_marks_small_samples():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        first = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
        workout.import_csv(conn, first["workout_id"], CSV, apply=True, rep_text=REPS)
        workout.end(conn, first["workout_id"], session_rpe=7, duration_min=20)

        plan2 = {**PLAN, "for_date": "2024-01-05"}
        second = workout.start(conn, for_date="2024-01-05", plan=plan2, readiness=READINESS)
        workout.import_csv(conn, second["workout_id"], CSV.replace("0.72m/s", "0.74m/s"),
                           apply=True, rep_text=REPS)
        workout.end(conn, second["workout_id"], session_rpe=6, duration_min=20)

        report = rep_velocity.analysis_report(conn, on_date="2024-01-10", weeks=4)
        assert report["available"] is True
        assert report["session_count"] == 2
        assert report["set_count"] == 2
        assert len(report["sessions"]) == 2
        assert report["sessions"][0]["next"]["days"] == 4
        assert report["sessions"][0]["next"]["delta_pct"] is not None
        assert all(row["status"] == "insufficient" for row in report["correlations"])
        assert report["missing"]["srpe"] == 0
        assert "Descriptive only" in report["note"]
    finally:
        store.close()


def test_analysis_is_empty_and_honest_without_rep_data():
    store = db.Store(":memory:")
    try:
        report = rep_velocity.analysis_report(store.connection, on_date="2024-01-10", weeks=4)
        assert report["available"] is False
        assert report["set_count"] == 0
        assert report["correlations"]
        assert all(row["n"] == 0 and row["status"] == "insufficient"
                   for row in report["correlations"])
        assert "Descriptive only" in report["note"]
    finally:
        store.close()
