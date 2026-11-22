"""Per-rep motion capture: payload rules, storage and the descriptive report."""

from __future__ import annotations

import inspect
import json

import pytest

from strength_coach import workout
from strength_coach.features import rep_tempo
from strength_coach.store import db

PLAN = {
    "for_date": "2026-11-01",
    "session_type": "squat",
    "items": [
        {"order_index": 0, "exercise_id": "competition_squat", "sets": 3,
         "reps_low": 3, "reps_high": 3, "load_kg": 140.0, "rir_target": 2},
        {"order_index": 1, "exercise_id": "hip_thrust", "sets": 3,
         "reps_low": 6, "reps_high": 6, "load_kg": 80.0, "rir_target": 2},
    ],
}
READINESS = {
    "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
    "nutrition": 4, "hydration": 4,
}

MOTION = [
    {"rep_index": 1, "velocity_mps": 0.62, "lower_ms": 1450, "lift_ms": 620,
     "pause_ms": 180, "rom_m": 0.41, "confidence": 0.93},
    {"rep_index": 2, "velocity_mps": 0.58, "lower_ms": 1510, "lift_ms": 690,
     "pause_ms": 120, "rom_m": 0.40, "confidence": 0.91},
    {"rep_index": 3, "velocity_mps": 0.54, "lower_ms": 1620, "lift_ms": 780,
     "pause_ms": 90, "rom_m": 0.39, "confidence": 0.88},
]


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def _started(conn):
    return workout.start(conn, for_date="2026-11-01", plan=PLAN, readiness=READINESS)


def _events(conn, workout_id):
    rows = conn.execute(
        "SELECT reps_json, source, motion_version FROM workout_rep_event "
        "WHERE workout_id = ? ORDER BY event_id",
        (workout_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def test_legacy_payload_is_stored_byte_identically(conn):
    started = _started(conn)
    workout.add_set(
        conn, started["workout_id"], exercise_id="competition_squat", load_kg=140,
        reps=3, rir=2, source="manual",
        rep_velocities=[
            {"rep_index": 1, "velocity_mps": 0.62},
            {"rep_index": 2, "velocity_mps": 0.58},
        ],
    )
    event = _events(conn, started["workout_id"])[0]
    assert event["reps_json"] == (
        '[{"rep_index":1,"velocity_mps":0.62},{"rep_index":2,"velocity_mps":0.58}]'
    )
    assert event["motion_version"] is None


def test_motion_payload_is_stored_and_materialised(conn):
    started = _started(conn)
    workout.add_set(
        conn, started["workout_id"], exercise_id="competition_squat", load_kg=140,
        reps=3, rir=2, source="manual", rep_velocities=MOTION, motion_version="tempo/1",
    )
    event = _events(conn, started["workout_id"])[0]
    assert event["motion_version"] == "tempo/1"
    assert json.loads(event["reps_json"])[0]["lower_ms"] == 1450

    workout.end(conn, started["workout_id"], session_rpe=7)

    reps = conn.execute("SELECT COUNT(*) AS n FROM clean_rep").fetchone()["n"]
    phases = conn.execute(
        "SELECT rep_index, lower_ms, method_version FROM clean_rep_phase ORDER BY rep_index"
    ).fetchall()
    assert reps == 3
    assert [row["rep_index"] for row in phases] == [1, 2, 3]
    assert phases[0]["lower_ms"] == 1450
    assert phases[0]["method_version"] == "tempo/1"


def test_tempo_only_set_writes_phase_but_no_clean_rep(conn):
    started = _started(conn)
    tempo_only = [
        {key: value for key, value in rep.items() if key != "velocity_mps"}
        for rep in MOTION
    ]
    workout.add_set(
        conn, started["workout_id"], exercise_id="competition_squat", load_kg=140,
        reps=3, rir=2, source="device", rep_velocities=tempo_only,
        motion_version="tempo/1",
    )
    workout.end(conn, started["workout_id"], session_rpe=7)

    assert conn.execute("SELECT COUNT(*) AS n FROM clean_rep").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM clean_rep_phase").fetchone()["n"] == 3


@pytest.mark.parametrize(
    ("reps", "payload", "version", "reason"),
    [
        (3, MOTION[:2], "tempo/1", "count_mismatch"),
        (3, [MOTION[0], MOTION[1], {**MOTION[2], "rep_index": 4}], "tempo/1", "index_gap"),
        (3, [MOTION[0], {**MOTION[1], "rep_index": 1}, MOTION[2]], "tempo/1", "index_duplicate"),
        (3, MOTION[:2] + [{**MOTION[2], "velocity_mps": None}], "tempo/1", "mixed_velocity"),
        (3, MOTION, None, "version_missing"),
        (3, MOTION, "tempo one", "version_format"),
        (3, [MOTION[0], MOTION[1], {**MOTION[2], "confidence": 2.0}], "tempo/1", "range"),
    ],
)
def test_invalid_motion_payload_is_rejected_atomically(conn, reps, payload, version, reason):
    started = _started(conn)
    with pytest.raises(workout.MotionPayloadError) as failure:
        workout.add_set(
            conn, started["workout_id"], exercise_id="competition_squat", load_kg=140,
            reps=reps, rir=2, source="device", rep_velocities=payload,
            motion_version=version,
        )
    assert failure.value.reason == reason
    assert _events(conn, started["workout_id"]) == []


def test_frozen_plan_carries_the_capture_axis(conn):
    started = _started(conn)
    axes = {
        item["exercise_id"]: item.get("motion_axis")
        for item in started["plan"]["items"]
    }
    assert axes["competition_squat"] == "vertical"
    assert axes["hip_thrust"] is None


def test_report_summarises_captured_sets_and_abstains_otherwise(conn):
    started = _started(conn)
    workout.add_set(
        conn, started["workout_id"], exercise_id="competition_squat", load_kg=140,
        reps=3, rir=2, source="device", rep_velocities=MOTION, motion_version="tempo/1",
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="hip_thrust", load_kg=80,
        reps=6, rir=2, source="manual",
    )
    workout.end(conn, started["workout_id"], session_rpe=7)

    report = rep_tempo.session_report(conn, started["workout_id"])
    assert report["captured_sets"] == 1
    captured = [item for item in report["sets"] if item["abstention"] is None][0]
    assert captured["reps"] == 3
    assert captured["lower_median_ms"] == 1510
    assert captured["tut_s"] == 7.1
    assert sum(1 for item in report["sets"] if item["abstention"] == "no_detail") == 1


def test_report_module_has_no_training_imports():
    imports = [
        line for line in inspect.getsource(rep_tempo).splitlines()
        if line.startswith(("import ", "from "))
    ]
    joined = " ".join(imports)
    for forbidden in ("prescribe", "readiness", "rules", "calibration"):
        assert forbidden not in joined
