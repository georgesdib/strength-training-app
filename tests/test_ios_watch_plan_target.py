"""S5: an issued plan belongs to the pairing, not a target device."""

# The shared HTTP fixture and helpers are intentionally imported from test_ios_workflow.
# ruff: noqa: F401, F811

from __future__ import annotations

import uuid

from test_ios_workflow import (
    _add_set,
    _first_item,
    _issue,
    _paired,
    _plan_state,
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


def test_the_pairing_sees_one_plan_and_the_watch_starts_it(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, watch_id = _mint_watch(ios, phone)

    status, plan = _issue(ios, phone)
    assert status == 200, plan
    assert "execution_target" not in plan

    status, seen = _request(ios["base"], "/api/ios/v1/plans/current", token=watch)
    assert status == 200, seen
    assert seen["issued_plan_id"] == plan["issued_plan_id"]
    assert "execution_target" not in seen

    # Either device of the pairing starts; the watch's execution writes are read-only, not
    # its start (S5).
    status, started = _start(ios, watch, plan["issued_plan_id"])
    assert status == 200, started
    assert started["status"] == "in_progress"
    assert started["owner_device_id"] == watch_id


def test_a_completed_start_replay_acknowledges_the_execution_id(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, watch_id = _mint_watch(ios, phone)
    status, plan = _issue(ios, phone)
    assert status == 200, plan
    status, started = _start(ios, phone, plan["issued_plan_id"])
    assert status == 200, started
    status, completed = _request(
        ios["base"], f"/api/ios/v1/workouts/{started['workout_id']}/complete",
        method="POST", payload={
            "not_recorded": True, "pending_devices": [watch_id],
        }, token=phone, key=uuid.uuid4().hex,
    )
    assert status == 200, completed

    # The watch's offline start replays after the phone finished. It must acknowledge the same
    # execution instead of 410 plan_consumed, so its queued sets can use late reconciliation.
    status, replay = _start(
        ios, watch, plan["issued_plan_id"],
        body={
            "issued_plan_id": plan["issued_plan_id"],
            "execution_id": plan["execution_id"],
        },
    )
    assert status == 200, replay
    assert replay["workout_id"] == started["workout_id"]
    assert replay["status"] == "completed"

    # The queued set can now use the open late-reconciliation window.
    status, body = _add_set(
        ios, phone, started["workout_id"], _first_item(started["plan"]),
        origin_device_id=watch_id,
        performed_at=started["started_at"],
    )
    assert status == 200, body
    assert body["sets"][-1]["origin_device_id"] == watch_id


def test_the_phone_starts_a_pairing_plan(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    _mint_watch(ios, phone)
    status, plan = _issue(ios, phone)
    assert status == 200, plan
    status, started = _start(ios, phone, plan["issued_plan_id"])
    assert status == 200, started


def test_replacing_the_watch_keeps_the_pairing_plan(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    _mint_watch(ios, phone)
    status, request = _issue(ios, phone, wait=False)
    assert status == 202, request

    second, _ = _mint_watch(ios, phone)

    assert _plan_state(ios, phone)["issued_plan_id"] == request["issued_plan_id"]
    assert _plan_state(ios, second)["issued_plan_id"] == request["issued_plan_id"]


def test_revoking_the_watch_keeps_the_phone_copy_of_the_plan(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, watch_id = _mint_watch(ios, phone)
    status, request = _issue(ios, phone, wait=False)
    assert status == 202, request
    assert _plan_state(ios, watch)["issued_plan_id"] == request["issued_plan_id"]

    status, _ = _request(
        ios["base"], f"/api/ios/v1/devices/{watch_id}", method="DELETE", token=phone,
    )
    assert status == 200

    seen = _plan_state(ios, phone)
    assert seen["status"] != "none"
    assert seen["issued_plan_id"] == request["issued_plan_id"]
    status, _ = _request(ios["base"], "/api/ios/v1/plans/current", token=watch)
    assert status == 403


def test_the_old_execution_target_field_is_gone(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    status, body = _issue(ios, phone, body={"execution_target": "watch"}, wait=False)
    assert status == 400, body
    assert "execution_target" in body["fields"]


def test_a_watch_request_replaces_the_pairing_plan(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, _ = _mint_watch(ios, phone)
    status, first = _issue(ios, phone, wait=False)
    assert status == 202, first
    status, second = _issue(ios, watch, wait=False)
    assert status == 202, second

    seen = _plan_state(ios, phone)
    assert seen["issued_plan_id"] == second["issued_plan_id"]
    assert _plan_state(ios, watch)["issued_plan_id"] == second["issued_plan_id"]
