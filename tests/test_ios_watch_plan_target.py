"""Phase 6.1: a plan requested for the watch is routed to it and only it can start it."""

# The shared HTTP fixture and helpers are intentionally imported from test_ios_workflow.
# ruff: noqa: F401, F811

from __future__ import annotations

from test_ios_workflow import _issue, _paired, _plan_state, _request, _start, ios

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


def test_phone_can_issue_a_watch_plan_and_only_the_watch_starts_it(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, _ = _mint_watch(ios, phone)

    status, plan = _issue(ios, phone, body={"execution_target": "watch"})
    assert status == 200, plan
    assert plan["execution_target"] == "watch"
    assert plan["status"] == "ready"

    status, seen = _request(ios["base"], "/api/ios/v1/plans/current", token=watch)
    assert status == 200
    assert seen["issued_plan_id"] == plan["issued_plan_id"]
    assert seen["execution_target"] == "watch"

    status, rejected = _start(ios, phone, plan["issued_plan_id"])
    assert status == 409, rejected

    status, started = _start(ios, watch, plan["issued_plan_id"])
    assert status == 200, started
    assert started["status"] == "in_progress"


def test_watch_cannot_start_a_phone_plan(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, _ = _mint_watch(ios, phone)
    status, plan = _issue(ios, phone)
    assert status == 200
    status, rejected = _start(ios, watch, plan["issued_plan_id"])
    assert status == 409, rejected
    status, started = _start(ios, phone, plan["issued_plan_id"])
    assert status == 200, started


def test_replacing_the_watch_retires_the_plan_it_was_issued_to(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    first, _ = _mint_watch(ios, phone)
    status, plan = _issue(ios, phone, body={"execution_target": "watch"})
    assert status == 200, plan
    assert _plan_state(ios, first)["status"] == "ready"

    # A replacement watch is a new device id; the plan was bound to the old one and can never
    # be started. Both callers must stop advertising it, or the phone shows a watch workout
    # the watch itself reports as missing.
    second, _ = _mint_watch(ios, phone)

    assert _plan_state(ios, phone)["status"] == "none"
    assert _plan_state(ios, second)["status"] == "none"
    status, rejected = _start(ios, second, plan["issued_plan_id"])
    assert status == 409, rejected
    assert rejected["code"] == "wrong_execution_target"


def test_revoking_the_watch_retires_its_live_plan(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    watch, watch_id = _mint_watch(ios, phone)
    status, plan = _issue(ios, phone, body={"execution_target": "watch"})
    assert status == 200, plan

    status, _ = _request(
        ios["base"], f"/api/ios/v1/devices/{watch_id}", method="DELETE", token=phone,
    )
    assert status == 200

    assert _plan_state(ios, phone)["status"] == "none"
    status, _ = _request(ios["base"], "/api/ios/v1/plans/current", token=watch)
    assert status == 403


def test_replacing_the_watch_keeps_a_phone_plan_intact(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    _mint_watch(ios, phone)
    status, plan = _issue(ios, phone)
    assert status == 200, plan

    _mint_watch(ios, phone)

    seen = _plan_state(ios, phone)
    assert seen["status"] == "ready"
    assert seen["issued_plan_id"] == plan["issued_plan_id"]
    assert seen["execution_target"] == "phone"


def test_watch_target_without_a_paired_watch_is_rejected(ios, monkeypatch):
    _enabled(monkeypatch)
    phone, _ = _paired(ios)
    status, body = _issue(ios, phone, body={"execution_target": "watch"}, wait=False)
    assert status == 409, body
    assert body["code"] == "watch_not_paired"
