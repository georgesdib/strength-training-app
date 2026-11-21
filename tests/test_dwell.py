"""Exercise dwell model: factor, rotation draw, counters, cap and reconcile."""

from __future__ import annotations

import pytest

from strength_coach import settings_profile, workout
from strength_coach.features import dwell
from strength_coach.store import db

PLAN = {
    "for_date": "2026-11-19",
    "session_type": "hinge",
    "items": [
        {"exercise_id": "trap_bar_deadlift", "sets": 5, "reps_low": 3,
         "reps_high": 5, "load_kg": 100, "rir_target": 2},
    ],
}
READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}


def test_factor_is_zero_at_zero_and_saturates() -> None:
    # f(c) = 1 - exp(-c / tau), with tau = 0.5 shipped.
    assert dwell.factor(0, 0.5) == 0.0
    assert dwell.factor(1, 0.5) == pytest.approx(0.8647, abs=1e-4)
    assert dwell.factor(2, 0.5) > 0.98
    assert dwell.factor(10, 0.5) <= 1.0
    assert dwell.factor(-1, 0.5) == 0.0


def test_rotation_value_is_deterministic_and_bounded() -> None:
    first = dwell.rotation_value(
        for_date="2026-11-19", session_type="squat", slot_id="bench_support"
    )
    again = dwell.rotation_value(
        for_date="2026-11-19", session_type="squat", slot_id="bench_support"
    )
    other_slot = dwell.rotation_value(
        for_date="2026-11-19", session_type="squat", slot_id="bench_main"
    )
    assert first == again
    assert 0.0 <= first < 1.0
    assert first != other_slot


def test_record_completion_increments_and_wraps(monkeypatch) -> None:
    store = db.Store(":memory:")
    try:
        conn = store.connection
        monkeypatch.setattr(
            dwell, "done_exercises", lambda *args, **kwargs: {"bench_press"}
        )
        assert dwell.record_completion(
            conn, session_id="s", for_date="2026-11-19", target=2
        ) == 1
        assert dwell.counts(conn)["bench_press"] == 1
        # The second exposure reaches the target and wraps to 0, so the lift re-enters the
        # pool at the least attractive end of the factor.
        assert dwell.record_completion(
            conn, session_id="s", for_date="2026-11-20", target=2
        ) == 1
        assert dwell.counts(conn)["bench_press"] == 0
    finally:
        store.close()


def test_completion_advances_the_counter_once_per_training_day() -> None:
    store = db.Store(":memory:")
    try:
        conn = store.connection
        first = workout.start(conn, for_date="2026-11-19", plan=PLAN, readiness=READINESS)
        workout.add_set(
            conn, first["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=5, rir=2,
        )
        workout.end(conn, first["workout_id"], session_rpe=7, duration_min=30)
        assert dwell.counts(conn).get("trap_bar_deadlift") == 1

        # A second workout on the same date must not advance the same exercise twice: the
        # counter is a count of training days, not of sessions.
        second = workout.start(conn, for_date="2026-11-19", plan=PLAN, readiness=READINESS)
        workout.add_set(
            conn, second["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=5, rir=2,
        )
        workout.end(conn, second["workout_id"], session_rpe=7, duration_min=30)
        assert dwell.counts(conn).get("trap_bar_deadlift") == 1
    finally:
        store.close()


def test_reconcile_zeroes_counters_at_or_above_the_target() -> None:
    store = db.Store(":memory:")
    try:
        conn = store.connection
        dwell.set_count(conn, "over", 6)
        dwell.set_count(conn, "under", 2)
        assert dwell.reconcile(conn, 4) == 1
        counts = dwell.counts(conn)
        assert counts["over"] == 0
        assert counts["under"] == 2
    finally:
        store.close()


def test_retired_rotation_keys_cannot_be_set() -> None:
    store = db.Store(":memory:")
    try:
        with pytest.raises(ValueError, match="retired"):
            settings_profile.save(
                store.connection,
                set_values={"resolver.rotation.main": 0.3},
                effective_from="2026-11-01",
            )
    finally:
        store.close()


def test_lowering_the_dwell_target_reconciles_the_counters() -> None:
    store = db.Store(":memory:")
    try:
        conn = store.connection
        settings_profile.save(
            conn, set_values={"resolver.dwell.target": 7}, effective_from="2026-11-01"
        )
        dwell.set_count(conn, "bench_press_narrow", 6)
        settings_profile.save(
            conn, set_values={"resolver.dwell.target": 4}, effective_from="2026-11-02"
        )
        assert dwell.counts(conn)["bench_press_narrow"] == 0
    finally:
        store.close()
