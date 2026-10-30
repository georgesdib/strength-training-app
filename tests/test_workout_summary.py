"""Phase 2 descriptive workout summary."""

from __future__ import annotations

import json

import pytest

from strength_coach import cli, workout
from strength_coach.store import db

PLAN = {
    "for_date": "2024-01-01",
    "session_type": "hinge",
    "items": [
        {
            "exercise_id": "trap_bar_deadlift",
            "sets": 2,
            "reps_low": 3,
            "reps_high": 5,
            "load_kg": 100,
            "rir_target": 2,
            "e1rm_kg": 120.0,
            "e1rm_ref": "set:s0/1",
            "e1rm_quality": "ok",
            "e1rm_age_days": 2,
        },
        {
            "exercise_id": "competition_bench_press",
            "sets": 2,
            "reps_low": 5,
            "reps_high": 5,
            "load_kg": 80,
            "rir_target": 2,
        },
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


def test_summary_has_completion_strength_dose_special_and_feedback(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="competition_bench_press",
        load_kg=80, reps=5, rir=2,
    )
    ended = workout.end(
        conn, started["workout_id"], session_rpe=7, duration_min=50,
        productivity=4, notes="summary test",
    )
    summary = workout.summary(conn, ended["workout_id"])

    assert summary["status"] == "completed"
    assert summary["completion"]["planned_sets"] == 4
    assert summary["completion"]["completed_sets"] == 3
    assert summary["basis"] == {
        "performance": "raw_formula_epley_rir",
        "decay": "not_applied",
        "calibration": "not_applied",
    }
    assert summary["feedback"]["srpe"] == 7.0
    assert summary["feedback"]["duration_min"] == 50.0
    assert summary["feedback"]["session_load_au"] == 350.0
    assert summary["feedback"]["productivity"] == 4
    assert summary["dose"]["per_exercise"]
    assert summary["dose"]["relative_intensity"]["n"] == 3
    assert summary["dose"]["relative_intensity"]["excluded_total"] == 0
    assert summary["strength"]
    assert summary["strength"][0]["post"]["status"] == "estimated"
    assert "score" not in summary
    assert summary["comparison"]["status"] == "unavailable"


def test_summary_exposes_power_velocity_and_not_recorded_quality_stop(conn):
    plan = {
        "for_date": "2024-01-01",
        "session_type": "hinge",
        "items": [{
            "exercise_id": "jump_squats", "sets": 2, "reps_low": 5,
            "reps_high": 5, "load_kg": 20, "rir_target": None,
            "quality_stop": "stop when height drops",
        }],
    }
    started = workout.start(conn, for_date="2024-01-01", plan=plan, readiness=READINESS)
    workout.add_set(
        conn, started["workout_id"], exercise_id="jump_squats",
        load_kg=20, reps=5, rir=4, velocity=0.50,
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="jump_squats",
        load_kg=20, reps=5, rir=4, velocity=0.45,
    )
    ended = workout.end(conn, started["workout_id"], session_rpe=6, duration_min=20)
    summary = workout.summary(conn, ended["workout_id"])

    power = summary["special"]["power"]
    assert power["sets"] == 2
    assert len(power["mean_velocity_change"]) == 1
    assert power["mean_velocity_change"][0]["change_pct"] == pytest.approx(-10.0)
    assert summary["special"]["quality_stop"]["status"] == "not_recorded"


def test_summary_rejects_in_progress(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)

    with pytest.raises(workout.WorkoutNotCompleted):
        workout.summary(conn, started["workout_id"])


def test_cli_summary_json_uses_the_same_payload(tmp_path, capsys):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    try:
        started = workout.start(
            store.connection, for_date="2024-01-01", plan=PLAN, readiness=READINESS
        )
        workout.add_set(
            store.connection, started["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=5, rir=2,
        )
        workout.end(
            store.connection, started["workout_id"], session_rpe=7, duration_min=50,
            productivity=4,
        )
    finally:
        store.close()

    assert cli.main(["--db", str(path), "summary", started["workout_id"], "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["feedback"]["productivity"] == 4


def test_summary_missing_workout_is_a_value_error(conn):
    with pytest.raises(ValueError, match="not found"):
        workout.summary(conn, "missing")
