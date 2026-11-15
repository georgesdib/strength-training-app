"""Web Narrate route: one read-only capability, no freeform chat."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from intelligence_support import enabled_config

from strength_coach.agents.client import LLMResponse
from strength_coach.intelligence import config as intelligence_config
from strength_coach.store import db
from strength_coach.web import server


class FakeClient:
    model = "fake-model"

    @property
    def available(self):
        return True

    def complete(self, prompt, *, system=None):
        return LLMResponse(
            text=json.dumps(
                {
                    "headline": "No training data",
                    "observations": ["No training observations are available."],
                    "limitations": [],
                }
            ),
            model=self.model,
            tokens=7,
        )


@pytest.fixture()
def web(tmp_path: Path, monkeypatch):
    path = tmp_path / "coach.db"
    db.Store(path).close()
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(server, "build_client", lambda settings=None: FakeClient())
    monkeypatch.setattr(
        intelligence_config, "load_config", lambda path=None: enabled_config()
    )
    httpd = server.create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", path
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post(base, body):
    request = urllib.request.Request(
        base + "/api/intelligence/narrate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def test_narrate_route_returns_narrative_and_traces(web):
    base, path = web
    status, body = _post(base, {"capability": "get_weekly_review", "payload": {}})
    assert status == 200, body
    assert body["headline"] == "No training data"
    assert body["model"] == "fake-model"
    store = db.Store(path)
    try:
        row = store.connection.execute("SELECT COUNT(*) AS n FROM run").fetchone()
        assert row["n"] == 1
        event = store.connection.execute(
            "SELECT kind FROM run_event ORDER BY seq"
        ).fetchall()
        assert [item["kind"] for item in event] == ["input", "llm_output"]
    finally:
        store.close()


def test_narrate_rejects_non_object_payload(web):
    base, _ = web
    status, body = _post(base, {"capability": "get_weekly_review", "payload": []})
    assert status == 400
    assert "payload" in body["error"]


def test_narrate_requires_a_capability(web):
    base, _ = web
    status, body = _post(base, {"payload": {}})
    assert status == 400
    assert "capability" in body["error"]
