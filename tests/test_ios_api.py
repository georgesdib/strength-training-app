"""iOS Phase 1: one-use pairing, hashed bearer credentials and read-only views.

These tests use the real threaded HTTP server over a temporary SQLite database, so they
exercise the same dispatch, body reader and error envelope the phone sees. No test touches
the owner's live database.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import threading
import urllib.error
import urllib.request

import pytest
from conftest import make_readiness, make_training

from strength_coach import cli, history
from strength_coach.features import progress as progress_feature
from strength_coach.store import db, importer, ios_devices
from strength_coach.utils import ios_credentials
from strength_coach.web import server as web_server
from strength_coach.web.server import create_server

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Competition Squat", "Weight_Used": "140",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-02", "Exercise": "Competition Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
]


@pytest.fixture
def ios(tmp_path):
    path = tmp_path / "coach.db"
    today = datetime.date.today().isoformat()
    training = make_training(ROWS)
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


def _request(base, path, *, method="GET", payload=None, token=None, headers=None):
    merged = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        merged["Content-Type"] = "application/json"
    if token is not None:
        merged["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base + path, data=data, headers=merged, method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"raw": raw}
        return exc.code, body


def _mint(path, *, ttl=ios_credentials.DEFAULT_TTL_SECONDS):
    store = db.Store(path)
    try:
        return ios_devices.mint_pairing_code(store.connection, ttl_seconds=ttl)
    finally:
        store.close()


def _pair(base, code, label=None):
    payload = {"code": code}
    if label is not None:
        payload["label"] = label
    return _request(base, "/api/ios/v1/pair", method="POST", payload=payload)


def _paired(ios):
    minted = _mint(ios["path"])
    status, body = _pair(ios["base"], minted["code"])
    assert status == 200, body
    return body["token"], body["device"]


def _one(path, sql, params=()):
    store = db.Store(path)
    try:
        return store.connection.execute(sql, params).fetchone()
    finally:
        store.close()


def _scalar(path, sql, params=()):
    row = _one(path, sql, params)
    return row[0] if row is not None else None


def _device_count(path) -> int:
    return int(_scalar(path, "SELECT COUNT(*) FROM ios_device") or 0)


def _wrong_code(code: str, step: int = 1) -> str:
    return f"{(int(code) + step) % 10 ** 8:08d}"


# --- pairing ---------------------------------------------------------------


def test_pair_creates_one_device_and_the_token_authenticates(ios):
    minted = _mint(ios["path"])
    status, body = _pair(ios["base"], minted["code"], "  Gym iPhone  ")
    assert status == 200, body
    assert body["api_version"] == "1"
    assert body["device"]["label"] == "Gym iPhone"
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", body["token"])
    assert body["server_date"] == ios["today"]
    assert isinstance(body["utc_offset_minutes"], int)
    assert body["server_timezone"]

    row = _one(ios["path"], "SELECT * FROM ios_device")
    assert row["token_hash"] == ios_credentials.hash_token(body["token"])
    assert body["token"] not in dict(row).values()
    assert _device_count(ios["path"]) == 1

    status, bootstrap = _request(
        ios["base"], "/api/ios/v1/bootstrap", token=body["token"],
    )
    assert status == 200
    assert bootstrap["api_version"] == "1"


def test_pair_rejects_wrong_code_and_the_five_attempt_limit_is_real(ios):
    minted = _mint(ios["path"])
    for step in range(1, 6):
        status, body = _pair(ios["base"], _wrong_code(minted["code"], step))
        assert status == 401, body
        assert body["error"] == "wrong pairing code"
    row = _one(ios["path"], "SELECT attempts FROM ios_pairing_code")
    assert row["attempts"] == ios_credentials.MAX_ATTEMPTS
    assert _device_count(ios["path"]) == 0

    status, body = _pair(ios["base"], minted["code"])
    assert status == 429, body
    assert _device_count(ios["path"]) == 0


def test_pair_rejects_malformed_code(ios):
    _mint(ios["path"])
    for malformed in ("", "1234", "123456789", "abcdefgh", "1234 5678 9", 1234567):
        status, body = _pair(ios["base"], malformed)
        assert status == 400, (malformed, body)
        assert "code" in body["fields"], (malformed, body)
    assert _device_count(ios["path"]) == 0
    row = _one(ios["path"], "SELECT attempts FROM ios_pairing_code")
    assert row["attempts"] == 0


def test_pair_rejects_expired_code(ios):
    minted = _mint(ios["path"])
    expired = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1))
    store = db.Store(ios["path"])
    try:
        store.connection.execute(
            "UPDATE ios_pairing_code SET expires_at = ?",
            (expired.isoformat(timespec="seconds"),),
        )
    finally:
        store.close()
    status, body = _pair(ios["base"], minted["code"])
    assert status == 410, body
    assert body["error"] == "pairing code expired"
    assert _device_count(ios["path"]) == 0


def test_pair_rejects_used_code_and_single_use(ios):
    minted = _mint(ios["path"])
    status, first = _pair(ios["base"], minted["code"])
    assert status == 200
    status, body = _pair(ios["base"], minted["code"])
    assert status == 410, body
    assert body["error"] == "pairing code already used"
    assert _device_count(ios["path"]) == 1

    row = _one(ios["path"], "SELECT used_at FROM ios_pairing_code")
    assert row["used_at"] is not None
    assert first["device"]["device_id"] == _scalar(
        ios["path"], "SELECT device_id FROM ios_device"
    )


def test_pair_rejects_exhausted_attempts(ios):
    minted = _mint(ios["path"])
    store = db.Store(ios["path"])
    try:
        store.connection.execute(
            "UPDATE ios_pairing_code SET attempts = ?", (ios_credentials.MAX_ATTEMPTS,)
        )
    finally:
        store.close()
    status, body = _pair(ios["base"], minted["code"])
    assert status == 429, body
    assert body["error"] == "pairing attempts exhausted"
    assert _device_count(ios["path"]) == 0


def test_pair_validates_and_trims_the_label(ios):
    minted = _mint(ios["path"])
    for bad in ("", "x" * 41, " "):
        status, body = _pair(ios["base"], minted["code"], bad)
        assert status == 400, (bad, body)
        assert "label" in body["fields"], (bad, body)
    assert _device_count(ios["path"]) == 0

    status, body = _pair(ios["base"], minted["code"])
    assert status == 200
    assert body["device"]["label"] == "iPhone"


# --- authentication --------------------------------------------------------


def test_authentication_missing_unknown_and_revoked(ios):
    for path in ("/api/ios/v1/bootstrap", "/api/ios/v1/today",
                 "/api/ios/v1/history", "/api/ios/v1/progress"):
        status, body = _request(ios["base"], path)
        assert status == 401, (path, body)
        assert body["error"] == "authentication required"

    status, body = _request(
        ios["base"], "/api/ios/v1/bootstrap",
        headers={"Authorization": "Token not-a-bearer"},
    )
    assert status == 401 and body["error"] == "authentication required"

    status, body = _request(
        ios["base"], "/api/ios/v1/bootstrap", token="unknown-token",
    )
    assert status == 401 and body["error"] == "authentication required"

    token, device = _paired(ios)
    status, _ = _request(ios["base"], "/api/ios/v1/does-not-exist")
    assert status == 401
    status, _ = _request(
        ios["base"], "/api/ios/v1/does-not-exist", token=token,
    )
    assert status == 404

    status, _ = _request(
        ios["base"], "/api/ios/v1/does-not-exist", method="POST",
        payload={"x": 1}, token=token,
    )
    assert status == 404
    status, _ = _request(
        ios["base"], "/api/ios/v1/does-not-exist", method="POST", payload={"x": 1},
    )
    assert status == 401

    store = db.Store(ios["path"])
    try:
        ios_devices.revoke_device(store.connection, device["device_id"])
    finally:
        store.close()
    status, body = _request(ios["base"], "/api/ios/v1/bootstrap", token=token)
    assert status == 403, body
    assert body["error"] == "device revoked"


def test_last_seen_updates_at_most_once_per_60_seconds(ios):
    token, device = _paired(ios)
    status, _ = _request(ios["base"], "/api/ios/v1/bootstrap", token=token)
    assert status == 200
    first = _scalar(
        ios["path"], "SELECT last_seen_at FROM ios_device WHERE device_id = ?",
        (device["device_id"],),
    )
    assert first is not None

    status, _ = _request(ios["base"], "/api/ios/v1/bootstrap", token=token)
    assert status == 200
    second = _scalar(
        ios["path"], "SELECT last_seen_at FROM ios_device WHERE device_id = ?",
        (device["device_id"],),
    )
    assert second == first

    stale = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=120)
    store = db.Store(ios["path"])
    try:
        store.connection.execute(
            "UPDATE ios_device SET last_seen_at = ? WHERE device_id = ?",
            (stale.isoformat(timespec="seconds"), device["device_id"]),
        )
    finally:
        store.close()
    status, _ = _request(ios["base"], "/api/ios/v1/bootstrap", token=token)
    assert status == 200
    third = _scalar(
        ios["path"], "SELECT last_seen_at FROM ios_device WHERE device_id = ?",
        (device["device_id"],),
    )
    assert third != stale.isoformat(timespec="seconds")


# --- read payloads ---------------------------------------------------------


def test_bootstrap_contract(ios):
    token, _ = _paired(ios)
    status, body = _request(ios["base"], "/api/ios/v1/bootstrap", token=token)
    assert status == 200
    assert set(body) == {
        "api_version", "server_date", "server_time", "utc_offset_minutes",
        "server_timezone", "capabilities",
    }
    assert body["api_version"] == "1"
    assert body["server_date"] == ios["today"]
    parsed = datetime.datetime.fromisoformat(body["server_time"])
    local = datetime.datetime.now().astimezone()
    assert parsed.utcoffset() == local.utcoffset()
    assert body["utc_offset_minutes"] == int(
        (local.utcoffset() or datetime.timedelta(0)).total_seconds() // 60
    )
    assert body["server_timezone"]
    assert body["capabilities"] == {
        "readiness": True,
        "readiness_write": True,
        "prescription": True,
        "workout_write": True,
        "healthkit": False,
        "offline": False,
    }


def test_today_matches_the_existing_readiness_payload(ios):
    token, _ = _paired(ios)
    status, today = _request(ios["base"], "/api/ios/v1/today", token=token)
    assert status == 200
    assert today["date"] == ios["today"]
    assert today["active_workout"] is None

    status, expected = _request(ios["base"], f"/api/readiness/{ios['today']}")
    assert status == 200
    assert today["readiness"] == expected
    assert today["readiness_score"] == today["readiness"]["score"]
    assert today["readiness_score"]["status"] in {"ready", "insufficient", "unknown"}


def test_history_matches_the_existing_service(ios):
    token, _ = _paired(ios)

    store = db.Store(ios["path"])
    try:
        expected_default = history.list_sessions(store.connection)
        expected_page = history.list_sessions(store.connection, limit=1, offset=1)
        expected_window = history.list_sessions(
            store.connection, limit=50, offset=0,
            start="2024-01-01", end="2024-01-01",
        )
    finally:
        store.close()

    status, body = _request(ios["base"], "/api/ios/v1/history", token=token)
    assert status == 200
    assert body == expected_default
    assert body["limit"] == 50 and body["offset"] == 0
    assert body["total"] == 2

    status, body = _request(
        ios["base"], "/api/ios/v1/history?limit=1&offset=1", token=token,
    )
    assert status == 200
    assert body == expected_page

    status, body = _request(
        ios["base"],
        "/api/ios/v1/history?start=2024-01-01&end=2024-01-01",
        token=token,
    )
    assert status == 200
    assert body == expected_window


def test_history_rejects_invalid_paging_and_dates(ios):
    token, _ = _paired(ios)
    cases = {
        "limit=0": "limit",
        "limit=101": "limit",
        "limit=abc": "limit",
        "limit=": "limit",
        "offset=-1": "offset",
        "offset=abc": "offset",
        "start=2024-13-01": "start",
        "end=nope": "end",
    }
    for query, field in cases.items():
        status, body = _request(
            ios["base"], f"/api/ios/v1/history?{query}", token=token,
        )
        assert status == 400, (query, body)
        assert field in body["fields"], (query, body)


def test_progress_matches_the_existing_service(ios):
    token, _ = _paired(ios)
    store = db.Store(ios["path"])
    try:
        expected_one = progress_feature.dashboard(
            store.connection, ios["today"], weeks=1
        )
        expected_default = progress_feature.dashboard(
            store.connection, ios["today"], weeks=8
        )
    finally:
        store.close()

    status, body = _request(
        ios["base"], f"/api/ios/v1/progress?weeks=1&date={ios['today']}",
        token=token,
    )
    assert status == 200
    assert body == expected_one

    status, body = _request(
        ios["base"], f"/api/ios/v1/progress?date={ios['today']}", token=token,
    )
    assert status == 200
    assert body == expected_default


def test_progress_rejects_invalid_weeks_and_date(ios):
    token, _ = _paired(ios)
    for query, field in {
        "weeks=0": "weeks",
        "weeks=53": "weeks",
        "weeks=abc": "weeks",
        "date=2024-13-01": "date",
    }.items():
        status, body = _request(
            ios["base"], f"/api/ios/v1/progress?{query}", token=token,
        )
        assert status == 400, (query, body)
        assert field in body["fields"], (query, body)


# --- secrets and regression ------------------------------------------------


def test_no_code_or_token_appears_in_logs_or_error_bodies(ios, caplog):
    caplog.set_level(logging.INFO)
    web_server._LOG_BUFFER.clear()

    minted = _mint(ios["path"])
    status, paired = _pair(ios["base"], minted["code"])
    assert status == 200
    token = paired["token"]

    status, wrong = _pair(ios["base"], _wrong_code(minted["code"]))
    assert status == 401
    store = db.Store(ios["path"])
    try:
        ios_devices.revoke_device(
            store.connection, paired["device"]["device_id"]
        )
    finally:
        store.close()
    status, revoked = _request(ios["base"], "/api/ios/v1/bootstrap", token=token)
    assert status == 403

    error_bodies = json.dumps(wrong) + json.dumps(revoked)
    with web_server._LOG_LOCK:
        buffered = "\n".join(
            f"{entry['level']} {entry['logger']} {entry['message']}"
            for entry in web_server._LOG_BUFFER
        )
    status, logs_page = _request(ios["base"], "/api/logs?limit=500")
    assert status == 200
    seen = "\n".join((caplog.text, buffered, json.dumps(logs_page)))

    assert minted["code"] not in error_bodies
    assert token not in error_bodies
    assert minted["code"] not in seen
    assert token not in seen


def test_existing_routes_remain_unauthenticated(ios):
    for path in (
        "/api/overview",
        "/api/history",
        "/api/progress",
        f"/api/readiness/{ios['today']}",
    ):
        status, _ = _request(ios["base"], path)
        assert status == 200, path


# --- CLI -------------------------------------------------------------------


def test_cli_ios_pair_prints_one_code_and_stores_no_plaintext(tmp_path, capsys):
    path = tmp_path / "cli.db"
    code = cli.main([
        "--db", str(path), "ios", "pair", "--label", "Test iPhone", "--ttl", "120",
    ])
    assert code == 0
    out = capsys.readouterr().out
    matches = re.findall(r"pairing code:\s*(\d{4})\s+(\d{4})", out)
    assert len(matches) == 1, out
    pairing_code = "".join(matches[0])
    assert "expires at:" in out
    assert "device label: Test iPhone" in out

    row = _one(path, "SELECT * FROM ios_pairing_code")
    assert row["code_hash"] == ios_credentials.hash_code(pairing_code)
    assert row["attempts"] == 0
    assert row["used_at"] is None
    assert row["expires_at"] > row["created_at"]

    raw = b""
    for suffix in ("", "-wal", "-shm"):
        candidate = path.with_name(path.name + suffix)
        if candidate.exists():
            raw += candidate.read_bytes()
    assert pairing_code.encode() not in raw
    assert pairing_code[:4].encode() + b" " + pairing_code[4:].encode() not in raw


def test_cli_ios_pair_validates_ttl_and_label(tmp_path, capsys):
    path = tmp_path / "cli.db"
    assert cli.main(["--db", str(path), "ios", "pair", "--ttl", "59"]) == 2
    assert "between 60 and 3600" in capsys.readouterr().out
    assert cli.main(["--db", str(path), "ios", "pair", "--ttl", "3601"]) == 2
    assert "between 60 and 3600" in capsys.readouterr().out
    assert cli.main(["--db", str(path), "ios", "pair", "--label", ""]) == 2
    assert "label must be" in capsys.readouterr().out
    assert int(_scalar(path, "SELECT COUNT(*) FROM ios_pairing_code")) == 0


def test_cli_ios_devices_and_revoke(tmp_path, capsys):
    path = tmp_path / "cli.db"
    store = db.Store(path)
    try:
        minted = ios_devices.mint_pairing_code(store.connection, ttl_seconds=300)
        paired = ios_devices.pair(
            store.connection, code=minted["code"], label="Kitchen iPhone",
        )
    finally:
        store.close()
    device_id = paired["device"]["device_id"]

    assert cli.main(["--db", str(path), "ios", "devices"]) == 0
    out = capsys.readouterr().out
    assert device_id in out
    assert "Kitchen iPhone" in out

    assert cli.main(["--db", str(path), "ios", "revoke", device_id]) == 0
    out = capsys.readouterr().out
    assert "revoked:" in out
    revoked_at = _scalar(
        path, "SELECT revoked_at FROM ios_device WHERE device_id = ?", (device_id,)
    )
    assert revoked_at is not None

    assert cli.main(["--db", str(path), "ios", "revoke", device_id]) == 0
    out = capsys.readouterr().out
    assert "already revoked:" in out
    assert _scalar(
        path, "SELECT revoked_at FROM ios_device WHERE device_id = ?", (device_id,)
    ) == revoked_at

    assert cli.main(["--db", str(path), "ios", "revoke", "missing"]) == 2
    assert "unknown device" in capsys.readouterr().out


def test_cli_pair_end_to_end_with_the_running_server(ios, capsys):
    assert cli.main(["--db", str(ios["path"]), "ios", "pair"]) == 0
    out = capsys.readouterr().out
    match = re.search(r"pairing code:\s*(\d{4})\s+(\d{4})", out)
    assert match
    code = "".join(match.groups())
    status, body = _pair(ios["base"], code)
    assert status == 200, body
    assert body["device"]["label"] == "iPhone"
    assert _device_count(ios["path"]) == 1
