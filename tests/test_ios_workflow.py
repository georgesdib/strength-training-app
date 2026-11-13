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
import time
import urllib.error
import urllib.request
import uuid

import pytest
from conftest import make_readiness, make_training

from strength_coach import ios_config
from strength_coach.features.deload import DeloadDecision
from strength_coach.store import db, importer, ios_devices
from strength_coach.web import ios_plan_worker
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
        # The dispatcher is a per-process singleton; stop it so the next test's temporary
        # database does not inherit a worker watching a deleted file.
        ios_plan_worker.stop_dispatcher()


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


def _plan_state(ios, token):
    status, body = _request(ios["base"], "/api/ios/v1/plans/current", token=token)
    assert status == 200, body
    return body


def _wait_for_plan(ios, token, *, timeout=60.0):
    """Poll until the request settles; the dispatcher may already have built it."""
    deadline = time.monotonic() + timeout
    while True:
        state = _plan_state(ios, token)
        if state["status"] in {"ready", "error", "none"}:
            return state
        if time.monotonic() >= deadline:
            raise AssertionError(f"plan request did not settle: {state}")
        time.sleep(0.05)


def _issue(ios, token, *, key=None, body=None, wait=True):
    """POST the request, then return the settled state.

    R7 made issue asynchronous, so the common case for a test is "the plan is ready": the
    return value keeps the old (status, payload) shape with the READY payload. Pass
    wait=False to inspect the 202 body itself.
    """
    status, issued = _request(
        ios["base"], "/api/ios/v1/prescriptions", method="POST",
        payload=body if body is not None else {}, token=token,
        key=key or uuid.uuid4().hex,
    )
    if not wait or status != 202:
        return status, issued
    state = _wait_for_plan(ios, token)
    return 200, state


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


def _plan_edit(ios, token, workout_id, suffix, payload, *, key=None):
    return _request(
        ios["base"], f"/api/ios/v1/workouts/{workout_id}/plan{suffix}", method="POST",
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hrv_ms", -1),
        ("hrv_ms", 0),
        ("hrv_ms", "nan"),
        ("rhr_bpm", 0),
        ("rhr_bpm", "inf"),
        ("bodyweight_kg", -1),
        ("bodyweight_kg", "nan"),
        ("wearable_score", 101),
        ("wearable_score", "-inf"),
    ],
)
def test_readiness_write_rejects_invalid_optional_device_values(ios, field, value):
    token, _ = _paired(ios)
    payload = {
        "values": {
            "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
            field: value,
        },
    }
    status, body = _request(
        ios["base"], "/api/ios/v1/readiness", method="POST",
        payload=payload, token=token, key=uuid.uuid4().hex,
    )
    assert status == 400, body
    assert field in body.get("fields", {}), body


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


