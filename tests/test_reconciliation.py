"""Late reconciliation: completion must not discard events from an unreachable device (D8)."""

from __future__ import annotations

import json

import pytest

from strength_coach import reconciliation, workout
from strength_coach.store import db

PLAN = {
    "for_date": "2026-11-01",
    "session_type": "squat",
    "items": [
        {"order_index": 0, "exercise_id": "trap_bar_deadlift", "sets": 4,
         "reps_low": 3, "reps_high": 5, "load_kg": 150.0, "rir_target": 2},
        {"order_index": 1, "exercise_id": "bench_press", "sets": 3,
         "reps_low": 5, "reps_high": 5, "load_kg": 90.0, "rir_target": 2},
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


def _started(conn):
    return workout.start(conn, for_date="2026-11-01", plan=PLAN, readiness=READINESS)


def _finish(conn, workout_id, pending=None):
    return workout.end(
        conn, workout_id, session_rpe=7, not_recorded=False,
        pending_devices=pending,
    )


def _events(conn, workout_id, event_type):
    return [
        json.loads(row["payload_json"])
        for row in conn.execute(
            "SELECT payload_json FROM workout_event "
            "WHERE workout_id = ? AND event_type = ? ORDER BY event_id",
            (workout_id, event_type),
        )
    ]


def test_a_finish_with_a_pending_device_opens_the_window(conn):
    started = _started(conn)
    _finish(conn, started["workout_id"], pending=["watch-1"])
    state = reconciliation.state(conn, started["workout_id"])
    assert state["state"] == "open"
    assert state["pending_devices"] == ["watch-1"]
    assert state["closes_at"] is not None


def test_a_finish_without_pending_devices_opens_nothing(conn):
    started = _started(conn)
    _finish(conn, started["workout_id"])
    assert reconciliation.state(conn, started["workout_id"])["state"] == "none"


def test_a_late_set_is_applied_to_the_durable_record(conn):
    started = _started(conn)
    workout_id = started["workout_id"]
    workout.add_set(conn, workout_id, exercise_id="bench_press", load_kg=90.0,
                    reps=5, rir=2, set_index=1, plan_item_index=1)
    _finish(conn, workout_id, pending=["watch-1"])

    before = conn.execute(
        "SELECT set_count, working_set_count FROM session WHERE session_id = ?",
        (workout_id,),
    ).fetchone()
    workout.add_set(conn, workout_id, exercise_id="bench_press", load_kg=95.0,
                    reps=5, rir=1, set_index=2, late=True)

    after = conn.execute(
        "SELECT set_count, working_set_count FROM session WHERE session_id = ?",
        (workout_id,),
    ).fetchone()
    assert after["set_count"] == before["set_count"] + 1
    assert after["working_set_count"] == before["working_set_count"] + 1
    assert conn.execute(
        "SELECT COUNT(*) FROM clean_set WHERE session_id = ?", (workout_id,)
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM workout_set WHERE workout_id = ?", (workout_id,)
    ).fetchone()[0] == 2
    assert _events(conn, workout_id, reconciliation.EVENT_LATE_SET)[0]["set_index"] == 2
    assert workout.summary(conn, workout_id)["reconciliation"]["state"] == "open"


def test_a_late_set_after_the_window_is_preserved_and_refused(conn, monkeypatch):
    started = _started(conn)
    workout_id = started["workout_id"]
    monkeypatch.setattr(reconciliation, "window_days", lambda conn=None: 0)
    _finish(conn, workout_id, pending=["watch-1"])
    assert reconciliation.state(conn, workout_id)["state"] == "closed"

    with pytest.raises(reconciliation.WindowClosed) as raised:
        workout.add_set(conn, workout_id, exercise_id="bench_press", load_kg=95.0,
                        reps=5, rir=1, set_index=1, late=True)
    assert raised.value.payload["exercise_id"] == "bench_press"

    # The caller preserves the arrival; nothing was written to the training rows.
    with db.transaction(conn):
        reconciliation.record_rejection(conn, workout_id, raised.value.payload)
    assert conn.execute(
        "SELECT COUNT(*) FROM workout_set WHERE workout_id = ?", (workout_id,)
    ).fetchone()[0] == 0
    rejected = _events(conn, workout_id, reconciliation.EVENT_REJECTED)
    assert rejected[0]["exercise_id"] == "bench_press"
    assert rejected[0]["reason"] == "reconciliation_window_closed"


def test_a_late_set_is_refused_when_no_window_was_opened(conn):
    started = _started(conn)
    _finish(conn, started["workout_id"])
    with pytest.raises(ValueError, match="not in progress"):
        workout.add_set(conn, started["workout_id"], exercise_id="bench_press",
                        load_kg=95.0, reps=5, rir=1, set_index=1, late=True)
    assert _events(conn, started["workout_id"], reconciliation.EVENT_REJECTED) == []


def test_the_finish_is_idempotent_and_can_still_name_pending_devices(conn):
    started = _started(conn)
    workout_id = started["workout_id"]
    _finish(conn, workout_id)
    _finish(conn, workout_id, pending=["watch-1"])
    state = reconciliation.state(conn, workout_id)
    assert state["state"] == "open"
    assert state["pending_devices"] == ["watch-1"]


def test_resolving_the_last_device_closes_the_window(conn):
    started = _started(conn)
    workout_id = started["workout_id"]
    _finish(conn, workout_id, pending=["watch-1", "watch-2"])

    state = reconciliation.resolve_device(conn, workout_id, "watch-1")
    assert state["state"] == "open"
    assert state["pending_devices"] == ["watch-2"]

    state = reconciliation.resolve_device(conn, workout_id, "watch-2")
    assert state["state"] == "closed"
    assert state["pending_devices"] == []
    assert state.get("resolved") is True


def test_resolving_an_unknown_or_repeated_device_is_a_no_op(conn):
    started = _started(conn)
    workout_id = started["workout_id"]
    _finish(conn, workout_id, pending=["watch-1"])

    assert reconciliation.resolve_device(conn, workout_id, "watch-9")["state"] == "open"
    reconciliation.resolve_device(conn, workout_id, "watch-1")
    before = conn.execute(
        "SELECT COUNT(*) FROM workout_event WHERE workout_id = ? "
        "AND event_type = 'reconciliation_resolved'",
        (workout_id,),
    ).fetchone()[0]
    reconciliation.resolve_device(conn, workout_id, "watch-1")
    after = conn.execute(
        "SELECT COUNT(*) FROM workout_event WHERE workout_id = ? "
        "AND event_type = 'reconciliation_resolved'",
        (workout_id,),
    ).fetchone()[0]
    assert before == after == 1



def test_a_late_form_rating_reaches_the_durable_session(conn):
    started = _started(conn)
    workout_id = started["workout_id"]
    _finish(conn, workout_id, pending=["watch-1"])
    workout.set_form_rating(
        conn, workout_id, exercise_id="bench_press", rating=4, note="solid",
        late=True,
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM session_form_rating WHERE session_id = ?", (workout_id,)
    ).fetchone()[0] == 1
    assert workout.get(conn, workout_id)["forms"][0]["rating"] == 4


def test_a_late_form_rating_after_the_window_is_preserved(conn, monkeypatch):
    started = _started(conn)
    workout_id = started["workout_id"]
    monkeypatch.setattr(reconciliation, "window_days", lambda conn=None: 0)
    _finish(conn, workout_id, pending=["watch-1"])
    with pytest.raises(reconciliation.WindowClosed) as raised:
        workout.set_form_rating(
            conn, workout_id, exercise_id="bench_press", rating=4, late=True,
        )
    assert raised.value.payload["rating"] == 4


def test_a_rejected_late_set_keeps_its_rep_velocities(conn, monkeypatch):
    started = _started(conn)
    workout_id = started["workout_id"]
    monkeypatch.setattr(reconciliation, "window_days", lambda conn=None: 0)
    _finish(conn, workout_id, pending=["watch-1"])
    with pytest.raises(reconciliation.WindowClosed) as raised:
        workout.add_set(
            conn, workout_id, exercise_id="bench_press", load_kg=90.0, reps=2,
            rir=2, set_index=1, late=True,
            rep_velocities=[{"rep_index": 1, "velocity_mps": 0.61},
                            {"rep_index": 2, "velocity_mps": 0.58}],
        )
    assert raised.value.payload["rep_velocities"][0]["velocity_mps"] == 0.61

