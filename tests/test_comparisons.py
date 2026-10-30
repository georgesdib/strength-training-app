"""Comparable-session descriptive summary tests."""

from __future__ import annotations

from strength_coach import workout
from strength_coach.features import comparisons
from strength_coach.store import db

READINESS = {
    "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
    "nutrition": 4, "hydration": 4,
}


def _plan(day: str):
    return {
        "for_date": day,
        "session_type": "hinge",
        "items": [{
            "exercise_id": "trap_bar_deadlift", "sets": 1, "reps_low": 5,
            "reps_high": 5, "load_kg": 100, "rir_target": 2,
        }],
    }


def test_three_prior_same_type_sessions_are_comparable():
    with db.Store(":memory:") as store:
        conn = store.connection
        current = None
        for day in ("2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22"):
            started = workout.start(conn, for_date=day, plan=_plan(day), readiness=READINESS)
            workout.add_set(
                conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                load_kg=100, reps=5, rir=2,
            )
            current = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)

        result = comparisons.comparable_sessions(conn, current["workout_id"])

    assert result["status"] == "available"
    assert result["n"] == 3
    assert result["key"] == "same_type+main_lift+overlap"
    assert result["metrics"]["working_sets"] == 1.0


def test_fewer_than_three_priors_is_unavailable():
    with db.Store(":memory:") as store:
        conn = store.connection
        current = None
        for day in ("2024-01-01", "2024-01-08"):
            started = workout.start(conn, for_date=day, plan=_plan(day), readiness=READINESS)
            workout.add_set(
                conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                load_kg=100, reps=5, rir=2,
            )
            current = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)

        result = comparisons.comparable_sessions(conn, current["workout_id"])

    assert result["status"] == "unavailable"
    assert result["n"] == 1
