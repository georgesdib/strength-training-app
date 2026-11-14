"""HTTP transport: authentication, host protection, body limits and token handling."""

from __future__ import annotations

import dataclasses as dc
import http.client
import json
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from conftest import make_readiness, make_training
from intelligence_support import enabled_config

from strength_coach.intelligence.mcp.app import build_app
from strength_coach.intelligence.tokens import TokenStore
from strength_coach.store import db, importer

DISCOVER = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "server/discover",
    "params": {
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    },
}


def _seed(path: Path) -> None:
    store = db.Store(path)
    training = make_training([
        {"Date": "2026-10-19", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2026-11-02", "Exercise": "Trap Bar Deadlift", "Weight_Used": "160",
         "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{}])
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
    finally:
        store.close()


def _start(app):
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.01)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, port


def _stop(server, thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)


def _post(port: int, payload: dict | bytes, *, token: str | None = None,
          host: str = "127.0.0.1"):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Host": f"{host}:{port}",
        # Revision 2026-07-28 requires these on every modern POST.
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "server/discover",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request("POST", "/mcp", body=body, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.fixture(scope="module")
def running(tmp_path_factory):
    root = tmp_path_factory.mktemp("mcp-http")
    db_path = root / "coach.db"
    _seed(db_path)
    store = TokenStore.load(root / "intelligence.local.yaml")
    _, token = store.create("Test laptop")
    revoked_client, revoked_token = store.create("Old laptop")
    store.revoke(revoked_client.client_id)
    app = build_app(db_path=db_path, config=enabled_config(), store=store)
    server, thread, port = _start(app)
    try:
        yield {"port": port, "token": token, "revoked": revoked_token}
    finally:
        _stop(server, thread)


def test_missing_token_is_rejected_before_the_protocol(running):
    status, headers, body = _post(running["port"], DISCOVER)
    assert status == 401
    assert "www-authenticate" in headers
    assert b"invalid_token" in body


def test_invalid_token_is_rejected(running):
    status, _, _ = _post(running["port"], DISCOVER, token="not-a-token")
    assert status == 401


def test_revoked_token_is_forbidden(running):
    status, _, body = _post(running["port"], DISCOVER, token=running["revoked"])
    assert status == 403
    assert b"revoked" in body


def test_valid_token_reaches_the_protocol(running):
    status, _, body = _post(running["port"], DISCOVER, token=running["token"])
    assert status == 200
    payload = json.loads(body)
    result = payload["result"]
    assert result["resultType"] == "complete"
    assert "tools" in result["capabilities"]
    assert "strength-intelligence" in body.decode("utf-8")
    assert "2026-07-28" in body.decode("utf-8")


def test_foreign_host_is_rejected(running):
    status, _, _ = _post(
        running["port"], DISCOVER, token=running["token"], host="evil.example"
    )
    assert status == 421


def test_oversized_body_is_rejected_before_parsing(tmp_path):
    db_path = tmp_path / "coach.db"
    _seed(db_path)
    store = TokenStore.load(tmp_path / "intelligence.local.yaml")
    _, token = store.create("Laptop")
    config = dc.replace(enabled_config(), max_request_body_bytes=1024)
    app = build_app(db_path=db_path, config=config, store=store)
    server, thread, port = _start(app)
    try:
        status, _, _ = _post(port, b"{" + b"x" * 4000, token=token)
        assert status == 413
        # Authentication runs first: an unauthenticated oversized request is 401, not 413,
        # so the size limit cannot be used as an unauthenticated probe.
        unauthenticated, _, _ = _post(port, b"{" + b"x" * 4000)
        assert unauthenticated == 401
    finally:
        _stop(server, thread)


def test_rate_limit_is_per_client(tmp_path):
    db_path = tmp_path / "coach.db"
    _seed(db_path)
    store = TokenStore.load(tmp_path / "intelligence.local.yaml")
    _, token = store.create("Laptop")
    config = dc.replace(enabled_config(), rate_limit_per_minute=1)
    app = build_app(db_path=db_path, config=config, store=store)
    server, thread, port = _start(app)
    try:
        first, _, _ = _post(port, DISCOVER, token=token)
        second, headers, _ = _post(port, DISCOVER, token=token)
        assert first == 200
        assert second == 429
        assert headers.get("retry-after") == "60"
    finally:
        _stop(server, thread)
