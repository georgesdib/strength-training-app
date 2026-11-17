"""Linking rules: two tiers, no silent relinking, and a queue for what cannot be decided."""

from __future__ import annotations

import pytest

from strength_coach.store import cardio, db
from tools import cardio_link

STRENGTH = "HKWorkoutActivityTypeTraditionalStrengthTraining"


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "coach.db")
    db.migrate(connection)
    yield connection
    connection.close()


def _session(conn, session_id, occurred_on, workout_id=None):
    conn.execute(
        "INSERT INTO session (session_id, occurred_on, set_count, exercise_count, workout_id) "
        "VALUES (?, ?, 20, 4, ?)",
        (session_id, occurred_on, workout_id),
    )


def _executed(conn, workout_id, start, end):
    conn.execute(
        """
        INSERT INTO workout_session (
            workout_id, for_date, session_type, status, plan_json, readiness_json,
            started_at, ended_at, duration_measured_s
        ) VALUES (?, '2026-11-10', 'A', 'completed', '{}', '{}', ?, ?, 2400)
        """,
        (workout_id, start, end),
    )


def _workout(conn, key, start, end, activity=STRENGTH, duration=2400):
    row, _ = cardio.record_workout(
        conn,
        external_key=cardio.content_key(
            activity_type=activity, started_at=start, ended_at=end, duration_s=duration
        ),
        origin="export",
        activity_type=activity,
        started_at=start,
        ended_at=end,
        duration_s=duration,
        source_name="Watch",
        imported_at="2026-11-17T18:00:00+00:00",
    )
    return row


def test_interval_tier_links_a_measured_session(conn):
    _session(conn, "s-1", "2026-11-10", workout_id="w-1")
    _executed(conn, "w-1", "2026-11-10T08:00:00+00:00", "2026-11-10T08:40:00+00:00")
    workout = _workout(conn, "k1", "2026-11-10T08:01:00+00:00", "2026-11-10T08:39:00+00:00")
    candidates, deferred = cardio_link.evaluate(conn)
    assert [c.method for c in candidates] == ["interval_overlap"]
    assert candidates[0].session_id == "s-1"
    assert candidates[0].overlap and candidates[0].overlap > 0.9
    assert deferred == []
    assert cardio_link.write_links(conn, candidates) == 1
    link = cardio.active_link(conn, workout["external_workout_id"])
    assert link["method"] == "interval_overlap"
    assert link["band_version"] == "link_v1"


def test_partial_overlap_queues_instead_of_linking(conn):
    _session(conn, "s-1", "2026-11-10", workout_id="w-1")
    _executed(conn, "w-1", "2026-11-10T08:00:00+00:00", "2026-11-10T08:40:00+00:00")
    _workout(conn, "k1", "2026-11-10T08:25:00+00:00", "2026-11-10T09:05:00+00:00")
    candidates, deferred = cardio_link.evaluate(conn)
    # The interval is authoritative: day containment must not claim this workout as well.
    assert candidates == []
    assert deferred and "below 0.6" in deferred[0].reason


def test_day_tier_links_only_when_the_day_is_unique(conn):
    _session(conn, "s-1", "2026-11-11")
    _workout(conn, "k1", "2026-11-11T18:00:00+00:00", "2026-11-11T18:55:00+00:00", duration=3300)
    candidates, deferred = cardio_link.evaluate(conn)
    assert [c.method for c in candidates] == ["day_containment"]
    assert deferred == []


def test_two_workouts_on_one_day_queue(conn):
    _session(conn, "s-1", "2026-11-12")
    _workout(conn, "k1", "2026-11-12T09:00:00+00:00", "2026-11-12T09:55:00+00:00", duration=3300)
    _workout(conn, "k2", "2026-11-12T18:00:00+00:00", "2026-11-12T18:55:00+00:00", duration=3300)
    candidates, deferred = cardio_link.evaluate(conn)
    assert candidates == []
    assert len(deferred) == 2
    assert all("strength workouts on 2026-11-12" in d.reason for d in deferred)


def test_non_strength_workouts_are_not_candidates(conn):
    _session(conn, "s-1", "2026-11-10")
    _workout(
        conn, "k1", "2026-11-10T08:00:00+00:00", "2026-11-10T08:40:00+00:00",
        activity="HKWorkoutActivityTypeRunning",
    )
    candidates, deferred = cardio_link.evaluate(conn)
    assert candidates == [] and deferred == []


def test_apply_is_idempotent_and_never_relinks(conn):
    _session(conn, "s-1", "2026-11-11")
    _workout(conn, "k1", "2026-11-11T18:00:00+00:00", "2026-11-11T18:55:00+00:00", duration=3300)
    candidates, _ = cardio_link.evaluate(conn)
    assert cardio_link.write_links(conn, candidates) == 1
    again, deferred = cardio_link.evaluate(conn)
    assert again == [] and deferred == []
    assert conn.execute("SELECT COUNT(*) FROM workout_link").fetchone()[0] == 1


def test_manual_link_and_unlink_round_trip(conn, tmp_path, capsys):
    workout = _workout(
        conn, "k1", "2026-11-11T18:00:00+00:00", "2026-11-11T18:55:00+00:00", duration=3300
    )
    _session(conn, "s-1", "2026-11-11")
    key = cardio.key_text(workout["external_key"])
    db_path = str(tmp_path / "coach.db")
    assert cardio_link.main(["--db", db_path, "--link", f"{key}=s-1"]) == 0
    link = cardio.active_link(conn, workout["external_workout_id"])
    assert link["method"] == "manual"
    assert cardio_link.main(["--db", db_path, "--unlink", key]) == 0
    conn.commit()
    assert cardio.active_link(conn, workout["external_workout_id"]) is None
