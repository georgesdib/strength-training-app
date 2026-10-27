"""The LLM layer: configuration, the null client, and narrative containment.

The claims under test:

* an unconfigured checkout runs with NullLLM and loses only the narrative;
* a failing model call never loses a deterministic artifact, and is recorded;
* configuration precedence is environment > file > defaults, and keys are never printed.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from strength_coach.agents import (
    LLMConfigError,
    LLMError,
    LLMResponse,
    LLMSettings,
    NullLLM,
    OpenAICompatibleClient,
    build_client,
    describe,
    explain_critique,
    load_settings,
)
from strength_coach.agents.narrative import SYSTEM_PROMPT, critique_prompt
from strength_coach.critique.rubric import Critique, RubricItem
from strength_coach.store import db
from strength_coach.trace import RunTrace

# --- configuration ---------------------------------------------------------


def test_unconfigured_defaults_to_null(tmp_path):
    settings = load_settings(tmp_path / "missing.toml", env={})
    assert settings.provider == "null"
    assert settings.enabled is False
    assert isinstance(build_client(settings), NullLLM)


def test_file_settings_are_read(tmp_path):
    path = tmp_path / "llm.toml"
    path.write_text(
        '[llm]\nprovider = "openai_compatible"\nmodel = "m1"\n'
        'base_url = "http://localhost:1234/v1"\napi_key = "sk-secret-value"\n',
        encoding="utf-8",
    )
    settings = load_settings(path, env={})
    assert settings.enabled is True
    assert settings.model == "m1"
    assert str(path) in settings.source


def test_environment_overrides_the_file(tmp_path):
    path = tmp_path / "llm.toml"
    path.write_text('[llm]\nprovider = "openai_compatible"\nmodel = "file-model"\n',
                    encoding="utf-8")
    settings = load_settings(
        path,
        env={
            "STRENGTH_COACH_LLM_MODEL": "env-model",
            "STRENGTH_COACH_LLM_BASE_URL": "http://env/v1",
            "STRENGTH_COACH_LLM_API_KEY": "sk-env-key",
        },
    )
    assert settings.model == "env-model"
    assert settings.base_url == "http://env/v1"
    assert "environment" in settings.source


def test_unknown_provider_is_rejected(tmp_path):
    path = tmp_path / "llm.toml"
    path.write_text('[llm]\nprovider = "mystery"\n', encoding="utf-8")
    with pytest.raises(LLMConfigError, match="unknown llm provider"):
        load_settings(path, env={})


def test_api_key_is_masked_in_diagnostics():
    settings = LLMSettings(api_key="sk-1234567890abcdef")
    assert describe(settings)["api_key"] == "sk-1…cdef"
    assert "1234567890" not in json.dumps(describe(settings))


def test_null_provider_stays_disabled_even_with_a_model():
    client = build_client(LLMSettings(provider="null", model="m"))
    assert isinstance(client, NullLLM)


def test_defaults_point_at_deepseek_once_a_provider_is_chosen():
    client = build_client(LLMSettings(provider="openai_compatible", api_key="sk-test"))
    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "https://api.deepseek.com/v1"
    assert client.model == "deepseek-chat"


def test_provider_and_key_from_the_environment_are_enough(tmp_path):
    settings = load_settings(
        tmp_path / "missing.toml",
        env={
            "STRENGTH_COACH_LLM_PROVIDER": "openai_compatible",
            "STRENGTH_COACH_LLM_API_KEY": "sk-test",
        },
    )
    assert settings.enabled is True
    assert settings.model == "deepseek-chat"
    assert settings.base_url == "https://api.deepseek.com/v1"


# --- null client and containment ------------------------------------------


class FakeClient:
    model = "fake-1"

    def __init__(self, text="solid session", tokens=17):
        self.available = True
        self.text = text
        self.tokens = tokens
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt, *, system=None):
        self.calls.append((prompt, system))
        return LLMResponse(text=self.text, model=self.model, tokens=self.tokens)


class FailingClient(FakeClient):
    def complete(self, prompt, *, system=None):
        raise LLMError("connection refused")


def test_null_llm_produces_no_narrative_and_no_event():
    with db.Store(":memory:") as store:
        with RunTrace.start(store.connection, input_hash="h") as trace:
            critique = _critique()
            text = explain_critique(NullLLM(), critique, _facts(), trace)
        assert text is None
        assert trace.events == []
        assert store.connection.execute("SELECT COUNT(*) c FROM run_event").fetchone()["c"] == 0


def test_narrative_is_recorded_as_an_event_with_tokens():
    client = FakeClient()
    with db.Store(":memory:") as store:
        with RunTrace.start(store.connection, input_hash="h") as trace:
            text = explain_critique(client, _critique(), _facts(), trace)
        assert text == "solid session"
        assert trace.llm_tokens == 17
        row = store.connection.execute(
            "SELECT payload FROM run_event WHERE kind = 'llm_output'"
        ).fetchone()
        payload = json.loads(row["payload"])
        assert payload["status"] == "ok"
        assert payload["model"] == "fake-1"
        assert payload["text"] == "solid session"
        assert store.connection.execute(
            "SELECT llm_tokens FROM run WHERE run_id = ?", (trace.run_id,)
        ).fetchone()["llm_tokens"] == 17


def test_a_failing_model_is_recorded_and_does_not_raise():
    with db.Store(":memory:") as store:
        with RunTrace.start(store.connection, input_hash="h") as trace:
            text = explain_critique(FailingClient(), _critique(), _facts(), trace)
            trace.finish(status="llm_failed")
        assert text is None
        payload = json.loads(store.connection.execute(
            "SELECT payload FROM run_event WHERE kind = 'llm_output'"
        ).fetchone()["payload"])
        assert payload["status"] == "error"
        assert "connection refused" in payload["error"]
        assert store.connection.execute(
            "SELECT status FROM run WHERE run_id = ?", (trace.run_id,)
        ).fetchone()["status"] == "llm_failed"


# --- prompts ---------------------------------------------------------------


def test_prompt_carries_the_facts_and_forbids_arithmetic():
    prompt = critique_prompt(_critique(), _facts())
    assert "PRG-RIR-001" in prompt
    assert "2026-10-05" in prompt
    assert "do not" in SYSTEM_PROMPT.lower() or "Do not" in SYSTEM_PROMPT
    assert "calculate" in SYSTEM_PROMPT.lower()


def test_unmeasurable_items_are_described_not_scored():
    prompt = critique_prompt(_critique(), _facts())
    assert '"measurable": false' in prompt


# --- the HTTP adapter ------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    received: dict = {}

    def do_POST(self):  # noqa: N802 - stdlib naming
        length = int(self.headers["Content-Length"])
        _Handler.received = {
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(length)),
        }
        body = json.dumps({
            "choices": [{"message": {"content": "ready"}}],
            "usage": {"total_tokens": 7},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the test server
        pass


def test_openai_client_speaks_chat_completions():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAICompatibleClient(
            model="test-model",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="sk-test",
        )
        response = client.complete("hello", system="be brief")
    finally:
        server.shutdown()

    assert response.text == "ready"
    assert response.tokens == 7
    sent = _Handler.received
    assert sent["path"] == "/v1/chat/completions"
    assert sent["auth"] == "Bearer sk-test"
    assert sent["body"]["model"] == "test-model"
    assert sent["body"]["messages"][0] == {"role": "system", "content": "be brief"}
    assert sent["body"]["messages"][-1] == {"role": "user", "content": "hello"}


def test_bad_response_shape_is_an_llm_error():
    client = OpenAICompatibleClient(
        model="m", base_url="http://example.invalid/v1",
        transport=lambda *args, **kwargs: json.dumps({"nope": True}),
    )
    with pytest.raises(LLMError, match="unexpected response shape"):
        client.complete("hi")


def test_empty_completion_is_rejected():
    client = OpenAICompatibleClient(
        model="m", base_url="http://example.invalid/v1",
        transport=lambda *args, **kwargs: json.dumps(
            {"choices": [{"message": {"content": "   "}}]}
        ),
    )
    with pytest.raises(LLMError, match="empty response"):
        client.complete("hi")


# --- fixtures --------------------------------------------------------------


def _item(key: str, score: float | None, measurable: bool, rules: tuple[str, ...] = ()):
    return RubricItem(
        key=key,
        weight=0.3,
        score=score,
        measurable=measurable,
        evidence_refs=("set:2026-10-05/1",) if measurable else (),
        rule_ids=rules,
        detail="detail",
    )


def _critique() -> Critique:
    return Critique(
        session_id="2026-10-05",
        facts_hash="abc",
        items=(
            _item("RIR_ADHERENCE", 0.89, True, ("PRG-RIR-001",)),
            _item("SESSION_DURATION", None, False),
        ),
        narrative="deterministic",
    )


def _facts():
    return SimpleNamespace(session_id="2026-10-05", occurred_on="2026-10-05", session_type="hinge")
