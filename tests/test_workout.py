"""Live workout: required readiness, append-only sets, measured/manual end."""

from __future__ import annotations

import pytest

from strength_coach import workout
from strength_coach.store import db

PLAN = {
    "for_date": "2024-01-01",
    "session_day": "B",
    "session_type": "hinge",
    "items": [
        {"exercise_id": "trap_bar_deadlift", "sets": 5, "reps_low": 3,
         "reps_high": 5, "load_kg": 100, "rir_target": 2},
        {"exercise_id": "competition_bench_press", "sets": 3, "reps_low": 5,
         "reps_high": 5, "load_kg": 80, "rir_target": 2},
    ],
}
READINESS = {
    "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
    "nutrition": 4, "hydration": 4,
}


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def test_start_requires_all_seven_readiness_fields(conn):
    with pytest.raises(ValueError, match="readiness.energy"):
        workout.start(conn, for_date="2024-01-01", plan=PLAN,
                      readiness={**READINESS, "energy": None})
    assert workout.active_workout(conn) is None


def test_start_add_remove_and_end(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    assert started["status"] == "in_progress"
    assert workout.active_workout(conn)["workout_id"] == started["workout_id"]

    with pytest.raises(ValueError, match="already in progress"):
        workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)

    added = workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                            load_kg=100, reps=5, rir=2)
    assert len(added["sets"]) == 1
    set_id = added["sets"][0]["set_id"]

    removed = workout.remove_set(conn, started["workout_id"], set_id)
    assert removed["sets"] == []

    ended = workout.end(conn, started["workout_id"], session_rpe=7,
                        duration_min=55, notes="felt good")
    assert ended["status"] == "completed"
    assert ended["duration_source"] == "manual"
    assert ended["duration_min"] == 55
    assert ended["session_rpe_recorded"] == 1
    assert workout.active_workout(conn) is None


def test_end_requires_srpe_or_explicit_not_recorded(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    with pytest.raises(ValueError, match="session_rpe"):
        workout.end(conn, started["workout_id"], session_rpe=None)
    ended = workout.end(conn, started["workout_id"], session_rpe=None, not_recorded=True)
    assert ended["session_rpe_recorded"] == 0
    assert ended["session_rpe"] is None


def test_end_materialises_session_and_comparison(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                    load_kg=100, reps=5, rir=2)
    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)

    session = conn.execute(
        "SELECT session_id, source, workout_id, prescription_id, set_count,"
        " working_set_count, session_rpe FROM session WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()
    assert session["source"] == "workout"
    assert session["workout_id"] == started["workout_id"]
    assert session["set_count"] == 1
    assert session["working_set_count"] == 1
    assert session["session_rpe"] == 7
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM clean_set WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()["c"] == 1
    assert ended["comparison"]["items"][0]["status"] == "under"
    assert ended["comparison"]["items"][1]["status"] == "missing"


def test_end_scores_rubric_and_review_closes_workout(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                    load_kg=100, reps=5, rir=2)
    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)
    assert ended["critique_id"]
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM critique WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()["c"] == 1
    assert workout.mark_reviewed(conn, started["workout_id"]) is True
    assert workout.mark_reviewed(conn, started["workout_id"]) is False
    assert workout.get(conn, started["workout_id"])["reviewed_at"]


def test_plan_overrides_keep_the_original_prescription(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    swapped = workout.swap_exercise(
        conn, started["workout_id"], 0, "conventional_deadlift"
    )
    assert swapped["original_plan"]["items"][0]["exercise_id"] == "trap_bar_deadlift"
    assert swapped["plan"]["items"][0]["exercise_id"] == "conventional_deadlift"
    assert swapped["plan"]["items"][0]["substitution_for"] == "trap_bar_deadlift"
    assert swapped["plan"]["items"][0]["load_kg"] is None
    assert swapped["plan_modified"] is True

    added = workout.add_exercise(
        conn, started["workout_id"], exercise_id="lat_pulldown", sets=2,
        reps_low=10, reps_high=12,
    )
    assert any(item["exercise_id"] == "lat_pulldown" for item in added["plan"]["items"])
    assert len(added["original_plan"]["items"]) == 2

    changed = workout.change_sets(conn, started["workout_id"], 0, 1)
    assert changed["plan"]["items"][0]["sets"] == 6
    removed = workout.remove_exercise(conn, started["workout_id"], 2)
    assert all(item["exercise_id"] != "lat_pulldown" for item in removed["plan"]["items"])
    assert len(removed["plan"]["items"]) == 2
