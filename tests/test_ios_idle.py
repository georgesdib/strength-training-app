"""Phase 6.1: idle warning and lazy abandonment."""

# The shared HTTP fixture and helpers are intentionally imported from test_ios_workflow.
# ruff: noqa: F401, F811

from __future__ import annotations

import datetime
import json

from test_ios_workflow import _issue, _paired, _request, _start, ios

from strength_coach.store import db


def _set_activity(path, workout_id, when):
    store = db.Store(path)
    try:
        store.connection.execute(
            "UPDATE workout_session SET last_activity_at = ? WHERE workout_id = ?",
            (when.isoformat(), workout_id),
        )
        store.connection.commit()
    finally:
        store.close()


def _activity(path, workout_id):
    store = db.Store(path)
    try:
        return store.connection.execute(
            "SELECT status, last_activity_at FROM workout_session WHERE workout_id = ?",
            (workout_id,),
        ).fetchone()
    finally:
        store.close()


def test_stale_warning_then_lazy_abandonment(ios):
    token, _ = _paired(ios)
    status, issue = _issue(ios, token)
    assert status == 200, issue
    status, started = _start(ios, token, issue["issued_plan_id"])
    assert status == 200, started
    workout_id = started["workout_id"]
    now = datetime.datetime.now(datetime.UTC)

    _set_activity(ios["path"], workout_id, now - datetime.timedelta(hours=4))
    status, execution = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout_id}/execution", token=token,
    )
    assert status == 200
    assert execution["stale"] is True
    assert execution["status"] == "in_progress"

    _set_activity(ios["path"], workout_id, now - datetime.timedelta(days=2))
    status, today = _request(ios["base"], "/api/ios/v1/today", token=token)
    assert status == 200
    assert today["active_workout"] is None

    row = _activity(ios["path"], workout_id)
    assert row["status"] == "abandoned"

    store = db.Store(ios["path"])
    try:
        event = store.connection.execute(
            "SELECT payload_json FROM workout_event WHERE workout_id = ? "
            "AND event_type = 'abandon' ORDER BY event_id DESC LIMIT 1",
            (workout_id,),
        ).fetchone()
        assert event is not None
        assert json.loads(event["payload_json"])["reason"] == "idle"
    finally:
        store.close()
