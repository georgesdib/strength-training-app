"""AFC-4 nudges: one review category, suppressed by an append-only decision."""

from __future__ import annotations

import pytest

from strength_coach import settings_profile, workout
from strength_coach.features import nudges
from strength_coach.store import db, repositories

READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}
DAYS = ("2024-02-01", "2024-02-02", "2024-02-03", "2024-02-04", "2024-02-05")


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def _session(conn, day, *, rir=2):
    item = {
        "exercise_id": "trap_bar_deadlift", "sets": 3, "reps_low": 5,
        "reps_high": 5, "load_kg": 100, "rir_target": 2,
    }
    started = workout.start(
        conn, for_date=day,
        plan={"for_date": day, "session_type": "hinge", "items": [item]},
        readiness=dict(READINESS),
    )
    for _ in range(3):
        workout.add_set(
            conn, started["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=5, rir=rir,
        )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=45)


def _rir_nudge(conn):
    for day in DAYS:
        _session(conn, day, rir=4 if day in DAYS[:3] else 2)
    on_date = "2024-03-01"
    return nudges.current(conn, on_date=on_date), on_date


def test_current_returns_one_review_category(conn):
    nudge, _ = _rir_nudge(conn)
    assert nudge is not None
    assert nudge["category"] == "review"
    assert nudge["family"] == "rir"
    assert nudge["key"].startswith("nudge:rir:")
    assert nudge["evidence"]["limitations"]


def test_dismissal_hides_the_same_evidence(conn):
    nudge, day = _rir_nudge(conn)
    assert nudges.record(
        conn, key=nudge["key"], action="dismiss", on_date=day,
        evidence_id=nudge["evidence_id"],
    ) is None
    assert nudges.current(conn, on_date=day) is None


def test_dismissal_only_covers_the_seen_window(conn):
    nudge, day = _rir_nudge(conn)
    conn.execute(
        "INSERT INTO maintenance_review (review_id, task_key, action, decision, note, reviewed_on) "
        "VALUES ('r1', ?, 'completed', 'not_applicable', 'different-window', ?)",
        (nudge["key"], day),
    )
    again = nudges.current(conn, on_date=day)
    assert again is not None
    assert again["key"] == nudge["key"]


def test_snooze_hides_for_fourteen_days(conn):
    nudge, day = _rir_nudge(conn)
    nudges.record(conn, key=nudge["key"], action="snooze", on_date=day)
    assert nudges.current(conn, on_date="2024-03-10") is None
    assert nudges.current(conn, on_date="2024-03-16") is not None


def test_invalid_decisions_are_rejected(conn):
    nudge, day = _rir_nudge(conn)
    with pytest.raises(ValueError, match="action"):
        nudges.record(conn, key=nudge["key"], action="hide", on_date=day)
    with pytest.raises(ValueError, match="nudge:"):
        nudges.record(conn, key="review:1", action="snooze", on_date=day)
    with pytest.raises(ValueError, match="evidence id"):
        nudges.record(conn, key=nudge["key"], action="dismiss", on_date=day)


def _programme_profile(conn, *, anchor=None, competition=None):
    repositories.append_athlete_profile(
        conn,
        effective_from="2024-01-01",
        block_start_date=anchor,
        competition_date=competition,
    )


def test_scheduled_deload_is_promoted_as_a_programme_nudge(conn):
    _programme_profile(conn, anchor="2024-01-01")
    settings_profile.save(
        conn,
        set_values={"deload.scheduled.every_weeks": 2},
        effective_from="2024-01-01",
    )
    nudge = nudges.current(conn, on_date="2024-01-08")
    assert nudge is not None
    assert nudge["family"] == "programme"
    assert nudge["key"] == "nudge:programme:deload"
    assert "deload" in nudge["statement"]
    assert nudge["evidence"]["limitations"]


def test_competition_peak_is_promoted_as_a_programme_nudge(conn):
    _programme_profile(conn, competition="2024-02-01")
    nudge = nudges.current(conn, on_date="2024-01-15")
    assert nudge is not None
    assert nudge["key"] == "nudge:programme:competition"
    assert "peak" in nudge["statement"]


def test_deload_nudge_precedes_the_competition_nudge(conn):
    _programme_profile(conn, anchor="2024-01-01", competition="2024-01-20")
    settings_profile.save(
        conn,
        set_values={"deload.scheduled.every_weeks": 2},
        effective_from="2024-01-01",
    )
    nudge = nudges.current(conn, on_date="2024-01-08")
    assert nudge is not None
    assert nudge["key"] == "nudge:programme:deload"


def test_programme_nudge_dismissal_covers_its_state(conn):
    _programme_profile(conn, anchor="2024-01-01")
    settings_profile.save(
        conn,
        set_values={"deload.scheduled.every_weeks": 2},
        effective_from="2024-01-01",
    )
    nudge = nudges.current(conn, on_date="2024-01-08")
    assert nudges.record(
        conn,
        key=nudge["key"],
        action="dismiss",
        on_date="2024-01-08",
        evidence_id=nudge["evidence_id"],
    ) is None
    assert nudges.current(conn, on_date="2024-01-08") is None


def test_programme_nudge_snooze_hides_for_fourteen_days(conn):
    _programme_profile(conn, competition="2024-02-01")
    nudge = nudges.current(conn, on_date="2024-01-15")
    nudges.record(conn, key=nudge["key"], action="snooze", on_date="2024-01-15")
    assert nudges.current(conn, on_date="2024-01-20") is None
    assert nudges.current(conn, on_date="2024-01-30") is not None

