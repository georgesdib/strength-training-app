"""Phase 6.1: ownership, takeover, revision and plan-item mismatch."""

# The shared HTTP fixture and helpers are intentionally imported from test_ios_workflow.
# ruff: noqa: F401, F811

from __future__ import annotations

import uuid

from test_ios_workflow import (
    _add_set,
    _first_item,
    _issue,
    _paired,
    _plan_edit,
    _request,
    _start,
    ios,
)

from strength_coach import ios_config


def _enabled(monkeypatch):
    monkeypatch.setattr(
        "strength_coach.web.server.ios_config.load_config",
        lambda: ios_config.IOSConfig(
            mutations_enabled=True,
            issued_plan_ttl_seconds=14400,
            receipt_retention_days=30,
            watch_enabled=True,
        ),
    )


def _mint_watch(ios, phone_token):
    status, body = _request(
        ios["base"], "/api/ios/v1/devices/watch", method="POST",
        payload={"label": "Watch"}, token=phone_token,
    )
    assert status == 201, body
    return body["token"], body["device"]["device_id"]


def _watch_workout(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, _ = _mint_watch(ios, phone)
    status, plan = _issue(ios, phone, body={"execution_target": "watch"})
    assert status == 200, plan
    status, started = _start(ios, watch, plan["issued_plan_id"])
    assert status == 200, started
    return phone, watch, started


def test_start_records_owner_and_revision(ios, monkeypatch):
    phone, watch, started = _watch_workout(ios, monkeypatch)
    assert started["owner_device_id"] != phone
    assert started["plan_revision"] == 0
    assert started["last_activity_at"] == started["started_at"]

    status, execution = _request(
        ios["base"], f"/api/ios/v1/workouts/{started['workout_id']}/execution",
        token=phone,
    )
    assert status == 200
    assert execution["owner_device_id"] == started["owner_device_id"]
    assert execution["plan_revision"] == 0
    assert execution["stale"] is False


def test_non_owner_cannot_write_sets_or_complete(ios, monkeypatch):
    phone, watch, started = _watch_workout(ios, monkeypatch)
    item = _first_item(started["plan"])
    status, body = _add_set(ios, phone, started["workout_id"], item)
    assert status == 409, body
    assert body["code"] == "not_owner"
    status, body = _request(
        ios["base"], f"/api/ios/v1/workouts/{started['workout_id']}/complete",
        method="POST", payload={"session_rpe": 7}, token=phone,
        key=uuid.uuid4().hex,
    )
    assert status == 409, body
    assert body["code"] == "not_owner"


def test_watch_cannot_edit_the_plan_but_phone_can(ios, monkeypatch):
    phone, watch, started = _watch_workout(ios, monkeypatch)
    item = _first_item(started["plan"])
    status, body = _plan_edit(
        ios, watch, started["workout_id"], "/items/0/sets",
        {"delta": 1, "expected_exercise_id": item["exercise_id"]},
    )
    assert status == 403, body
    assert body["code"] == "not_phone"

    status, updated = _plan_edit(
        ios, phone, started["workout_id"], "/items/0/sets",
        {"delta": 1, "expected_exercise_id": item["exercise_id"]},
    )
    assert status == 200, updated
    assert updated["plan_revision"] == 1


def test_takeover_transfers_writes_to_the_phone(ios, monkeypatch):
    phone, watch, started = _watch_workout(ios, monkeypatch)
    item = _first_item(started["plan"])
    status, body = _request(
        ios["base"], f"/api/ios/v1/workouts/{started['workout_id']}/takeover",
        method="POST", payload={"confirm": True}, token=watch,
        key=uuid.uuid4().hex,
    )
    assert status == 403, body

    status, body = _request(
        ios["base"], f"/api/ios/v1/workouts/{started['workout_id']}/takeover",
        method="POST", payload={"confirm": True}, token=phone,
        key=uuid.uuid4().hex,
    )
    assert status == 200, body
    assert body["owner_device_id"] != started["owner_device_id"]

    status, body = _add_set(ios, watch, started["workout_id"], item)
    assert status == 409, body
    status, body = _add_set(ios, phone, started["workout_id"], item)
    assert status == 200, body


def test_changed_plan_item_returns_mismatch_then_off_plan(ios, monkeypatch):
    phone, watch, started = _watch_workout(ios, monkeypatch)
    items = started["plan"]["items"]
    assert len(items) >= 2
    first = items[0]
    other = next(
        item["exercise_id"] for item in items[1:]
        if item["exercise_id"] != first["exercise_id"]
    )
    status, body = _add_set(
        ios, watch, started["workout_id"], first,
        plan_item_index=0, exercise_id=other,
    )
    assert status == 409, body
    assert body["code"] == "plan_item_mismatch"

    status, body = _add_set(
        ios, watch, started["workout_id"], first,
        plan_item_index=None, exercise_id=other,
    )
    assert status == 200, body
