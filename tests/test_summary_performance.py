"""The completed-workout summary must stay cheap enough for a mobile client.

Each relative-strength ratio walks the whole lift history, so the summary computes them only
when the caller renders them, and it shares one clean-set read across its sections. These are
structural guards rather than wall-clock assertions, so they cannot flake on a slow machine.
"""

from __future__ import annotations

import contextlib

import pytest

from strength_coach import workout
from strength_coach.features import relative_strength
from strength_coach.store import db, queries

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


@pytest.fixture
def completed(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="competition_bench_press",
        load_kg=80, reps=5, rir=2,
    )
    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=45)
    return ended["workout_id"]


class _Relationship:
    relationship_id = "tbdl_bench"
    label = "Trap-bar deadlift / Bench press"
    numerator = "trap_bar_deadlift"
    denominator = "competition_bench_press"
    max_age_days = 56


def test_summary_without_ratios_never_walks_history(conn, completed, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("relative-strength ratios must not be computed")

    monkeypatch.setattr(relative_strength, "current_ratio", boom)
    payload = workout.summary(conn, completed, include_ratios=False)
    # The key stays present so the payload shape is stable for every caller.
    assert payload["ratios"] == []


def test_summary_with_ratios_computes_the_matching_relationship(conn, completed, monkeypatch):
    calls = []
    monkeypatch.setattr(relative_strength, "load_relationships", lambda: [_Relationship()])
    monkeypatch.setattr(
        relative_strength,
        "current_ratio",
        lambda *args, **kwargs: calls.append(args[1].relationship_id) or {"ok": True},
    )
    payload = workout.summary(conn, completed)
    assert payload["ratios"] == [{"ok": True}]
    assert calls == ["tbdl_bench"]


def test_summary_runs_inside_the_clean_set_snapshot(conn, completed, monkeypatch):
    used = []
    real = queries.clean_sets_snapshot

    @contextlib.contextmanager
    def spy(connection):
        used.append(connection)
        with real(connection):
            yield

    monkeypatch.setattr(queries, "clean_sets_snapshot", spy)
    workout.summary(conn, completed, include_ratios=False)
    assert used == [conn]
