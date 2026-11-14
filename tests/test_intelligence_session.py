"""get_session_details: composition, routing and projection."""

from __future__ import annotations

import json

import pytest
from conftest import make_readiness, make_training
from intelligence_support import service

from strength_coach import history, workout
from strength_coach.intelligence import INTERNAL_PRINCIPAL
from strength_coach.store import db, importer

PLAN = {
    "for_date": "2026-11-02",
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


@pytest.fixture()
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def _completed_workout(conn) -> str:
    started = workout.start(
        conn, for_date=PLAN["for_date"], plan=PLAN, readiness=READINESS
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="competition_bench_press",
        load_kg=80, reps=5, rir=2,
    )
    workout.end(
        conn, started["workout_id"], session_rpe=7, duration_min=50,
        productivity=4, notes="private note text",
    )
    return started["workout_id"]


def _session(conn, **arguments):
    return service(conn).execute(
        INTERNAL_PRINCIPAL, "get_session_details", arguments
    )


def test_workout_detail_uses_the_existing_summary(conn):
    workout_id = _completed_workout(conn)
    result = _session(conn, workout_id=workout_id)
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "ok"
    assert env.facts["session"].value["source"] == "workout"
    assert env.facts["session"].value["date"] == "2026-11-02"
    assert env.facts["feedback"].value["srpe"] == 7.0
    assert "strength" in env.facts and "dose" in env.facts
    assert env.evidence, "the summary supplies real evidence items"
    assert env.provenance.services[0][0] == "strength_coach.workout"
    assert env.period.start == env.period.end == "2026-11-02"


def test_notes_and_health_fields_never_leave_the_capability(conn):
    workout_id = _completed_workout(conn)
    env = _session(conn, workout_id=workout_id).envelope
    text = json.dumps(env.as_dict())
    assert "private note text" not in text
    for forbidden in ("attributed_symptoms", "workout_note", "notes\":"):
        assert forbidden not in text
    assert "session notes" in env.privacy.excluded_fields


def test_session_id_resolves_a_workout_session(conn):
    workout_id = _completed_workout(conn)
    result = _session(conn, session_id=workout_id)
    assert result.ok, result.error
    assert result.envelope.facts["session"].value["source"] == "workout"
    assert result.envelope.evidence


def test_imported_session_reports_sets_and_unavailable_analysis(conn):
    training = make_training([
        {"Date": "2026-10-19", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2026-10-26", "Exercise": "Trap Bar Deadlift", "Weight_Used": "155",
         "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{}])
    importer.import_export(
        conn, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    session_id = "2026-10-19"
    result = _session(conn, session_id=session_id)
    assert result.ok, result.error
    env = result.envelope
    assert env.facts["session"].value["source"] == "imported"
    assert env.facts["sets"].n == len(env.facts["sets"].value)
    assert env.facts["sets"].value[0]["exercise_id"] == "trap_bar_deadlift"
    assert env.facts["adherence"].value["status"] != "available"
    assert env.evidence == ()
    assert any("Imported" in limitation for limitation in env.limitations)


def test_voided_imported_session_is_no_data(conn):
    training = make_training([
        {"Date": "2026-10-19", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{}])
    importer.import_export(
        conn, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    history.void_session(conn, "2026-10-19", reason="duplicate")
    result = _session(conn, session_id="2026-10-19")
    assert result.ok
    assert result.envelope.status == "no_data"
    assert "session is voided" in result.envelope.missing


def test_active_workout_is_invalid_state(conn):
    started = workout.start(
        conn, for_date="2026-11-02", plan=PLAN, readiness=READINESS
    )
    result = _session(conn, workout_id=started["workout_id"])
    assert not result.ok
    assert result.error.code == "invalid_state"


def test_unknown_identifiers_are_not_found(conn):
    assert _session(conn, workout_id="missing").error.code == "not_found"
    assert _session(conn, session_id="missing").error.code == "not_found"


@pytest.mark.parametrize(
    "arguments, field",
    [
        ({}, "session_id"),
        ({"workout_id": "a", "session_id": "b"}, "workout_id"),
        ({"workout_id": ""}, "workout_id"),
        ({"workout_id": 3}, "workout_id"),
        ({"workout_id": "x", "include_ratios": "yes"}, "include_ratios"),
        ({"workout_id": "x", "bogus": 1}, "bogus"),
    ],
)
def test_invalid_arguments_are_rejected(conn, arguments, field):
    result = _session(conn, **arguments)
    assert not result.ok
    assert result.error.code == "invalid_argument"
    assert result.error.field == field


def test_include_ratios_is_accepted(conn):
    workout_id = _completed_workout(conn)
    result = _session(conn, workout_id=workout_id, include_ratios=True)
    assert result.ok


def test_session_detail_is_read_only(conn):
    workout_id = _completed_workout(conn)
    before = conn.total_changes
    tables = ("session", "clean_set", "workout_session", "workout_set", "prescription")
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    assert _session(conn, workout_id=workout_id).ok
    assert conn.total_changes == before
    assert {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables} == counts


def test_session_detail_is_deterministic(conn):
    workout_id = _completed_workout(conn)
    first = _session(conn, workout_id=workout_id).envelope.as_dict()
    second = _session(conn, workout_id=workout_id).envelope.as_dict()
    assert first == second
