"""Training days group session fragments without merging them."""

from __future__ import annotations

import datetime as dt

from strength_coach import history, workout
from strength_coach.features import attendance, strength_trend, training_day
from strength_coach.prescribe import volume_budget
from strength_coach.store import db

PLAN = {
    "for_date": "2024-01-01",
    "session_type": "hinge",
    "items": [
        {"exercise_id": "trap_bar_deadlift", "sets": 1, "reps_low": 5,
         "reps_high": 5, "load_kg": 100, "rir_target": 2},
    ],
}
SECOND_PLAN = {
    **PLAN,
    "session_type": "squat",
}
READINESS = {
    "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
    "nutrition": 4, "hydration": 4,
}


def _fragment(conn, plan=PLAN, *, load=100):
    started = workout.start(conn, for_date="2024-01-01", plan=plan, readiness=READINESS)
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=load, reps=5, rir=2,
    )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)
    return started["workout_id"]


def test_two_fragments_are_one_training_day():
    store = db.Store(":memory:")
    try:
        _fragment(store.connection)
        _fragment(store.connection, load=110)
        days = training_day.group(store.connection)
        assert len(days) == 1
        day = days[0]
        assert day["occurred_on"] == "2024-01-01"
        assert day["fragment_count"] == 2
        assert day["session_type"] == "hinge"
        assert day["planned_type"] == "hinge"
        assert day["set_count"] == 2
        assert day["working_set_count"] == 2
        assert day["duration_min"] == 60.0

        attendance_summary = attendance.summary(
            store.connection, start=dt.date(2024, 1, 1),
            end=dt.date(2024, 1, 7), weeks=1,
        )
        assert attendance_summary["completed"] == 1
        assert volume_budget.completed_sessions(
            store.connection, on_date="2024-01-01"
        ) == 1
    finally:
        store.close()


def test_different_fragment_types_display_as_mixed():
    store = db.Store(":memory:")
    try:
        _fragment(store.connection)
        _fragment(store.connection, plan=SECOND_PLAN)
        day = training_day.group(store.connection)[0]
        assert day["session_type"] == "mixed"
        assert day["planned_type"] is None
    finally:
        store.close()


def test_e1rm_uses_one_best_observation_per_training_day():
    store = db.Store(":memory:")
    try:
        _fragment(store.connection, load=100)
        _fragment(store.connection, load=110)
        points = strength_trend.observations(
            store.connection, "trap_bar_deadlift", "2024-01-01", "2024-01-01"
        )
        assert len(points) == 1
        # The 110 kg fragment must win, not the first or latest fragment.
        assert points[0].estimate.load_kg == 110.0
    finally:
        store.close()


def test_history_groups_fragments_under_one_day():
    store = db.Store(":memory:")
    try:
        first = _fragment(store.connection)
        second = _fragment(store.connection)
        data = history.list_training_days(store.connection)
        assert data["total"] == 1
        day = data["days"][0]
        assert {item["session_id"] for item in day["fragments"]} == {first, second}
        assert day["set_count"] == 2
    finally:
        store.close()
