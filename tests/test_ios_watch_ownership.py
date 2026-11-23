"""S5: the pairing shares a plan; only the phone writes execution (D3, D12)."""

# The shared HTTP fixture and helpers are intentionally imported from test_ios_workflow.
# ruff: noqa: F401, F811

from __future__ import annotations

import uuid

from test_ios_workflow import (
    _add_set,
    _first_item,
    _issue,
    _paired,
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


def _pairing_workout(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, phone_device = _paired(ios)
    watch, _ = _mint_watch(ios, phone)
    status, plan = _issue(ios, phone)
    assert status == 200, plan
    status, started = _start(ios, phone, plan["issued_plan_id"])
    assert status == 200, started
    return phone, phone_device, watch, started


def test_start_records_owner_as_provenance(ios, monkeypatch):
    phone, phone_device, watch, started = _pairing_workout(ios, monkeypatch)
    assert started["owner_device_id"] == phone_device["device_id"]
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


def test_only_the_phone_writes_execution(ios, monkeypatch):
    phone, _device, watch, started = _pairing_workout(ios, monkeypatch)
    item = _first_item(started["plan"])

    status, body = _add_set(ios, phone, started["workout_id"], item)
    assert status == 200, body
    # The watch token is read-only: execution commits through the phone (D3, D12).
    status, refused = _add_set(ios, watch, started["workout_id"], item, set_index=2)
    assert status == 403, refused
    assert refused["code"] == "watch_read_only"


def test_the_watch_reads_but_cannot_write(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, _ = _mint_watch(ios, phone)
    status, plan = _issue(ios, phone)
    assert status == 200, plan
    status, seen = _request(ios["base"], "/api/ios/v1/plans/current", token=watch)
    assert status == 200, seen
    assert seen["issued_plan_id"] == plan["issued_plan_id"]
    status, started = _start(ios, phone, plan["issued_plan_id"])
    assert status == 200, started
    item = _first_item(started["plan"])
    status, refused = _add_set(ios, watch, started["workout_id"], item)
    assert status == 403, refused
    assert refused["code"] == "watch_read_only"


def test_takeover_route_is_gone(ios, monkeypatch):
    phone, phone_device, watch, started = _pairing_workout(ios, monkeypatch)
    status, body = _request(
        ios["base"], f"/api/ios/v1/workouts/{started['workout_id']}/takeover",
        method="POST", payload={"confirm": True}, token=phone,
        key=uuid.uuid4().hex,
    )
    assert status == 404, body


def test_a_stale_plan_item_index_is_kept_as_extra_work(ios, monkeypatch):
    phone, phone_device, watch, started = _pairing_workout(ios, monkeypatch)
    items = started["plan"]["items"]
    assert len(items) >= 2
    first = items[0]
    other = next(
        item["exercise_id"] for item in items[1:]
        if item["exercise_id"] != first["exercise_id"]
    )
    # The plan is frozen, so this is a stale index: the set is preserved as extra work and
    # never attributed to another exercise's slot. The 409 plan_item_mismatch is retired.
    status, body = _add_set(
        ios, phone, started["workout_id"], first,
        plan_item_index=0, exercise_id=other,
    )
    assert status == 200, body
    logged = body["sets"][-1]
    assert logged["exercise_id"] == other
    assert logged["prescription_item_index"] is None

    # An annotated substitution keeps the slot on both columns.
    status, body = _add_set(
        ios, phone, started["workout_id"], first,
        exercise_id=other, substitutes_plan_item_index=0, set_index=2,
    )
    assert status == 200, body
    annotated = body["sets"][-1]
    assert annotated["prescription_item_index"] == 0
    assert annotated["substitutes_plan_item_index"] == 0


def test_watch_cannot_author_an_execution_change(ios, monkeypatch):
    _phone, phone_device, watch, started = _pairing_workout(ios, monkeypatch)
    payload = {
        "event_id": str(uuid.uuid4()),
        "change": "substitution",
        "plan_item_index": 0,
        "exercise_id": _first_item(started["plan"])["exercise_id"],
    }
    status, body = _request(
        ios["base"], f"/api/ios/v1/workouts/{started['workout_id']}/execution",
        method="POST", payload=payload, token=watch, key=uuid.uuid4().hex,
    )
    assert status == 403, body
    assert body["code"] == "watch_read_only"
