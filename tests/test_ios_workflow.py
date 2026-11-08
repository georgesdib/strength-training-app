"""Phase 2 iOS online strength workflow contract tests.

The live threaded server and a temporary SQLite database are used throughout. No test touches the
owner's live data/coach.db.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import datetime
import json
import threading
import urllib.error
import urllib.request
import uuid

import pytest
from conftest import make_readiness, make_training

from strength_coach import ios_config
from strength_coach.features.deload import DeloadDecision
from strength_coach.store import db, importer, ios_devices
from strength_coach.web import server as web_server
from strength_coach.web.server import create_server


@pytest.fixture
def ios(tmp_path):
    path = tmp_path / "coach.db"
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    rows = [
        {"Date": today, "Exercise": "Competition Squat", "Weight_Used": "140",
         "RIR": "2", "Reps_Done": "3"},
        {"Date": today, "Exercise": "Competition Bench Press", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": yesterday, "Exercise": "Competition Deadlift", "Weight_Used": "180",
         "RIR": "2", "Reps_Done": "3"},
    ]
    training = make_training(rows)
    readiness = make_readiness([{"Date": today}])
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    httpd = create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "base": f"http://127.0.0.1:{httpd.server_address[1]}",
            "path": path,
            "today": today,
        }
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _request_full(base, path, *, method="GET", payload=None, token=None,
                  key=None, headers=None):
    merged = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        merged["Content-Type"] = "application/json"
    if token is not None:
        merged["Authorization"] = f"Bearer {token}"
    if key is not None:
        merged["Idempotency-Key"] = key
    request = urllib.request.Request(
        base + path, data=data, headers=merged, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw), dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"raw": raw}
        return exc.code, body, dict(exc.headers)


def _request(base, path, **kwargs):
    status, body, _ = _request_full(base, path, **kwargs)
    return status, body


def _mint(path):
    store = db.Store(path)
    try:
        return ios_devices.mint_pairing_code(store.connection)["code"]
    finally:
        store.close()


def _pair(base, code, label="iPhone"):
    return _request(base, "/api/ios/v1/pair", method="POST",
                    payload={"code": code, "label": label})


def _paired(ios):
    code = _mint(ios["path"])
    status, body = _pair(ios["base"], code)
    assert status == 200, body
    return body["token"], body["device"]


def _scalar(path, sql, params=()):
    store = db.Store(path)
    try:
        row = store.connection.execute(sql, params).fetchone()
        return row[0] if row is not None else None
    finally:
        store.close()


def _row(path, sql, params=()):
    store = db.Store(path)
    try:
        row = store.connection.execute(sql, params).fetchone()
        return dict(row) if row is not None else None
    finally:
        store.close()


def _issue(ios, token, *, key=None, body=None):
    return _request(
        ios["base"], "/api/ios/v1/prescriptions", method="POST",
        payload=body if body is not None else {}, token=token,
        key=key or uuid.uuid4().hex,
    )


def _start(ios, token, issued_plan_id, *, key=None, body=None):
    payload = body if body is not None else {"issued_plan_id": issued_plan_id}
    return _request(
        ios["base"], "/api/ios/v1/workouts", method="POST",
        payload=payload, token=token, key=key or uuid.uuid4().hex,
    )


def _first_item(plan):
    items = plan.get("items") or []
    assert items, "the issued plan is empty"
    return items[0]


def _add_set(ios, token, workout_id, item, *, key=None, **overrides):
    payload = {
        "exercise_id": item["exercise_id"],
        "load_kg": item.get("load_kg"),
        "reps": 3,
        "rir": 2,
        "velocity_mps": 0.62,
        "set_index": 1,
    }
    payload.update(overrides)
    return _request(
        ios["base"], f"/api/ios/v1/workouts/{workout_id}/sets", method="POST",
        payload=payload, token=token, key=key or uuid.uuid4().hex,
    )


def _active_workout(ios, token):
    status, today = _request(ios["base"], "/api/ios/v1/today", token=token)
    assert status == 200, today
    return today.get("active_workout")


# --- readiness -------------------------------------------------------------


def test_readiness_write_replays_without_a_second_manual_entry(ios):
    token, _ = _paired(ios)
    key = uuid.uuid4().hex
    payload = {"values": {"sleep": 4, "energy": 3, "mood": 5, "soreness": 4,
                          "stress": 3, "hrv_ms": 55}, "note": "test"}
    before = int(_scalar(ios["path"], "SELECT COUNT(*) FROM readiness_entry"))
    status, body = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload=payload, token=token, key=key,
    )
    assert status == 200, body
    assert body["score"]["status"] == "ready"
    after = int(_scalar(ios["path"], "SELECT COUNT(*) FROM readiness_entry"))
    assert after > before

    status, replay, headers = _request_full(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload=payload, token=token, key=key,
    )
    assert status == 200, replay
    assert replay == body
    assert headers.get("Idempotent-Replay") == "true"
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM readiness_entry")) == after
    assert body["sleep"] == 4.0


def _healthkit_sample(field="hrv_ms", value=55.0, *, sample_id=None, sample_at=None,
                      source_name="Apple Watch", source_class="apple_watch",
                      source_model="Watch6,18", source_manufacturer="Apple Inc."):
    return {
        "field": field,
        "value": value,
        "sample_id": sample_id or uuid.uuid4().hex,
        "sample_at": sample_at or datetime.datetime.now(datetime.UTC).isoformat(),
        "source_name": source_name,
        "source_bundle_id": "com.apple.health",
        "source_class": source_class,
        "source_model": source_model,
        "source_manufacturer": source_manufacturer,
    }


def _healthkit(ios, token, samples=None, *, day=None, key=None):
    payload = {
        "date": day or ios["today"],
        "samples": samples if samples is not None else [
            _healthkit_sample("hrv_ms", 55.0),
            _healthkit_sample("rhr_bpm", 52.0),
        ],
    }
    return _request(
        ios["base"], "/api/ios/v1/healthkit/readiness", method="POST",
        payload=payload, token=token, key=key or uuid.uuid4().hex,
    )


def test_healthkit_readiness_imports_and_replays(ios):
    token, _ = _paired(ios)
    samples = [_healthkit_sample("hrv_ms", 55.0), _healthkit_sample("rhr_bpm", 52.0)]
    key = uuid.uuid4().hex
    status, body = _healthkit(ios, token, samples, key=key)
    assert status == 200, body
    assert body["healthkit"]["hrv_ms"]["value"] == 55.0
    assert body["healthkit"]["rhr_bpm"]["value"] == 52.0
    assert body["sources"]["hrv_ms"] == "healthkit"
    assert body["sources"]["rhr_bpm"] == "healthkit"
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM healthkit_readiness")) == 2
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM readiness_entry")) == 0
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM readiness_day WHERE hrv_ms IS NOT NULL")) == 0

    status, today = _request(ios["base"], "/api/ios/v1/today", token=token)
    assert status == 200
    assert today["readiness"]["healthkit"]["hrv_ms"]["value"] == 55.0
    assert today["readiness"]["sources"]["hrv_ms"] == "healthkit"

    status, replay, headers = _request_full(
        ios["base"], "/api/ios/v1/healthkit/readiness", method="POST",
        payload={"date": ios["today"], "samples": samples},
        token=token, key=key,
    )
    assert status == 200, replay
    assert replay == body
    assert headers.get("Idempotent-Replay") == "true"
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM healthkit_readiness")) == 2


def test_healthkit_sample_identity_conflicts_are_atomic(ios):
    token, _ = _paired(ios)
    first = _healthkit_sample("hrv_ms", 55.0, sample_id="sample-a")
    status, _ = _healthkit(ios, token, [first], key=uuid.uuid4().hex)
    assert status == 200

    changed_value = {**first, "value": 56.0}
    status, body = _healthkit(ios, token, [changed_value], key=uuid.uuid4().hex)
    assert status == 409, body
    assert body["code"] == "healthkit_sample_conflict"
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM healthkit_readiness")) == 1

    changed_at = {**first, "sample_at": datetime.datetime.now(datetime.UTC).isoformat()}
    status, body = _healthkit(ios, token, [changed_at], key=uuid.uuid4().hex)
    assert status == 409, body

    changed_source = {**first, "source_name": "Other Source"}
    status, body = _healthkit(ios, token, [changed_source], key=uuid.uuid4().hex)
    assert status == 409, body

    changed_class = {**first, "source_class": "unknown"}
    status, body = _healthkit(ios, token, [changed_class], key=uuid.uuid4().hex)
    assert status == 409, body

    status, body = _healthkit(ios, token, [first], key=uuid.uuid4().hex)
    assert status == 200, body
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM healthkit_readiness")) == 1

    mixed = [
        _healthkit_sample("rhr_bpm", 50.0, sample_id="sample-b"),
        {**first, "value": 54.0},
    ]
    status, body = _healthkit(ios, token, mixed, key=uuid.uuid4().hex)
    assert status == 409, body
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM healthkit_readiness")) == 1


def test_healthkit_observations_are_device_scoped(ios):
    first_token, first_device = _paired(ios)
    second_token, second_device = _paired(ios)
    assert first_device["device_id"] != second_device["device_id"]
    first = _healthkit_sample("hrv_ms", 55.0, sample_id="shared-sample")
    second = _healthkit_sample("hrv_ms", 56.0, sample_id="shared-sample")
    status, body = _healthkit(ios, first_token, [first], key=uuid.uuid4().hex)
    assert status == 200, body
    status, body = _healthkit(ios, second_token, [second], key=uuid.uuid4().hex)
    assert status == 200, body
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM healthkit_readiness")) == 2
    status, today = _request(ios["base"], "/api/ios/v1/today", token=first_token)
    assert status == 200
    # Readiness is athlete-level; device scope protects the observation identity, not a separate
    # per-device readiness view. The latest accepted observation is the effective one.
    assert today["readiness"]["healthkit"]["hrv_ms"]["value"] == 56.0
    status, today = _request(ios["base"], "/api/ios/v1/today", token=second_token)
    assert status == 200
    assert today["readiness"]["healthkit"]["hrv_ms"]["value"] == 56.0

def test_healthkit_manual_precedence_keeps_observation(ios):
    token, _ = _paired(ios)
    status, body = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload={"values": {"hrv_ms": 60.0, "rhr_bpm": 58.0}},
        token=token, key=uuid.uuid4().hex,
    )
    assert status == 200, body
    assert body["sources"]["hrv_ms"] == "manual"

    status, body = _healthkit(ios, token, [
        _healthkit_sample("hrv_ms", 55.0),
        _healthkit_sample("rhr_bpm", 52.0),
    ], key=uuid.uuid4().hex)
    assert status == 200, body
    assert body["hrv_ms"] == 60.0
    assert body["rhr_bpm"] == 58.0
    assert body["sources"]["hrv_ms"] == "manual"
    assert body["healthkit"]["hrv_ms"]["value"] == 55.0
    assert body["healthkit"]["rhr_bpm"]["value"] == 52.0


def test_healthkit_bodyweight_is_an_optional_readiness_observation(ios):
    token, _ = _paired(ios)
    sample = _healthkit_sample(
        "bodyweight_kg", 80.5,
        sample_at=(datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)).isoformat(),
    )
    status, body = _healthkit(ios, token, [sample], key=uuid.uuid4().hex)
    assert status == 200, body
    assert body["bodyweight_kg"] == 80.5
    assert body["healthkit"]["bodyweight_kg"]["value"] == 80.5
    assert body["sources"]["bodyweight_kg"] == "healthkit"
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM healthkit_readiness")) == 1

    status, manual = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload={"values": {"bodyweight_kg": 81.0}},
        token=token, key=uuid.uuid4().hex,
    )
    assert status == 200, manual
    assert manual["bodyweight_kg"] == 81.0
    assert manual["sources"]["bodyweight_kg"] == "manual"
    assert manual["healthkit"]["bodyweight_kg"]["value"] == 80.5

    stale = _healthkit_sample(
        "bodyweight_kg", 79.0,
        sample_at=(datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=31)).isoformat(),
    )
    status, body = _healthkit(ios, token, [stale], key=uuid.uuid4().hex)
    assert status == 400, body
    assert any(key.endswith("sample_at") for key in body.get("fields", {}))


def test_healthkit_validation_and_device_scope(ios):
    token, _ = _paired(ios)
    future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10)).isoformat()
    stale = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=49)).isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    cases = [
        ({"date": yesterday, "samples": [_healthkit_sample()]}, "date"),
        ({"date": ios["today"], "samples": []}, "samples"),
        ({"date": ios["today"], "samples": [
            _healthkit_sample("hrv_ms", 0.0), _healthkit_sample("rhr_bpm", 52.0),
        ]}, "value"),
        ({"date": ios["today"], "samples": [
            _healthkit_sample("hrv_ms", -1.0), _healthkit_sample("rhr_bpm", 52.0),
        ]}, "value"),
        ({"date": ios["today"], "samples": [
            _healthkit_sample("hrv_ms", 55.0, sample_at=future),
        ]}, "sample_at"),
        ({"date": ios["today"], "samples": [
            _healthkit_sample("hrv_ms", 55.0, sample_at=stale),
        ]}, "sample_at"),
        ({"date": ios["today"], "samples": [
            _healthkit_sample("rhr_bpm", 52.0, sample_at=stale),
        ]}, "sample_at"),
        ({"date": ios["today"], "samples": [
            _healthkit_sample("hrv_ms", 55.0), _healthkit_sample("hrv_ms", 56.0),
        ]}, "field"),
        ({"date": ios["today"], "samples": [
            _healthkit_sample("hrv_ms", 55.0, source_class="watch"),
        ]}, "source_class"),
        ({"date": ios["today"], "samples": [
            _healthkit_sample("sleep", 4.0),
        ]}, "field"),
    ]
    for payload, field in cases:
        status, body = _request(
            ios["base"], "/api/ios/v1/healthkit/readiness", method="POST",
            payload=payload, token=token, key=uuid.uuid4().hex,
        )
        assert status == 400, (payload, body)
        fields = body.get("fields", {})
        assert any(key == field or key.endswith("." + field) for key in fields), (payload, body)

    status, body = _healthkit(ios, token, [_healthkit_sample("hrv_ms", 55.0)], key=uuid.uuid4().hex)
    assert status == 200, body
    status, body = _healthkit(ios, token, [_healthkit_sample("hrv_ms", 56.0)], key=uuid.uuid4().hex)
    assert status == 200, body
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM healthkit_readiness")) == 2


def test_ready_partial_readiness_can_start_without_stress(ios):
    token, _ = _paired(ios)
    store = db.Store(ios["path"])
    try:
        store.connection.execute(
            "DELETE FROM readiness_day WHERE on_date = ?", (ios["today"],)
        )
        store.connection.execute(
            "DELETE FROM readiness_entry WHERE on_date = ?", (ios["today"],)
        )
    finally:
        store.close()
    status, readiness = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload={"values": {"sleep": 5, "energy": 3, "mood": 5, "soreness": 5}},
        token=token, key=uuid.uuid4().hex,
    )
    assert status == 200, readiness
    assert readiness["score"]["status"] == "ready"
    assert readiness.get("stress") is None

    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    assert workout["status"] == "in_progress"


def test_readiness_rejects_unknown_empty_and_removed_fields(ios):
    token, _ = _paired(ios)
    cases = [
        ({"values": {}}, "values"),
        ({"values": {"sleep": 0}}, "sleep"),
        ({"values": {"nutrition": 4}}, "nutrition"),
        ({"values": {"unknown": 4}}, "unknown"),
        ({"values": {"sleep": 4}, "plan": {}}, "plan"),
    ]
    for payload, field in cases:
        status, body = _request(
            ios["base"], "/api/ios/v1/readiness", method="POST",
            payload=payload, token=token, key=uuid.uuid4().hex,
        )
        assert status == 400, (payload, body)
        fields = body.get("fields", {})
        assert any(key == field or key.endswith("." + field) for key in fields), (payload, body)


# --- prescription issue ----------------------------------------------------


def test_prescription_issue_persists_normal_prescription_and_plan(ios):
    token, _ = _paired(ios)
    status, body = _issue(ios, token)
    assert status == 200, body
    assert body["issued_plan_id"]
    assert body["prescription_id"]
    assert body["for_date"] == ios["today"]
    assert body["plan"]["items"]
    assert body["plan"]["for_date"] == ios["today"]
    assert body["readiness"]["status"] == "ready"
    assert body["expires_at"]
    plan_row = _row(
        ios["path"],
        "SELECT * FROM ios_issued_plan WHERE issued_plan_id = ?",
        (body["issued_plan_id"],),
    )
    assert plan_row["prescription_id"] == body["prescription_id"]
    assert plan_row["consumed_at"] is None
    assert plan_row["superseded_at"] is None
    assert int(_scalar(
        ios["path"],
        "SELECT COUNT(*) FROM prescription WHERE prescription_id = ?",
        (body["prescription_id"],),
    )) == 1

    status, rejected = _request(
        ios["base"], "/api/ios/v1/prescriptions", method="POST",
        payload={"plan": {"items": []}}, token=token, key=uuid.uuid4().hex,
    )
    assert status == 400
    assert "plan" in rejected["fields"]
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM ios_issued_plan")) == 1


def test_prescription_requires_readiness_or_explicit_ack(ios):
    token, _ = _paired(ios)
    store = db.Store(ios["path"])
    try:
        store.connection.execute(
            "DELETE FROM readiness_day WHERE on_date = ?", (ios["today"],)
        )
        store.connection.execute(
            "DELETE FROM readiness_entry WHERE on_date = ?", (ios["today"],)
        )
    finally:
        store.close()

    status, body = _issue(ios, token)
    assert status == 409, body
    assert body["code"] == "readiness_required"
    assert body["details"]["can_acknowledge"] is True
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM ios_issued_plan")) == 0

    status, body = _issue(ios, token, body={"readiness_ack": True})
    assert status == 200, body
    row = _row(
        ios["path"],
        "SELECT readiness_ack FROM ios_issued_plan WHERE issued_plan_id = ?",
        (body["issued_plan_id"],),
    )
    assert row["readiness_ack"] == 1


def test_prescription_supersedes_previous_live_plan(ios):
    token, _ = _paired(ios)
    status, first = _issue(ios, token)
    assert status == 200, first
    status, second = _issue(ios, token)
    assert status == 200, second
    first_row = _row(
        ios["path"],
        "SELECT superseded_at FROM ios_issued_plan WHERE issued_plan_id = ?",
        (first["issued_plan_id"],),
    )
    assert first_row["superseded_at"] is not None
    status, body = _start(ios, token, first["issued_plan_id"])
    assert status == 410, body
    assert body["code"] == "plan_superseded"


def test_prescription_issue_requires_idempotency_and_rejects_unknown_fields(ios):
    token, _ = _paired(ios)
    status, body = _request(
        ios["base"], "/api/ios/v1/prescriptions", method="POST",
        payload={}, token=token,
    )
    assert status == 400, body
    assert body["code"] == "idempotency_key_required"

    status, body = _issue(ios, token, body={"session_type": "squat"})
    assert status == 400, body
    assert "session_type" in body["fields"]

    status, body = _issue(ios, token, body={"readiness_ack": "yes"})
    assert status == 400, body
    assert "readiness_ack" in body["fields"]


def test_scheduled_deload_and_drop_require_confirmation(ios, monkeypatch):
    token, _ = _paired(ios)
    monkeypatch.setattr(
        web_server.deload_feature,
        "scheduled_decision",
        lambda *args, **kwargs: DeloadDecision(
            reason="test scheduled deload", trigger="scheduled", block_week=1
        ),
    )
    status, body = _issue(ios, token)
    assert status == 409, body
    assert body["code"] == "confirmation_required"
    assert "deload" in body["details"]
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM ios_issued_plan")) == 0

    status, body = _issue(ios, token, body={"confirmations": {"deload": False}})
    assert status == 200, body

    monkeypatch.setattr(
        web_server.Handler,
        "_drop_confirmation_window",
        lambda self, conn, day: {
            "date": day, "applies": True, "reason": "test drop window",
        },
    )
    status, body = _issue(ios, token)
    assert status == 409, body
    assert "drop" in body["details"]
    status, body = _issue(
        ios, token, body={"confirmations": {"deload": False, "drop": False}}
    )
    assert status == 200, body


# --- start -----------------------------------------------------------------


def test_start_by_id_is_idempotent_and_adopts_active_workout(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    key = uuid.uuid4().hex
    status, first = _start(ios, token, issued["issued_plan_id"], key=key)
    assert status == 200, first
    assert first["status"] == "in_progress"
    assert first["prescription_id"] == issued["prescription_id"]
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM workout_session")) == 1

    status, replay, headers = _request_full(
        ios["base"], "/api/ios/v1/workouts", method="POST",
        payload={"issued_plan_id": issued["issued_plan_id"]},
        token=token, key=key,
    )
    assert status == 200, replay
    assert replay["workout_id"] == first["workout_id"]
    assert headers.get("Idempotent-Replay") == "true"
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM workout_session")) == 1

    status, adopted = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, adopted
    assert adopted["workout_id"] == first["workout_id"]
    row = _row(
        ios["path"],
        "SELECT consumed_at, workout_id FROM ios_issued_plan WHERE issued_plan_id = ?",
        (issued["issued_plan_id"],),
    )
    assert row["consumed_at"] is not None
    assert row["workout_id"] == first["workout_id"]


def test_start_rejects_other_device_and_client_plan_content(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    code = _mint(ios["path"])
    status, second = _pair(ios["base"], code, label="Other iPhone")
    assert status == 200, second

    status, body = _start(ios, second["token"], issued["issued_plan_id"])
    assert status == 404, body
    assert body["code"] == "plan_not_found"

    status, body = _start(
        ios, token, issued["issued_plan_id"],
        body={"issued_plan_id": issued["issued_plan_id"], "plan": {"items": []}},
    )
    assert status == 400, body
    assert "plan" in body["fields"]


def test_start_rejects_expired_and_consumed_plans(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    store = db.Store(ios["path"])
    try:
        store.connection.execute(
            "UPDATE ios_issued_plan SET expires_at = ? WHERE issued_plan_id = ?",
            ("2000-01-01T00:00:00+00:00", issued["issued_plan_id"]),
        )
    finally:
        store.close()
    status, body = _start(ios, token, issued["issued_plan_id"])
    assert status == 410, body
    assert body["code"] == "plan_expired"

    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, started = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, started
    status, completed = _request(
        ios["base"], f"/api/ios/v1/workouts/{started['workout_id']}/complete",
        method="POST", payload={"not_recorded": True}, token=token,
        key=uuid.uuid4().hex,
    )
    assert status == 200, completed
    status, body = _start(ios, token, issued["issued_plan_id"])
    assert status == 410, body
    assert body["code"] == "plan_consumed"


# --- sets, form, completion, abandon --------------------------------------


def test_add_set_stores_manual_velocity_and_retries_without_duplicates(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])

    key = uuid.uuid4().hex
    status, first = _add_set(ios, token, workout["workout_id"], item, key=key)
    assert status == 200, first
    assert len(first["sets"]) == 1
    assert first["sets"][0]["velocity"] == 0.62

    status, replay, headers = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/sets",
        method="POST",
        payload={
            "exercise_id": item["exercise_id"], "load_kg": item.get("load_kg"),
            "reps": 3, "rir": 2, "velocity_mps": 0.62, "set_index": 1,
        },
        token=token, key=key,
    )
    assert status == 200, replay
    assert len(replay["sets"]) == 1
    assert headers.get("Idempotent-Replay") == "true"

    status, deduped = _add_set(
        ios, token, workout["workout_id"], item, set_index=1
    )
    assert status == 200, deduped
    assert len(deduped["sets"]) == 1

    status, second = _add_set(
        ios, token, workout["workout_id"], item, set_index=2
    )
    assert status == 200, second
    assert len(second["sets"]) == 2

    status, invalid = _add_set(
        ios, token, workout["workout_id"], item,
        set_index=3, velocity_mps=0,
    )
    assert status == 400, invalid
    assert "velocity_mps" in invalid["fields"]

    status, invalid = _add_set(
        ios, token, workout["workout_id"], item, set_index=4, rir=7
    )
    assert status == 400, invalid
    assert "rir" in invalid["fields"]


def test_form_and_complete_materialise_once(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    assert _add_set(ios, token, workout["workout_id"], item)[0] == 200

    status, formed = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/form",
        method="POST", payload={"exercise_id": item["exercise_id"], "rating": 4},
        token=token, key=uuid.uuid4().hex,
    )
    assert status == 200, formed
    assert formed["forms"][0]["rating"] == 4

    status, invalid = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload={}, token=token, key=uuid.uuid4().hex,
    )
    assert status == 400, invalid
    assert invalid["code"] == "session_rpe_required"

    key = uuid.uuid4().hex
    payload = {"session_rpe": 7, "duration_min": 45, "notes": "test session"}
    status, completed = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload=payload, token=token, key=key,
    )
    assert status == 200, completed
    assert completed["status"] == "completed"
    assert completed["session_rpe"] == 7.0
    assert int(_scalar(
        ios["path"], "SELECT COUNT(*) FROM session WHERE session_id = ?",
        (workout["workout_id"],),
    )) == 1

    status, replay, headers = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload=payload, token=token, key=key,
    )
    assert status == 200, replay
    assert headers.get("Idempotent-Replay") == "true"
    assert int(_scalar(
        ios["path"], "SELECT COUNT(*) FROM session WHERE session_id = ?",
        (workout["workout_id"],),
    )) == 1

    status, body = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload={"not_recorded": True}, token=token,
        key=uuid.uuid4().hex,
    )
    assert status == 409, body
    assert body["code"] == "workout_not_active"

    status, history = _request(ios["base"], "/api/ios/v1/history", token=token)
    assert status == 200
    assert any(s["session_id"] == workout["workout_id"] for s in history["sessions"])


def test_abandon_and_completion_retry_rules(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    key = uuid.uuid4().hex
    status, abandoned = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/abandon",
        method="POST", payload={}, token=token, key=key,
    )
    assert status == 200, abandoned
    assert abandoned["status"] == "abandoned"

    status, replay, headers = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/abandon",
        method="POST", payload={}, token=token, key=key,
    )
    assert status == 200, replay
    assert headers.get("Idempotent-Replay") == "true"

    status, body = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/abandon",
        method="POST", payload={}, token=token, key=uuid.uuid4().hex,
    )
    assert status == 409, body
    assert body["code"] == "workout_not_active"

    status, body = _start(ios, token, issued["issued_plan_id"])
    assert status == 410, body
    assert body["code"] == "plan_consumed"


# --- concurrency, lost responses, recovery -------------------------------


def _concurrent_require_barrier(monkeypatch):
    """Release both requests from config loading at the same instant.

    The receipt check moved inside the write transaction, so the second request must wait
    there. In the old code both requests would reach their pre-transaction receipt lookup and
    both see no receipt.
    """
    barrier = threading.Barrier(2)
    original = web_server.Handler._ios_require_mutations

    def synchronized(self):
        config = original(self)
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait(timeout=2)
        return config

    monkeypatch.setattr(web_server.Handler, "_ios_require_mutations", synchronized)

    # The old code looked up the receipt before opening the write transaction. Pausing both
    # lookups makes that race deterministic: the fixed code holds one transaction, so only
    # one lookup can enter and the other times out while waiting for the write lock.
    receipt_barrier = threading.Barrier(2)
    original_get = web_server.ios_workflow.get_receipt

    def get_receipt(conn, device_id, operation_id):
        result = original_get(conn, device_id, operation_id)
        with contextlib.suppress(threading.BrokenBarrierError):
            receipt_barrier.wait(timeout=0.5)
        return result

    monkeypatch.setattr(web_server.ios_workflow, "get_receipt", get_receipt)
    return barrier


def test_concurrent_identical_readiness_runs_once_and_replays(ios, monkeypatch):
    token, device = _paired(ios)
    key = uuid.uuid4().hex
    payload = {"values": {"sleep": 4}}
    _concurrent_require_barrier(monkeypatch)
    before = int(_scalar(ios["path"], "SELECT COUNT(*) FROM readiness_entry"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _request_full, ios["base"], "/api/ios/v1/readiness",
                method="POST", payload=payload, token=token, key=key,
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=20) for future in futures]

    assert [status for status, _, _ in results] == [200, 200]
    assert sum(
        1 for _, _, headers in results
        if headers.get("Idempotent-Replay") == "true"
    ) == 1
    after = int(_scalar(ios["path"], "SELECT COUNT(*) FROM readiness_entry"))
    assert after == before + 1
    assert int(_scalar(
        ios["path"],
        "SELECT COUNT(*) FROM ios_operation_receipt "
        "WHERE device_id = ? AND operation_id = ?",
        (device["device_id"], str(uuid.UUID(key))),
    )) == 1
    monkeypatch.undo()

    status, replay, headers = _request_full(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload=payload, token=token, key=key,
    )
    assert status == 200, replay
    assert headers.get("Idempotent-Replay") == "true"
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM readiness_entry")) == after

    status, body = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload={"values": {"sleep": 5}}, token=token, key=key,
    )
    assert status == 409, body
    assert body["code"] == "idempotency_conflict"


def test_lost_start_response_retry_replays_one_workout(ios):
    token, _ = _paired(ios)
    key = uuid.uuid4().hex
    status, issued = _issue(ios, token)
    assert status == 200, issued
    payload = {"issued_plan_id": issued["issued_plan_id"]}
    first = _request_full(
        ios["base"], "/api/ios/v1/workouts", method="POST",
        payload=payload, token=token, key=key,
    )
    second = _request_full(
        ios["base"], "/api/ios/v1/workouts", method="POST",
        payload=payload, token=token, key=key,
    )
    assert first[0] == 200 and second[0] == 200, (first, second)
    assert second[2].get("Idempotent-Replay") == "true"
    assert first[1]["workout_id"] == second[1]["workout_id"]
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM workout_session")) == 1
    row = _row(
        ios["path"],
        "SELECT consumed_at, workout_id FROM ios_issued_plan WHERE issued_plan_id = ?",
        (payload["issued_plan_id"],),
    )
    assert row["consumed_at"] is not None
    assert row["workout_id"] == first[1]["workout_id"]


def test_lost_set_response_retry_replays_without_duplicate(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    key = uuid.uuid4().hex
    payload = {
        "exercise_id": item["exercise_id"],
        "load_kg": item.get("load_kg"),
        "reps": 3, "rir": 2, "velocity_mps": 0.62, "set_index": 1,
    }
    first = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/sets",
        method="POST", payload=payload, token=token, key=key,
    )
    second = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/sets",
        method="POST", payload=payload, token=token, key=key,
    )
    assert first[0] == 200 and second[0] == 200, (first, second)
    assert second[2].get("Idempotent-Replay") == "true"
    assert len(first[1]["sets"]) == 1
    assert len(second[1]["sets"]) == 1
    assert int(_scalar(
        ios["path"], "SELECT COUNT(*) FROM workout_set WHERE workout_id = ?",
        (workout["workout_id"],),
    )) == 1


def test_lost_completion_response_retry_replays_one_session(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    assert _add_set(ios, token, workout["workout_id"], item)[0] == 200
    key = uuid.uuid4().hex
    payload = {"session_rpe": 7, "duration_min": 45, "notes": "lost response"}
    first = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload=payload, token=token, key=key,
    )
    second = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload=payload, token=token, key=key,
    )
    assert first[0] == 200 and second[0] == 200, (first, second)
    assert second[2].get("Idempotent-Replay") == "true"
    assert first[1]["status"] == "completed"
    assert second[1]["status"] == "completed"
    assert int(_scalar(
        ios["path"], "SELECT COUNT(*) FROM session WHERE session_id = ?",
        (workout["workout_id"],),
    )) == 1


def test_concurrent_identical_set_requests_do_not_duplicate(ios, monkeypatch):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    key = uuid.uuid4().hex
    payload = {
        "exercise_id": item["exercise_id"],
        "load_kg": item.get("load_kg"),
        "reps": 3, "rir": 2, "velocity_mps": 0.62, "set_index": 1,
    }
    _concurrent_require_barrier(monkeypatch)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _request_full,
                ios["base"],
                f"/api/ios/v1/workouts/{workout['workout_id']}/sets",
                method="POST", payload=payload, token=token, key=key,
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=20) for future in futures]
    assert [status for status, _, _ in results] == [200, 200]
    assert sum(
        1 for _, _, headers in results
        if headers.get("Idempotent-Replay") == "true"
    ) == 1
    assert int(_scalar(
        ios["path"], "SELECT COUNT(*) FROM workout_set WHERE workout_id = ?",
        (workout["workout_id"],),
    )) == 1


def test_concurrent_identical_start_requests_create_one_workout(ios, monkeypatch):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    key = uuid.uuid4().hex
    payload = {"issued_plan_id": issued["issued_plan_id"]}
    _concurrent_require_barrier(monkeypatch)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _request_full, ios["base"], "/api/ios/v1/workouts",
                method="POST", payload=payload, token=token, key=key,
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=20) for future in futures]
    assert [status for status, _, _ in results] == [200, 200]
    assert len({body["workout_id"] for _, body, _ in results}) == 1
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM workout_session")) == 1
    assert int(_scalar(
        ios["path"],
        "SELECT COUNT(*) FROM ios_issued_plan WHERE consumed_at IS NOT NULL",
    )) == 1


def test_concurrent_identical_completion_materialises_one_session(ios, monkeypatch):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    assert _add_set(ios, token, workout["workout_id"], item)[0] == 200
    key = uuid.uuid4().hex
    payload = {"session_rpe": 7, "duration_min": 45}
    _concurrent_require_barrier(monkeypatch)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _request_full,
                ios["base"],
                f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
                method="POST", payload=payload, token=token, key=key,
            )
            for _ in range(2)
        ]
        results = [future.result(timeout=20) for future in futures]
    assert [status for status, _, _ in results] == [200, 200]
    assert sum(
        1 for _, _, headers in results
        if headers.get("Idempotent-Replay") == "true"
    ) == 1
    assert int(_scalar(
        ios["path"], "SELECT COUNT(*) FROM session WHERE session_id = ?",
        (workout["workout_id"],),
    )) == 1


def test_active_workout_recovery_returns_logged_sets(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    first = _add_set(ios, token, workout["workout_id"], item)
    assert first[0] == 200, first
    status, today = _request(ios["base"], "/api/ios/v1/today", token=token)
    assert status == 200, today
    active = today["active_workout"]
    assert active["workout_id"] == workout["workout_id"]
    assert len(active["sets"]) == 1
    assert active["sets"][0]["velocity"] == 0.62

    second = _add_set(
        ios, token, workout["workout_id"], item, set_index=2
    )
    assert second[0] == 200, second
    assert len(second[1]["sets"]) == 2
    status, completed = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload={"session_rpe": 7}, token=token,
        key=uuid.uuid4().hex,
    )
    assert status == 200, completed
    assert completed["status"] == "completed"
    assert int(_scalar(
        ios["path"], "SELECT COUNT(*) FROM workout_set WHERE workout_id = ?",
        (workout["workout_id"],),
    )) == 2


def test_set_is_rejected_after_completion_or_abandonment(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    assert _add_set(ios, token, workout["workout_id"], item)[0] == 200
    status, completed = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload={"not_recorded": True}, token=token,
        key=uuid.uuid4().hex,
    )
    assert status == 200, completed
    status, body = _add_set(
        ios, token, workout["workout_id"], item, set_index=2
    )
    assert status == 409, body
    assert body["code"] == "workout_not_active"
    assert int(_scalar(
        ios["path"], "SELECT COUNT(*) FROM workout_set WHERE workout_id = ?",
        (workout["workout_id"],),
    )) == 1

    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    status, abandoned = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/abandon",
        method="POST", payload={}, token=token, key=uuid.uuid4().hex,
    )
    assert status == 200, abandoned
    status, body = _add_set(ios, token, workout["workout_id"], item)
    assert status == 409, body
    assert body["code"] == "workout_not_active"


def test_second_start_while_active_is_rejected(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    status, second = _issue(ios, token)
    assert status == 200, second
    status, body = _start(ios, token, second["issued_plan_id"])
    assert status == 409, body
    assert body["code"] == "workout_active"
    assert body["details"]["workout_id"] == workout["workout_id"]


def test_lost_form_and_abandon_responses_replay(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])

    form_key = uuid.uuid4().hex
    form_payload = {"exercise_id": item["exercise_id"], "rating": 4}
    first = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/form",
        method="POST", payload=form_payload, token=token, key=form_key,
    )
    second = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/form",
        method="POST", payload=form_payload, token=token, key=form_key,
    )
    assert first[0] == 200 and second[0] == 200, (first, second)
    assert second[2].get("Idempotent-Replay") == "true"
    assert int(_scalar(
        ios["path"],
        "SELECT COUNT(*) FROM workout_form_rating WHERE workout_id = ?",
        (workout["workout_id"],),
    )) == 1

    abandon_key = uuid.uuid4().hex
    first = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/abandon",
        method="POST", payload={}, token=token, key=abandon_key,
    )
    second = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/abandon",
        method="POST", payload={}, token=token, key=abandon_key,
    )
    assert first[0] == 200 and second[0] == 200, (first, second)
    assert second[2].get("Idempotent-Replay") == "true"
    assert first[1]["status"] == "abandoned"
    assert second[1]["status"] == "abandoned"


# --- idempotency, config flag, security ------------------------------------


def test_idempotency_conflict_for_changed_body_or_route(ios):
    token, _ = _paired(ios)
    key = uuid.uuid4().hex
    status, first = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload={"values": {"sleep": 4}}, token=token, key=key,
    )
    assert status == 200, first
    status, body = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload={"values": {"sleep": 5}}, token=token, key=key,
    )
    assert status == 409, body
    assert body["code"] == "idempotency_conflict"

    status, body = _request(
        ios["base"], "/api/ios/v1/prescriptions", method="POST",
        payload={}, token=token, key=key,
    )
    assert status == 409, body
    assert body["code"] == "idempotency_conflict"


def test_mutations_disabled_keeps_reads_available(ios, monkeypatch):
    token, _ = _paired(ios)
    monkeypatch.setattr(
        web_server.ios_config,
        "load_config",
        lambda: ios_config.IOSConfig(False, 3600, 30),
    )
    status, bootstrap = _request(
        ios["base"], "/api/ios/v1/bootstrap", token=token,
    )
    assert status == 200
    assert bootstrap["capabilities"]["readiness_write"] is False
    assert bootstrap["capabilities"]["prescription"] is False
    assert bootstrap["capabilities"]["workout_write"] is False
    assert bootstrap["capabilities"]["healthkit_readiness"] is False

    status, today = _request(ios["base"], "/api/ios/v1/today", token=token)
    assert status == 200
    assert today["date"] == ios["today"]

    status, body = _issue(ios, token)
    assert status == 503, body
    assert body["code"] == "ios_mutations_disabled"

    status, body = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload={"values": {"sleep": 4}}, token=token,
        key=uuid.uuid4().hex,
    )
    assert status == 503, body

    status, body = _request(
        ios["base"], "/api/ios/v1/healthkit/readiness", method="POST",
        payload={"date": ios["today"], "samples": [
            _healthkit_sample("hrv_ms", 55.0),
        ]}, token=token, key=uuid.uuid4().hex,
    )
    assert status == 503, body
    assert body["code"] == "ios_mutations_disabled"


def test_mutation_bodies_and_secrets_do_not_enter_the_log_buffer(ios):
    token, _ = _paired(ios)
    web_server._LOG_BUFFER.clear()
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    status, with_set = _add_set(ios, token, workout["workout_id"], item)
    assert status == 200, with_set
    status, logs = _request(ios["base"], "/api/logs?limit=500")
    assert status == 200
    with web_server._LOG_LOCK:
        buffered = "\n".join(
            entry["message"] for entry in web_server._LOG_BUFFER
        )
    seen = json.dumps(logs) + "\n" + buffered
    assert token not in seen
    assert "velocity_mps" not in seen
    assert "session_rpe" not in seen
