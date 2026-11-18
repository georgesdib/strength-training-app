"""Longevity capability: envelope shape, abstention, and the facts-only rule."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from intelligence_support import service

from strength_coach.intelligence import INTERNAL_PRINCIPAL
from strength_coach.store import cardio, db

TODAY = dt.date(2026, 11, 14)  # shared test clock; completed week is 2026-11-02..08
RUN = "HKWorkoutActivityTypeRunning"


@pytest.fixture()
def store(tmp_path):
    s = db.Store(tmp_path / "coach.db")
    yield s
    s.close()


def _workout(conn, start, minutes, *, mets=None):
    end = (dt.datetime.fromisoformat(start) + dt.timedelta(minutes=minutes)).isoformat()
    cardio.record_workout(
        conn,
        external_key=cardio.content_key(
            activity_type=RUN, started_at=start, ended_at=end, duration_s=minutes * 60
        ),
        origin="export",
        activity_type=RUN,
        started_at=start,
        ended_at=end,
        duration_s=minutes * 60,
        source_name="Watch",
        avg_mets=mets,
        avg_heart_rate=None,
        imported_at="2026-11-17T18:00:00+00:00",
    )


def _vo2max(conn, *, measured_at="2026-11-10T08:00:00+00:00", value=48.0):
    cardio.record_vo2max(
        conn,
        external_id=f"vo2-{measured_at}",
        measured_at=measured_at,
        value=value,
        method="Apple Watch",
        noted_at=measured_at,
    )


def _call(conn, **arguments):
    payload = {"as_of": TODAY.isoformat()} | arguments
    return service(conn).execute(INTERNAL_PRINCIPAL, "get_longevity_assessment", payload)


def test_envelope_carries_the_week_and_never_advice(store):
    conn = store.connection
    for day in ("03", "04", "05"):
        _workout(conn, f"2026-11-{day}T08:00:00+00:00", 60, mets=4.0)
    _vo2max(conn)

    result = _call(conn)
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "ok"
    assert env.capability == "get_longevity_assessment"
    assert env.privacy.classification == "health"
    assert env.period.start == "2026-11-02"
    assert env.period.end == "2026-11-08"

    last = env.facts["last_week"].value
    assert last["equivalent_minutes"] == 180.0
    assert last["relation"] == "inside"
    assert last["reference"]["role"] == "context, not a target"
    assert env.facts["last_week"].gate == "signal"
    assert env.facts["current_week"].value["equivalent_minutes"] == 0
    assert env.facts["vo2max"].value["status"] == "current"

    # Facts only: no recommendation, no prose, no target.
    assert "advice" not in env.facts
    assert "recommendation" not in env.facts
    payload = json.dumps(env.as_dict(), default=str).lower()
    assert "should" not in payload


def test_thin_classification_abstains(store):
    conn = store.connection
    _workout(conn, "2026-11-03T08:00:00+00:00", 20, mets=4.0)
    _workout(conn, "2026-11-04T08:00:00+00:00", 200)

    result = _call(conn)
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "insufficient"
    assert env.facts["last_week"].gate == "insufficient"
    assert env.facts["last_week"].value["relation"] == "unknown"
    assert env.facts["last_week"].value["remaining_minutes"] is None


def test_empty_week_is_no_data_not_zero(store):
    result = _call(store.connection)
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "no_data"
    assert env.facts["last_week"].value["equivalent_minutes"] == 0.0
    assert "no VO2max measurement has been recorded" in env.missing


def test_stale_vo2max_is_reported_with_its_date(store):
    conn = store.connection
    _vo2max(conn, measured_at="2026-06-01T08:00:00+00:00", value=48.0)
    env = _call(conn).envelope
    fact = env.facts["vo2max"]
    assert fact.value["status"] == "stale"
    assert fact.value["value"] == 48.0
    assert fact.value["unit"] == "ml/kg/min"
    assert fact.value["measured_on"] == "2026-06-01"


def test_optional_blocks_follow_the_request(store):
    conn = store.connection
    _workout(conn, "2026-11-03T08:00:00+00:00", 60, mets=4.0)
    default = _call(conn).envelope
    assert "time_in_zone" not in default.facts
    assert "patterns" in default.facts

    with_tiz = _call(conn, include_time_in_zone=True).envelope
    assert "time_in_zone" in with_tiz.facts
    assert with_tiz.facts["time_in_zone"].gate == "insufficient"  # no samples seeded

    without_patterns = _call(conn, include_patterns=False).envelope
    assert "patterns" not in without_patterns.facts


def test_future_date_and_unknown_arguments_are_rejected(store):
    conn = store.connection
    future = _call(conn, as_of="2026-12-01")
    assert not future.ok
    assert future.error.code == "invalid_argument"

    unknown = _call(conn, window_weeks=4)
    assert not unknown.ok
    assert unknown.error.code == "invalid_argument"
