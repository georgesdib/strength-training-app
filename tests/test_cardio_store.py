"""The cardio store is the only writer of the corpus tables; these tests pin its rules."""

from __future__ import annotations

import sqlite3

import pytest

from strength_coach.store import cardio, db

IMPORTED = "2026-11-17T18:00:00+00:00"
START = "2026-11-10T08:00:00+00:00"
END = "2026-11-10T08:40:00+00:00"


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "coach.db")
    db.migrate(connection)
    connection.execute(
        "INSERT INTO session (session_id, occurred_on, set_count, exercise_count) "
        "VALUES ('s-1', '2026-11-10', 20, 4)"
    )
    connection.commit()
    yield connection
    connection.close()


def _workout(conn, **overrides):
    kwargs = dict(
        external_key="k-0123456789abcdef",
        origin="export",
        activity_type="HKWorkoutActivityTypeRunning",
        started_at=START,
        ended_at=END,
        duration_s=2400,
        source_name="Apple Watch",
        imported_at=IMPORTED,
    )
    kwargs.update(overrides)
    return cardio.record_workout(conn, **kwargs)


def test_content_key_is_deterministic_and_sensitive():
    base = dict(
        activity_type="HKWorkoutActivityTypeCycling",
        started_at=START,
        ended_at=END,
        duration_s=1800,
    )
    assert cardio.content_key(**base) == cardio.content_key(**base)
    assert len(cardio.content_key(**base)) == 64
    assert cardio.content_key(**{**base, "duration_s": 1801}) != cardio.content_key(**base)


def test_workout_is_idempotent_and_conflicts_instead_of_overwriting(conn):
    row, created = _workout(conn)
    assert created is True
    assert row["origin"] == "export"
    again, created_again = _workout(conn)
    assert created_again is False
    assert again["external_workout_id"] == row["external_workout_id"]
    with pytest.raises(cardio.CardioConflict):
        _workout(conn, duration_s=2401)
    with pytest.raises(cardio.CardioConflict):
        _workout(conn, activity_type="HKWorkoutActivityTypeWalking")


def test_workout_rejects_naive_times_and_impossible_ranges(conn):
    with pytest.raises(cardio.CardioIngestError):
        _workout(conn, started_at="2026-11-10T08:00:00")  # no offset
    with pytest.raises(cardio.CardioIngestError):
        _workout(conn, ended_at=START)
    with pytest.raises(cardio.CardioIngestError):
        _workout(conn, duration_s=0)
    with pytest.raises(cardio.CardioIngestError):
        _workout(conn, origin="manual")
    with pytest.raises(cardio.CardioIngestError):
        _workout(conn, avg_heart_rate=160, max_heart_rate=140)


def test_timestamps_normalise_to_utc(conn):
    row, _ = _workout(
        conn,
        started_at="2026-11-10 08:00:00 +0000",   # Apple export format
        ended_at="2026-11-10T12:00:00+02:00",     # a non-UTC offset
    )
    assert row["started_at"] == "2026-11-10T08:00:00+00:00"
    assert row["ended_at"] == "2026-11-10T10:00:00+00:00"
    # The same instants written in UTC are the same workout, not a conflict.
    again, created = _workout(
        conn,
        started_at="2026-11-10T08:00:00+00:00",
        ended_at="2026-11-10T10:00:00+00:00",
    )
    assert created is False
    assert again["external_workout_id"] == row["external_workout_id"]


