"""Web chat: token accounting must reach the daily budget."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from intelligence_support import enabled_config

from strength_coach.agents.client import LLMResponse
from strength_coach.intelligence import config as intelligence_config
from strength_coach.intelligence.model.narrative import daily_tokens_used
from strength_coach.store import db
from strength_coach.web import server


class FakeClient:
    model = "fake-chat"

    def complete(self, prompt, *, system=None):
        return LLMResponse(text="Two sessions this week.", model=self.model, tokens=42)


@pytest.fixture()
def web(tmp_path: Path, monkeypatch):
    path = tmp_path / "coach.db"
    db.Store(path).close()
    monkeypatch.setattr(
        server, "load_settings", lambda: SimpleNamespace(enabled=True, daily_tokens=150_000)
    )
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


def test_chat_tokens_increase_the_daily_budget(web):
    base, path = web
    request = urllib.request.Request(
        base + "/api/intelligence/chat",
        data=json.dumps({"messages": [{"role": "user", "content": "How was this week?"}]}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode())
    assert response.status == 200
    assert body["tokens"] == 42
    assert body["raw"]["model"] == "fake-chat"
    assert body["raw"]["request"]["messages"][-1]["content"].startswith(
        "Answer the latest athlete message"
    )
    assert body["raw"]["response"]["usage"]["total_tokens"] == 42
    assert "Authorization" not in json.dumps(body["raw"])
    store = db.Store(path)
    try:
        assert daily_tokens_used(store.connection) == 42
        row = store.connection.execute("SELECT llm_tokens FROM run").fetchone()
        assert row["llm_tokens"] == 42
    finally:
        store.close()
