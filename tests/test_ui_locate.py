"""Locate: the model may phrase the answer, never invent the destination."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from strength_coach.agents.client import LLMResponse
from strength_coach.intelligence.knowledge import retrieval
from strength_coach.intelligence.model.locate import run_locate, verify
from strength_coach.intelligence.model.narrative import daily_tokens_used
from strength_coach.store import db
from strength_coach.web import server

TARGETS = [
    {
        "kind": "panel",
        "title": "Resolver",
        "subtitle": "Settings",
        "view": "settings",
        "target": "settings-resolver-panel",
    },
    {
        "kind": "setting",
        "title": "Dwell target (done exposures)",
        "subtitle": "Settings · Resolver",
        "view": "settings",
        "target": "profile-resolver-dwell-target",
    },
    {
        "kind": "doc",
        "title": "Dwell and rotation",
        "subtitle": "docs/DWELL-AND-ROTATION.md",
        "doc": "docs/DWELL-AND-ROTATION.md",
        "anchor": "",
    },
]


def test_a_known_path_is_verified():
    assert verify("Settings → Resolver.", TARGETS) == (True, None)


def test_an_invented_place_is_rejected():
    verified, warning = verify("Settings → Resolver → Advanced tuning.", TARGETS)
    assert verified is False
    assert "Advanced tuning" in warning


def test_links_are_rejected():
    verified, warning = verify("See [the resolver](#settings).", TARGETS)
    assert verified is False
    assert "link" in warning


def test_documents_are_checked_against_the_targets():
    assert verify("The model is in docs/DWELL-AND-ROTATION.md.", TARGETS)[0] is True
    assert verify("See docs/UNKNOWN.md.", TARGETS)[0] is False


class FakeClient:
    model = "fake-locate"

    def __init__(self, text="Settings → Resolver."):
        self.text = text
        self.prompts = []

    def complete(self, prompt, *, system=None):
        self.prompts.append((prompt, system))
        return LLMResponse(text=self.text, model=self.model, tokens=11)


def test_run_locate_grounds_the_prompt_on_the_targets():
    client = FakeClient()
    result = run_locate(client, "resolver dwell", TARGETS, [])
    prompt, system = client.prompts[0]
    assert "TARGETS" in prompt
    assert '"Resolver"' in prompt
    assert "resolver dwell" in prompt
    assert "never write markdown links" in system
    assert result.answer == "Settings → Resolver."
    assert result.verified is True
    assert result.tokens == 11


@pytest.fixture()
def web(tmp_path, monkeypatch):
    path = tmp_path / "coach.db"
    db.Store(path).close()
    monkeypatch.setattr(
        server, "load_settings", lambda: SimpleNamespace(enabled=True, daily_tokens=150_000)
    )
    monkeypatch.setattr(server, "build_client", lambda settings=None: FakeClient())
    monkeypatch.setattr(retrieval, "search", lambda *args, **kwargs: [])
    httpd = server.create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", path
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _locate(base, payload):
    request = urllib.request.Request(
        base + "/api/intelligence/locate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.loads(response.read().decode())


def test_locate_returns_the_answer_and_the_index_results(web):
    base, path = web
    status, body = _locate(base, {"query": "resolver dwell settings"})
    assert status == 200
    assert body["verified"] is True
    assert body["warning"] is None
    assert body["answer"] == "Settings → Resolver."
    assert body["results"]
    assert any(row["target"] == "settings-resolver-panel" for row in body["results"])
    assert body["tokens"] == 11
    store = db.Store(path)
    try:
        assert daily_tokens_used(store.connection) == 11
    finally:
        store.close()


def test_locate_flags_an_invented_place_but_keeps_the_results(web, monkeypatch):
    base, _path = web
    monkeypatch.setattr(server, "build_client", lambda settings=None: FakeClient("Settings → Mars."))
    status, body = _locate(base, {"query": "resolver dwell settings"})
    assert status == 200
    assert body["verified"] is False
    assert "Mars" in body["warning"]
    assert body["results"]


def test_locate_accepts_live_rendered_surfaces(web):
    base, _path = web
    status, body = _locate(
        base,
        {
            "query": "add a constraint",
            "live": [
                {
                    "title": "Add constraint",
                    "view": "state",
                    "target": "state-forms",
                    "subtitle": "Athlete",
                }
            ],
        },
    )
    assert status == 200
    assert body["results"][0]["target"] == "state-forms"
    assert body["results"][0]["title"] == "Add constraint"


def test_locate_requires_text(web):
    base, _path = web
    with pytest.raises(urllib.error.HTTPError) as failure:
        _locate(base, {"query": "   "})
    assert failure.value.code == 400


def test_locate_rejects_an_overlong_query(web):
    base, _path = web
    with pytest.raises(urllib.error.HTTPError) as failure:
        _locate(base, {"query": "x" * 201})
    assert failure.value.code == 400


def test_locate_needs_a_configured_model(web, monkeypatch):
    base, _path = web
    monkeypatch.setattr(
        server, "load_settings", lambda: SimpleNamespace(enabled=False, daily_tokens=150_000)
    )
    with pytest.raises(urllib.error.HTTPError) as failure:
        _locate(base, {"query": "dwell"})
    assert failure.value.code == 400
