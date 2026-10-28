"""Part B residual: VBT only, lift-scoped, both gates (DEC-RESIDUAL-01)."""

from __future__ import annotations

import datetime as dt

from strength_coach.features import residual
from strength_coach.prescribe import persistence
from strength_coach.store import db

ON = "2026-04-30"


def store_with(observations, *, exercise="bench_press", reps=5, basis="lift", second=None):
    """observations: list of (date, velocity). The optional second adds a second lift."""
    lifts = {exercise: observations}
    if second is not None:
        lifts[second[0]] = second[1]
    store = db.Store(":memory:")
    conn = store.connection
    plan = {
        "for_date": observations[0][0] if observations else ON,
        "session_type": "bench_squat",
        "items": [{
            "exercise_id": lift, "sets": 1, "reps_low": reps, "reps_high": reps,
            "load_kg": 80, "load_basis": "e1rm", "rir_target": 2,
            "velocity_target": 0.5,
            "vbt_basis": basis + " · 10 sets/5 sessions",
            "essential": True, "refs": [],
        } for lift in lifts],
    }
    prescription_id = persistence.store_plan(conn, plan)
    for item_index, (lift, rows) in enumerate(lifts.items()):
        for index, (day, velocity) in enumerate(rows):
            workout_id = f"{lift}-{index}"
            conn.execute(
                "INSERT INTO workout_session (workout_id, prescription_id, for_date,"
                " session_type, plan_json, readiness_json, started_at)"
                " VALUES (?, ?, ?, 'squat', '{}', '{}', ?)",
                (workout_id, prescription_id, day, day + "T10:00:00Z"),
            )
            conn.execute(
                "INSERT INTO workout_set (workout_id, exercise_id, set_index, load_kg,"
                " reps, rir, velocity, prescription_item_index)"
                " VALUES (?, ?, 1, 80, ?, 2, ?, ?)",
                (workout_id, lift, reps, velocity, item_index),
            )
    return store


def weeks_of(count, start="2026-02-14", step=3):
    first = dt.date.fromisoformat(start)
    return [((first + dt.timedelta(days=step * index)).isoformat(), 0.46)
            for index in range(count)]


def test_a_small_comparable_sample_is_a_signal_not_an_evaluation():
    store = store_with(weeks_of(6))
    try:
        report = residual.compute(store.connection, ON)
    finally:
        store.close()
    assert report.signal_available is True
    assert report.evaluation_ready is False
    assert len(report.lifts) == 1
    lift = report.lifts[0]
    assert lift.n == 6
    assert lift.gate == "signal"
    assert lift.mean_residual < 0  # slower than the target
    assert lift.calibration_scope == "lift"


def test_fewer_than_five_observations_abstains():
    store = store_with(weeks_of(4))
    try:
        report = residual.compute(store.connection, ON)
    finally:
        store.close()
    assert report.signal_available is False
    assert report.lifts[0].gate == "insufficient"
    assert any("need 5" in reason for reason in report.abstain)


def test_a_family_scoped_target_is_not_used():
    store = store_with(weeks_of(6), basis="family")
    try:
        report = residual.compute(store.connection, ON)
    finally:
        store.close()
    assert report.lifts == ()
    assert any("lift-scoped" in reason for reason in report.abstain)


def test_two_lifts_at_twenty_observations_over_eight_weeks_are_evaluation_ready():
    store = store_with(weeks_of(20, step=3), second=("high_bar_squat", weeks_of(20, step=3)))
    try:
        report = residual.compute(store.connection, ON)
    finally:
        store.close()
    assert {lift.exercise_id for lift in report.lifts} == {"bench_press", "high_bar_squat"}
    assert all(lift.gate == "evaluation" for lift in report.lifts)
    assert report.evaluation_ready is True
