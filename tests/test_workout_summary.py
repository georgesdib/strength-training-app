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
    # DEC-AFC-01: adherence is the single metric source; the duplicate count block is gone.
    assert "completion" not in summary
    assert summary["adherence"]["status"] == "available"
    assert summary["adherence"]["final_plan"]["set_completion"]["denominator"] == 4
    assert summary["quality"]["flags"]
    evidence = summary["evidence"]
    assert evidence
    assert all(item["evidence_id"].startswith("ev:") for item in evidence)
    assert {item["source"] for item in evidence} >= {"adherence.set_completion"}
    assert all(item["window"] == {"start": "2024-01-01", "end": "2024-01-01"}
               for item in evidence)
    # Same rows and window reproduce the same ids.
    assert workout.summary(conn, ended["workout_id"])["evidence"] == evidence
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


def _finish(conn, rir):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    for _ in range(2):
        workout.add_set(
            conn, started["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=5, rir=rir,
        )
    for _ in range(2):
        workout.add_set(
            conn, started["workout_id"], exercise_id="competition_bench_press",
            load_kg=80, reps=5, rir=rir,
        )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)
    return workout.summary(conn, started["workout_id"])


def test_summary_observation_reports_rir_deviation(conn):
    payload = _finish(conn, rir=4)
    observation = payload["observation"]
    assert observation is not None
    assert observation["family"] == "rir"
    assert observation["gate"] == "signal"
    assert observation["evidence_id"].startswith("ev:")
    assert "RIR averaged" in observation["text"]
    assert observation["evidence"]["limitations"]


def test_summary_observation_absent_when_nothing_qualifies(conn):
    payload = _finish(conn, rir=2)
    assert payload["observation"] is None
    # The report still carries its evidence and quality sections.
    assert payload["evidence"]


def test_summary_observation_reports_incomplete_work(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=45)
    payload = workout.summary(conn, started["workout_id"])
    observation = payload["observation"]
    assert observation is not None
    assert observation["family"] == "incomplete_work"
    assert "not filled" in observation["text"]