def test_sample_association_and_heart_rate_are_validated(conn):
    workout, _ = _workout(conn)
    sid = workout["external_workout_id"]
    with pytest.raises(cardio.CardioIngestError):
        cardio.record_sample(
            conn, sample_key="x-1", kind="heart_rate", sampled_at=START, value=150.0,
            unit="count/min", source_name="Watch", imported_at=IMPORTED, association="workout",
        )
    with pytest.raises(cardio.CardioIngestError):
        cardio.record_sample(
            conn, sample_key="x-2", kind="heart_rate", sampled_at=START, value=400.0,
            unit="count/min", source_name="Watch", imported_at=IMPORTED,
            external_workout_id=sid, association="workout",
        )
    sample, created = cardio.record_sample(
        conn, sample_key="x-3", kind="heart_rate", sampled_at=START, value=150.0,
        unit="count/min", source_name="Watch", imported_at=IMPORTED,
        external_workout_id=sid, association="workout",
    )
    assert created is True
    assert sample["association"] == "workout"
    _, again = cardio.record_sample(
        conn, sample_key="x-3", kind="heart_rate", sampled_at=START, value=150.0,
        unit="count/min", source_name="Watch", imported_at=IMPORTED,
        external_workout_id=sid, association="workout",
    )
    assert again is False
    with pytest.raises(cardio.CardioConflict):
        cardio.record_sample(
            conn, sample_key="x-3", kind="heart_rate", sampled_at=START, value=151.0,
            unit="count/min", source_name="Watch", imported_at=IMPORTED,
            external_workout_id=sid, association="workout",
        )
    with pytest.raises(sqlite3.IntegrityError):
        cardio.record_sample(
            conn, sample_key="x-4", kind="heart_rate", sampled_at=START, value=140.0,
            unit="count/min", source_name="Watch", imported_at=IMPORTED,
            external_workout_id="missing", association="workout",
        )


def test_link_is_one_active_link_and_unlink_is_an_event(conn):
    workout, _ = _workout(conn)
    sid = workout["external_workout_id"]
    assert cardio.active_link(conn, sid) is None
    link = cardio.link_workout(
        conn, external_workout_id=sid, session_id="s-1", method="day_containment",
        band_version="link_v1", confidence=0.5,
    )
    assert cardio.active_link(conn, sid)["link_id"] == link["link_id"]
    with pytest.raises(cardio.CardioIngestError):
        cardio.link_workout(
            conn, external_workout_id=sid, session_id="s-1", method="explicit",
            band_version="link_v1",
        )
    unlink = cardio.unlink_workout(conn, external_workout_id=sid)
    assert unlink["supersedes_id"] == link["link_id"]
    assert cardio.active_link(conn, sid) is None
    with pytest.raises(cardio.CardioIngestError):
        cardio.unlink_workout(conn, external_workout_id=sid)
    with pytest.raises(cardio.CardioIngestError):
        cardio.link_workout(
            conn, external_workout_id="missing", session_id="s-1", method="explicit",
            band_version="link_v1",
        )
    # history keeps both events
    assert conn.execute("SELECT COUNT(*) FROM workout_link").fetchone()[0] == 2


def test_link_to_missing_session_is_rejected(conn):
    workout, _ = _workout(conn)
    with pytest.raises(cardio.CardioIngestError):
        cardio.link_workout(
            conn, external_workout_id=workout["external_workout_id"], session_id="missing",
            method="explicit", band_version="link_v1",
        )


def test_status_events_are_append_only_history(conn):
    workout, _ = _workout(conn)
    sid = workout["external_workout_id"]
    assert cardio.current_status(conn, sid) is None
    cardio.record_status(conn, external_workout_id=sid, status="absent_from_source")
    cardio.record_status(conn, external_workout_id=sid, status="reappeared")
    assert cardio.current_status(conn, sid) == "reappeared"
    with pytest.raises(cardio.CardioIngestError):
        cardio.record_status(conn, external_workout_id=sid, status="deleted")
    with pytest.raises(cardio.CardioIngestError):
        cardio.record_status(conn, external_workout_id="missing", status="reappeared")


def test_sync_state_roundtrip_and_upsert(conn):
    assert cardio.get_sync_state(conn, "history_cutoff") is None
    cardio.set_sync_state(conn, "history_cutoff", START, updated_at=IMPORTED)
    cardio.set_sync_state(conn, "history_cutoff", END, updated_at=IMPORTED)
    assert cardio.get_sync_state(conn, "history_cutoff") == END
    with pytest.raises(cardio.CardioIngestError):
        cardio.set_sync_state(conn, "history_cutoff", END, updated_at="2026-11-17T18:00:00")