def test_ios_exercise_catalogue_and_plan_add_defaults(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    plan_ids = {item["exercise_id"] for item in workout["plan"]["items"]}

    status, catalogue = _request(ios["base"], "/api/ios/v1/exercises", token=token)
    assert status == 200, catalogue
    entries = catalogue["exercises"]
    assert all({"id", "display", "pattern"} <= set(entry) for entry in entries)
    new_id = next(entry["id"] for entry in entries if entry["id"] not in plan_ids)

    status, added = _plan_edit(
        ios, token, workout["workout_id"], "/exercises", {"exercise_id": new_id},
    )
    assert status == 200, added
    item = next(item for item in added["plan"]["items"] if item["exercise_id"] == new_id)
    assert item["sets"] == 3
    assert item["reps_low"] == 8
    assert item["reps_high"] == 12
    assert item["rir_target"] == 2
    assert item["load_kg"] is None
    assert item["added_during_workout"] is True

    status, conflict = _plan_edit(
        ios, token, workout["workout_id"], "/exercises", {"exercise_id": new_id},
    )
    assert status == 409, conflict
    assert conflict["code"] == "exercise_already_present"


def test_ios_plan_swap_expected_guard_and_idempotent_replay(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = workout["plan"]["items"][0]
    plan_ids = {entry["exercise_id"] for entry in workout["plan"]["items"]}
    status, catalogue = _request(ios["base"], "/api/ios/v1/exercises", token=token)
    assert status == 200, catalogue
    new_id = next(entry["id"] for entry in catalogue["exercises"] if entry["id"] not in plan_ids)

    status, conflict = _plan_edit(
        ios, token, workout["workout_id"], "/items/0/swap",
        {"exercise_id": new_id, "expected_exercise_id": "wrong_exercise"},
    )
    assert status == 409, conflict
    assert conflict["code"] == "plan_changed"
    assert conflict["details"]["workout"]["workout_id"] == workout["workout_id"]

    key = uuid.uuid4().hex
    payload = {"exercise_id": new_id, "expected_exercise_id": item["exercise_id"]}
    status, swapped = _plan_edit(
        ios, token, workout["workout_id"], "/items/0/swap", payload, key=key,
    )
    assert status == 200, swapped
    assert swapped["plan"]["items"][0]["exercise_id"] == new_id
    assert swapped["original_plan"]["items"][0]["exercise_id"] == item["exercise_id"]

    # The execution envelope carries the edited plan with its revision so a watch can apply it
    # without a second request (contract §10.1/§10.3).
    status, execution = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/execution",
        token=token,
    )
    assert status == 200, execution
    assert execution["plan_revision"] >= 1
    assert execution["plan"]["items"][0]["exercise_id"] == new_id
    assert swapped["plan"]["items"][0]["load_kg"] is None
    assert swapped["plan"]["items"][0]["substitution_for"] == item["exercise_id"]

    status, replayed = _plan_edit(
        ios, token, workout["workout_id"], "/items/0/swap", payload, key=key,
    )
    assert status == 200, replayed
    assert replayed["plan"]["items"][0]["exercise_id"] == new_id
    assert _scalar(
        ios["path"],
        "SELECT COUNT(*) FROM workout_event WHERE workout_id = ? AND event_type = 'swap_exercise'",
        (workout["workout_id"],),
    ) == 1


def test_ios_plan_edit_blocks_swap_and_set_reduction_after_logged_sets(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item_index = next(
        index for index, entry in enumerate(workout["plan"]["items"])
        if int(entry.get("sets") or 0) >= 4
    )
    item = workout["plan"]["items"][item_index]
    plan_ids = {entry["exercise_id"] for entry in workout["plan"]["items"]}
    status, catalogue = _request(ios["base"], "/api/ios/v1/exercises", token=token)
    assert status == 200, catalogue
    new_id = next(entry["id"] for entry in catalogue["exercises"] if entry["id"] not in plan_ids)

    for index in range(1, 4):
        status, body = _add_set(
            ios, token, workout["workout_id"], item,
            set_index=index, plan_item_index=item_index,
        )
        assert status == 200, body

    status, conflict = _plan_edit(
        ios, token, workout["workout_id"], f"/items/{item_index}/swap",
        {"exercise_id": new_id, "expected_exercise_id": item["exercise_id"]},
    )
    assert status == 409, conflict
    assert conflict["code"] == "sets_already_logged"
    assert conflict["details"]["logged_sets"] == 3

    current = workout["plan"]["items"][item_index]["sets"]
    assert current >= 4
    status, lowered = _plan_edit(
        ios, token, workout["workout_id"], f"/items/{item_index}/sets",
        {"delta": 3 - current, "expected_exercise_id": item["exercise_id"]},
    )
    assert status == 200, lowered
    assert lowered["plan"]["items"][item_index]["sets"] == 3

    status, conflict = _plan_edit(
        ios, token, workout["workout_id"], f"/items/{item_index}/sets",
        {"delta": -1, "expected_exercise_id": item["exercise_id"]},
    )
    assert status == 409, conflict
    assert conflict["code"] == "sets_below_logged"
    assert conflict["details"]["logged_sets"] == 3


def test_ios_remove_last_plan_item_is_blocked(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    workout_id = workout["workout_id"]
    current = workout
    while len(current["plan"]["items"]) > 1:
        item = current["plan"]["items"][0]
        status, current = _plan_edit(
            ios, token, workout_id, "/items/0/remove",
            {"expected_exercise_id": item["exercise_id"]},
        )
        assert status == 200, current
    item = current["plan"]["items"][0]
    status, conflict = _plan_edit(
        ios, token, workout_id, "/items/0/remove",
        {"expected_exercise_id": item["exercise_id"]},
    )
    assert status == 409, conflict
    assert conflict["code"] == "last_plan_item"


def test_ios_set_and_complete_preserve_local_timestamps(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    started_at = datetime.datetime.fromisoformat(workout["started_at"])
    item = workout["plan"]["items"][0]
    performed_at = (started_at + datetime.timedelta(seconds=1)).isoformat()

    status, rejected = _add_set(
        ios, token, workout["workout_id"], item,
        performed_at=(started_at - datetime.timedelta(seconds=1)).isoformat(),
    )
    assert status == 400, rejected

    status, changed = _add_set(
        ios, token, workout["workout_id"], item, performed_at=performed_at,
    )
    assert status == 200, changed
    assert changed["sets"][-1]["created_at"].startswith(performed_at[:19])

    status, rejected = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST",
        payload={
            "session_rpe": 7,
            "ended_at": (started_at - datetime.timedelta(seconds=1)).isoformat(),
        },
        token=token, key=uuid.uuid4().hex,
    )
    assert status == 400, rejected

    ended_at = datetime.datetime.now(datetime.UTC).isoformat()
    status, completed = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST",
        payload={"session_rpe": 7, "ended_at": ended_at},
        token=token, key=uuid.uuid4().hex,
    )
    assert status == 200, completed
    assert completed["status"] == "completed"
    assert completed["duration_source"] == "measured"


def test_ios_set_resolves_stable_plan_item_identity_after_removal(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    items = workout["plan"]["items"]
    assert len(items) >= 3
    first, second, third = items[0], items[1], items[2]
    second_identity = second.get("order_index", 1)
    first_identity = first.get("order_index", 0)
    # The old positional lookup would read items[1], which is now this different exercise.
    assert third["exercise_id"] != second["exercise_id"]

    status, current = _plan_edit(
        ios, token, workout["workout_id"], "/items/0/remove",
        {"expected_exercise_id": first["exercise_id"]},
    )
    assert status == 200, current
    assert current["plan"]["items"][0]["exercise_id"] == second["exercise_id"]

    status, added = _add_set(
        ios, token, workout["workout_id"], second,
        set_index=1, plan_item_index=second_identity,
    )
    assert status == 200, added
    assert _scalar(
        ios["path"],
        "SELECT prescription_item_index FROM workout_set "
        "WHERE workout_id = ? ORDER BY rowid DESC LIMIT 1",
        (workout["workout_id"],),
    ) == second_identity

    status, removed = _add_set(
        ios, token, workout["workout_id"], first,
        set_index=1, plan_item_index=first_identity,
    )
    assert status == 409, removed
    assert removed["code"] == "plan_item_mismatch"

    status, missing = _add_set(
        ios, token, workout["workout_id"], second,
        set_index=2, plan_item_index=999,
    )
    assert status == 409, missing
    assert missing["code"] == "plan_item_mismatch"


def test_ios_removing_an_item_keeps_later_set_identity(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    items = workout["plan"]["items"]
    assert len(items) >= 2
    first = items[0]
    second = items[1]
    second_identity = second.get("order_index", 1)
    for index in (1, 2, 3):
        status, body = _add_set(
            ios, token, workout["workout_id"], second,
            set_index=index, plan_item_index=second_identity,
        )
        assert status == 200, body

    remove_key = uuid.uuid4().hex
    status, body = _plan_edit(
        ios, token, workout["workout_id"], "/items/0/remove",
        {"expected_exercise_id": first["exercise_id"]}, key=remove_key,
    )
    assert status == 200, body
    status, replay = _plan_edit(
        ios, token, workout["workout_id"], "/items/0/remove",
        {"expected_exercise_id": first["exercise_id"]}, key=remove_key,
    )
    assert status == 200, replay
    assert _scalar(
        ios["path"],
        "SELECT COUNT(*) FROM workout_event WHERE workout_id = ? AND event_type = 'remove_exercise'",
        (workout["workout_id"],),
    ) == 1
    bench = next(
        item for item in body["comparison"]["items"]
        if item["exercise_id"] == second["exercise_id"]
    )
    assert bench["plan_item_index"] == second_identity
    assert bench["actual_sets"] == 3

    # Reload through the same authoritative workout read.
    status, today = _request(ios["base"], "/api/ios/v1/today", token=token)
    assert status == 200, today
    reloaded = today["active_workout"]
    bench = next(
        item for item in reloaded["comparison"]["items"]
        if item["exercise_id"] == second["exercise_id"]
    )
    assert bench["actual_sets"] == 3
    assert bench["plan_item_index"] == second_identity

    target = int(second["sets"])
    assert target >= 4
    status, conflict = _plan_edit(
        ios, token, workout["workout_id"], "/items/0/sets",
        {"delta": 1 - target, "expected_exercise_id": second["exercise_id"]},
    )
    assert status == 409, conflict
    assert conflict["code"] == "sets_below_logged"
    status, reduced = _plan_edit(
        ios, token, workout["workout_id"], "/items/0/sets",
        {"delta": 3 - target, "expected_exercise_id": second["exercise_id"]},
    )
    assert status == 200, reduced
    bench = next(
        item for item in reduced["plan"]["items"]
        if item["exercise_id"] == second["exercise_id"]
    )
    assert bench["sets"] == 3

def test_ios_manual_set_accepts_optional_per_rep_velocity(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    status, body = _add_set(
        ios, token, workout["workout_id"], item,
        velocity_mps=None,
        reps=3,
        rep_velocities=[
            {"rep_index": 1, "velocity_mps": 0.62},
            {"rep_index": 2, "velocity_mps": 0.58},
            {"rep_index": 3, "velocity_mps": 0.54},
        ],
    )
    assert status == 200, body
    logged = body["sets"][-1]
    assert logged["velocity"] == 0.58
    assert [rep["velocity_mps"] for rep in logged["reps_detail"]["reps"]] == [0.62, 0.58, 0.54]
    assert logged["rep_summary"]["count"] == 3
    assert logged["rep_summary"]["loss_abs"] == 0.08

    status, body = _add_set(
        ios, token, workout["workout_id"], item,
        velocity_mps=None,
        reps=3,
        rep_velocities=[
            {"rep_index": 1, "velocity_mps": 0.62},
            {"rep_index": 1, "velocity_mps": 0.58},
        ],
    )
    assert status == 400, body
    assert any(key.startswith("rep_velocities") for key in body.get("fields", {}))

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


def test_prescription_issue_queues_then_publishes_a_preview(ios):
    token, _ = _paired(ios)
    status, queued = _issue(ios, token, wait=False)
    assert status == 202, queued
    assert queued["status"] == "queued"
    assert queued["issued_plan_id"]
    assert queued["request_expires_at"]
    assert queued["plan_expires_at"] is None
    assert "plan" not in queued

    body = _wait_for_plan(ios, token)
    assert body["status"] == "ready", body
    assert body["issued_plan_id"] == queued["issued_plan_id"]
    assert body["for_date"] == ios["today"]
    assert body["plan"]["items"]
    assert body["plan"]["for_date"] == ios["today"]
    assert body["readiness"]["status"] == "ready"
    assert body["plan_expires_at"]
    plan_row = _row(
        ios["path"],
        "SELECT * FROM ios_issued_plan WHERE issued_plan_id = ?",
        (body["issued_plan_id"],),
    )
    assert plan_row["status"] == "ready"
    # R7: a preview is not a prescription. The rows appear when the owner starts it.
    assert plan_row["prescription_id"] is None
    assert int(_scalar(ios["path"], "SELECT COUNT(*) FROM prescription")) == 0

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
    # R7: the start transaction is what writes the prescription, and the workout links to it.
    started_row = _row(
        ios["path"],
        "SELECT prescription_id FROM workout_session WHERE workout_id = ?",
        (first["workout_id"],),
    )
    assert started_row["prescription_id"]
    assert first["prescription_id"] == started_row["prescription_id"]
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
    assert status == 409, body
    assert body["code"] == "wrong_execution_target"

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
            "UPDATE ios_issued_plan SET plan_expires_at = ? WHERE issued_plan_id = ?",
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


def test_ios_remove_performed_set(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    status, added = _add_set(ios, token, workout["workout_id"], item)
    assert status == 200, added
    set_id = added["sets"][-1]["set_id"]

    key = uuid.uuid4().hex
    status, removed = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/remove-set",
        method="POST", payload={"set_id": set_id}, token=token, key=key,
    )
    assert status == 200, removed
    assert all(row["set_id"] != set_id for row in removed["sets"])

    status, replay, headers = _request_full(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/remove-set",
        method="POST", payload={"set_id": set_id}, token=token, key=key,
    )
    assert status == 200, replay
    assert headers.get("Idempotent-Replay") == "true"


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

    status, invalid_productivity = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload={"session_rpe": 7, "productivity": 6},
        token=token, key=uuid.uuid4().hex,
    )
    assert status == 400, invalid_productivity
    assert invalid_productivity["fields"]["productivity"] == "must be an integer from 1 to 5"

    key = uuid.uuid4().hex
    payload = {
        "session_rpe": 7, "duration_min": 45, "notes": "test session",
        "productivity": 4,
    }
    status, completed = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/complete",
        method="POST", payload=payload, token=token, key=key,
    )
    assert status == 200, completed
    assert completed["status"] == "completed"
    assert completed["session_rpe"] == 7.0
    assert _scalar(
        ios["path"], "SELECT productivity FROM session_feedback WHERE session_id = ?",
        (workout["workout_id"],),
    ) == 4
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

# --- R7: bounded worker, eligibility and authoritative recovery -------------


@pytest.fixture
def build_spy(monkeypatch):
    """Record every build the dispatcher actually starts."""
    calls = []
    original = ios_plan_worker.build_plan

    def spy(conn, row):
        calls.append(dict(row))
        return original(conn, row)

    monkeypatch.setattr(ios_plan_worker, "build_plan", spy)
    return calls


def _plan_row(ios, issued_plan_id):
    return _row(
        ios["path"],
        "SELECT * FROM ios_issued_plan WHERE issued_plan_id = ?",
        (issued_plan_id,),
    )


def _wait_until(predicate, *, timeout=30.0, message="condition not reached"):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(message)
        time.sleep(0.02)


def _hold_cpu_slot():
    slot = web_server._CPU_JOB_SLOTS
    assert slot.acquire(timeout=5), "CPU slot was not free for the test"
    return slot


def test_superseded_queued_request_never_reaches_the_builder(ios, build_spy):
    token, _ = _paired(ios)
    slot = _hold_cpu_slot()
    try:
        status, first = _issue(
            ios, token, wait=False, body={"settings": {"session_type": "squat"}},
        )
        assert status == 202, first
        status, second = _issue(
            ios, token, wait=False, body={"settings": {"session_type": "hinge"}},
        )
        assert status == 202, second
    finally:
        slot.release()

    state = _wait_for_plan(ios, token)
    assert state["status"] == "ready", state
    assert state["issued_plan_id"] == second["issued_plan_id"]

    superseded = _plan_row(ios, first["issued_plan_id"])
    assert superseded["status"] == "skipped"
    assert superseded["error_code"] == "superseded"
    assert superseded["plan_json"] is None
    # Exactly one build ran: the superseded request never reached the resolver.
    assert len(build_spy) == 1
    assert build_spy[0]["issued_plan_id"] == second["issued_plan_id"]


def test_expired_queued_request_never_reaches_the_builder(ios, build_spy):
    token, _ = _paired(ios)
    slot = _hold_cpu_slot()
    try:
        status, queued = _issue(ios, token, wait=False)
        assert status == 202, queued
        store = db.Store(ios["path"])
        try:
            store.connection.execute(
                "UPDATE ios_issued_plan SET request_expires_at = ? WHERE issued_plan_id = ?",
                ("2000-01-01T00:00:00+00:00", queued["issued_plan_id"]),
            )
        finally:
            store.close()
    finally:
        slot.release()

    row = _wait_until(
        lambda: (
            _plan_row(ios, queued["issued_plan_id"])
            if _plan_row(ios, queued["issued_plan_id"])["status"] != "queued" else None
        ),
        message="the expired request was never terminalised",
    )
    assert row["status"] == "skipped"
    assert row["error_code"] == "expired"
    assert build_spy == []


def test_start_before_the_plan_is_ready_is_a_conflict(ios):
    token, _ = _paired(ios)
    slot = _hold_cpu_slot()
    try:
        status, queued = _issue(ios, token, wait=False)
        assert status == 202, queued
        status, body = _start(ios, token, queued["issued_plan_id"])
        assert status == 409, body
        assert body["code"] == "plan_not_ready"
        assert body["details"]["status"] in {"queued", "building"}
    finally:
        slot.release()

    state = _wait_for_plan(ios, token)
    assert state["status"] == "ready", state
    status, workout = _start(ios, token, state["issued_plan_id"])
    assert status == 200, workout
    assert workout["status"] == "in_progress"


def test_only_one_dispatcher_thread_is_started(ios):
    token, _ = _paired(ios)
    for _ in range(3):
        status, body = _issue(ios, token, wait=False)
        assert status == 202, body
    threads = [
        thread for thread in threading.enumerate()
        if thread.name == ios_plan_worker.DISPATCHER_NAME
    ]
    assert len(threads) == 1
    _wait_for_plan(ios, token)


def test_plans_current_is_authoritative_after_a_lost_response(ios):
    token, _ = _paired(ios)
    # The 202 is "lost": the client only has whatever the authoritative read returns.
    status, queued = _issue(ios, token, wait=False)
    assert status == 202, queued

    state = _wait_for_plan(ios, token)
    assert state["status"] == "ready"
    assert state["issued_plan_id"] == queued["issued_plan_id"]

    # A newer request replaces it; the read must never resurrect the older plan.
    status, replacement = _issue(ios, token, wait=False)
    assert status == 202, replacement
    state = _wait_for_plan(ios, token)
    assert state["issued_plan_id"] == replacement["issued_plan_id"]
    assert state["issued_plan_id"] != queued["issued_plan_id"]


def test_plans_current_reports_none_for_an_expired_ready_plan(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    store = db.Store(ios["path"])
    try:
        store.connection.execute(
            "UPDATE ios_issued_plan SET plan_expires_at = ? WHERE issued_plan_id = ?",
            ("2000-01-01T00:00:00+00:00", issued["issued_plan_id"]),
        )
    finally:
        store.close()
    state = _plan_state(ios, token)
    assert state == {"status": "none"}


def test_ios_execution_events_are_idempotent_and_analysable(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    item = _first_item(issued["plan"])
    status, added = _add_set(ios, token, workout["workout_id"], item)
    assert status == 200, added
    set_id = added["sets"][-1]["set_id"]

    # Give the synthetic session enough elapsed time for a set and rest without inventing
    # future timestamps in the API request.
    workout_start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=60)
    store = db.Store(ios["path"])
    try:
        store.connection.execute(
            "UPDATE workout_session SET started_at = ? WHERE workout_id = ?",
            (workout_start.isoformat(), workout["workout_id"]),
        )
        store.connection.commit()
    finally:
        store.close()

    def stamp(offset):
        return (workout_start + datetime.timedelta(seconds=offset)).isoformat()

    event_ids = [str(uuid.uuid4()) for _ in range(4)]
    events = [
        {"event_id": event_ids[0], "event_type": "set_started",
         "occurred_at": stamp(1), "local_set_id": "local-set-1"},
        {"event_id": event_ids[1], "event_type": "set_completed",
         "occurred_at": stamp(21), "local_set_id": "local-set-1", "set_id": set_id},
        {"event_id": event_ids[2], "event_type": "rest_started",
         "occurred_at": stamp(22), "payload": {"prescribed_rest_s": 60}},
        {"event_id": event_ids[3], "event_type": "rest_completed",
         "occurred_at": stamp(27)},
    ]
    key = uuid.uuid4().hex
    status, result = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/execution-events",
        method="POST", payload={"events": events}, token=token, key=key,
    )
    assert status == 200, result
    assert result["accepted"] == event_ids
    assert result["duplicates"] == []
    assert _scalar(
        ios["path"],
        "SELECT COUNT(*) FROM workout_execution_event WHERE workout_id = ?",
        (workout["workout_id"],),
    ) == 4

    status, replay = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/execution-events",
        method="POST", payload={"events": events}, token=token,
        key=uuid.uuid4().hex,
    )
    assert status == 200, replay
    assert replay["accepted"] == []
    assert replay["duplicates"] == event_ids

    status, analytics = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/execution",
        token=token,
    )
    assert status == 200, analytics
    assert analytics["data_quality"]["event_count"] == 4
    assert analytics["sets"][0]["duration_s"] == 20
    assert analytics["rests"][0]["actual_rest_s"] == 5
    assert analytics["rests"][0]["deviation_s"] == -55
    assert analytics["summary"]["active_lifting_s"] == 20
    assert analytics["summary"]["recorded_recovery_s"] == 5

    status, web_analytics = _request(
        ios["base"], f"/api/history/{workout['workout_id']}/execution"
    )
    assert status == 200, web_analytics
    assert web_analytics["data_quality"]["event_count"] == 4


def test_ios_execution_events_reject_bad_timestamps_atomically(ios):
    token, _ = _paired(ios)
    status, issued = _issue(ios, token)
    assert status == 200, issued
    status, workout = _start(ios, token, issued["issued_plan_id"])
    assert status == 200, workout
    valid = {
        "event_id": str(uuid.uuid4()), "event_type": "set_started",
        "occurred_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "local_set_id": "local-set-1",
    }
    invalid = {
        "event_id": str(uuid.uuid4()), "event_type": "set_started",
        "occurred_at": "2000-01-01T00:00:00+00:00",
        "local_set_id": "local-set-2",
    }
    status, result = _request(
        ios["base"], f"/api/ios/v1/workouts/{workout['workout_id']}/execution-events",
        method="POST", payload={"events": [valid, invalid]}, token=token,
        key=uuid.uuid4().hex,
    )
    assert status == 409, result
    assert _scalar(
        ios["path"],
        "SELECT COUNT(*) FROM workout_execution_event WHERE workout_id = ?",
        (workout["workout_id"],),
    ) == 0

def test_ios_exercise_library_detail_e1rm_and_history(ios):
    token, _ = _paired(ios)
    status, detail = _request(
        ios["base"], "/api/ios/v1/exercises/competition_squat", token=token
    )
    assert status == 200, detail
    assert detail["exercise"]["id"] == "competition_squat"
    assert detail["exercise"]["display"] == "Competition Squat"
    assert detail["properties"]["pattern"] == "squat"
    assert detail["e1rm_applicable"] is True
    assert detail["e1rm"]["exercise_id"] == "competition_squat"
    assert detail["e1rm"]["summary"]["n"] >= 1
    assert detail["e1rm"]["basis"] == "raw_formula_epley_rir"

    # bench_press has no explicit e1rm_applicable field; the endpoint must use the shared
    # structural default rather than treating absence as false.
    status, default_applicable = _request(
        ios["base"], "/api/ios/v1/exercises/bench_press", token=token
    )
    assert status == 200, default_applicable
    assert default_applicable["e1rm_applicable"] is True

    status, history = _request(
        ios["base"], "/api/ios/v1/exercises/competition_squat/history?limit=1",
        token=token,
    )
    assert status == 200, history
    assert history["exercise_id"] == "competition_squat"
    assert history["total"] >= 1
    assert history["sessions"]
    assert history["sessions"][0]["sets"]

    status, not_applicable = _request(
        ios["base"], "/api/ios/v1/exercises/medicine_ball_chest_pass",
        token=token,
    )
    assert status == 200, not_applicable
    assert not_applicable["e1rm_applicable"] is False
    assert not_applicable["e1rm"] is None

    status, missing = _request(
        ios["base"], "/api/ios/v1/exercises/not_an_exercise", token=token
    )
    assert status == 404, missing


def test_top_set_setting_is_validated_and_echoed(ios):
    token, _ = _paired(ios)
    status, accepted = _issue(
        ios, token, wait=False,
        body={"settings": {"session_type": "squat", "top_set": True}},
    )
    assert status == 202, accepted
    assert accepted["settings"]["top_set"] is True

    status, rejected = _issue(
        ios, token, wait=False,
        body={"settings": {"top_set": "yes"}},
    )
    assert status == 400, rejected
    assert rejected["code"] == "validation_failed"
    assert rejected["fields"]["top_set"] == "must be true or false"


def test_top_set_setting_reaches_the_builder(ios, monkeypatch):
    from strength_coach.web import ios_plan_worker

    calls = []
    original = ios_plan_worker.build_prescription

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(ios_plan_worker, "build_prescription", spy)
    token, _ = _paired(ios)
    status, state = _issue(
        ios, token,
        body={"settings": {"session_type": "squat", "top_set": False}},
    )
    assert status == 200, state
    assert calls, "the plan builder was not called"
    assert calls[-1]["top_set_requested"] is False
    assert state["settings"]["top_set"] is False


def test_queue_selection_is_fifo(tmp_path):
    """The dispatcher picks the oldest eligible request, not the newest."""
    from strength_coach.store import ios_workflow

    store = db.Store(tmp_path / "coach.db")
    try:
        conn = store.connection
        # One live row per device, so FIFO needs two devices — the dispatcher serves them in
        # creation order, which is the whole point of the selection query.
        for device in ("device-a", "device-b"):
            conn.execute(
                "INSERT INTO ios_device (device_id, label, token_hash, created_at) "
                "VALUES (?, 'iPhone', ?, '2026-01-01T00:00:00+00:00')",
                (device, "hash-" + device),
            )
        for order, plan_id, device in ((1, "older", "device-a"), (2, "newer", "device-b")):
            conn.execute(
                "INSERT INTO ios_issued_plan "
                "(issued_plan_id, device_id, status, requested_session_type, settings_json, "
                " build_inputs_json, for_date, readiness_json, readiness_ack, created_at, "
                " request_expires_at) "
                "VALUES (?, ?, 'queued', 'auto', '{}', '{}', '2026-01-02', '{}', 0, "
                "        ?, '2999-01-01T00:00:00+00:00')",
                (plan_id, device, f"2026-01-02T0{order}:00:00+00:00"),
            )
        selected = ios_workflow.select_next_request(conn, "2026-01-02T10:00:00+00:00")
        assert selected["issued_plan_id"] == "older"
    finally:
        store.close()
