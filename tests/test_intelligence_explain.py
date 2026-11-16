"""Explain retrieval, citation checks and web endpoint."""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from intelligence_support import enabled_config

from strength_coach.agents.client import LLMResponse
from strength_coach.intelligence import config as intelligence_config
from strength_coach.intelligence.knowledge.allowlist import load_config
from strength_coach.intelligence.knowledge.citations import extract
from strength_coach.intelligence.knowledge.explain import run_explain
from strength_coach.intelligence.knowledge.index import build
from strength_coach.intelligence.knowledge.retrieval import query_kind, search
from strength_coach.store import db
from strength_coach.web import server


def _fixture(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "private").mkdir()
    (root / "docs" / "readiness.md").write_text(
        "# Readiness\n\nThe score is a composite of readiness inputs.\n", encoding="utf-8"
    )
    (root / "src" / "score.py").write_text(
        "def calculate_score():\n    return 1\n", encoding="utf-8"
    )
    (root / "tests" / "test_score.py").write_text(
        "def test_score():\n    assert True\n", encoding="utf-8"
    )
    (root / "private" / "notes.md").write_text(
        "# Private notes\n\nMy private readiness notes.\n", encoding="utf-8"
    )
    index = tmp_path / "index.sqlite"
    config_path = tmp_path / "knowledge.yaml"
    config_path.write_text(yaml.safe_dump({
        "version": 1,
        "index_path": str(index),
        "sources": [{
            "name": "repo", "root": str(root),
            "include": [r"^docs/.*\.md$", r"^src/.*\.py$", r"^tests/.*\.py$", r"^private/.*"],
        }],
        "retrieval": {"top_k": 4, "max_context_chars": 4000, "max_answer_words": 120},
    }), encoding="utf-8")
    config = load_config(config_path)
    build(config)
    return config


ANSWER = "The score is a composite [docs/readiness.md:1-3] \x60The score is a composite\x60."


class FakeClient:
    model = "fake-explain"

    def complete(self, prompt, *, system=None):
        return LLMResponse(text=ANSWER, model=self.model, tokens=11)


def test_retrieval_finds_readiness_and_citation_is_valid(tmp_path):
    config = _fixture(tmp_path)
    chunks = search(config.index_path, "how is readiness calculated", top_k=4, max_chars=4000)
    assert chunks
    assert any(chunk.path == "docs/readiness.md" for chunk in chunks)

    citations = extract(ANSWER, config, config.index_path)
    assert citations and citations[0].verified
    assert citations[0].url.startswith("#docs?doc=")


def test_query_kind_prefers_the_right_source_class():
    assert query_kind("Where in the code is readiness applied?") == "code"
    assert query_kind("What does the test suite expect?") == "test"
    assert query_kind("What does my private athlete state say?") == "private"
    assert query_kind("How is readiness calculated?") == "docs"


def test_retrieval_prefers_expected_source_classes(tmp_path):
    config = _fixture(tmp_path)
    code = search(config.index_path, "Where in the code is the score calculated?", top_k=4, max_chars=4000)
    assert code and code[0].path == "src/score.py"
    tests = search(config.index_path, "What does the test suite expect?", top_k=4, max_chars=4000)
    assert tests and tests[0].path == "tests/test_score.py"
    private = search(config.index_path, "What does my private notes say?", top_k=4, max_chars=4000)
    assert private and private[0].path == "private/notes.md"


def test_citation_rejects_bad_line_and_snippet(tmp_path):
    config = _fixture(tmp_path)
    bad_line = extract("Claim [docs/readiness.md:99-100].", config, config.index_path)
    assert not bad_line[0].verified
    bad_quote = extract(
        "Claim [docs/readiness.md:1-3] \x60unrelated words entirely\x60.", config, config.index_path
    )
    assert not bad_quote[0].verified


class GeneralClient:
    model = "general"

    def complete(self, prompt, *, system=None):
        return LLMResponse(text="This is general knowledge, ungrounded.", model=self.model, tokens=3)


def test_explain_is_ungrounded_without_sources(tmp_path):
    config = _fixture(tmp_path)
    result = run_explain(config, GeneralClient(), "unrelated xyzzy")
    assert not result.grounded
    assert not result.citations
    assert result.tokens == 3


def test_explain_is_grounded_with_sources(tmp_path):
    config = _fixture(tmp_path)
    result = run_explain(config, FakeClient(), "how is readiness calculated")
    assert result.grounded
    assert result.citations
    assert result.tokens == 11
    assert result.chunks


@pytest.fixture()
def web(tmp_path: Path, monkeypatch):
    path = tmp_path / "coach.db"
    db.Store(path).close()
    knowledge = _fixture(tmp_path / "knowledge")
    monkeypatch.setattr(
        server, "load_settings", lambda: SimpleNamespace(enabled=True, daily_tokens=150_000)
    )
    monkeypatch.setattr(server, "build_client", lambda settings=None: FakeClient())
    monkeypatch.setattr(
        intelligence_config, "load_config", lambda path=None: enabled_config()
    )
    monkeypatch.setattr(
        "strength_coach.intelligence.knowledge.allowlist.load_config",
        lambda path=None: knowledge,
    )
    httpd = server.create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_explain_endpoint_returns_citations(web):
    request = urllib.request.Request(
        web + "/api/intelligence/explain",
        data=json.dumps({"question": "how is readiness calculated"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode())
    assert response.status == 200
    assert body["citations"]
    assert body["grounded"] is True
    assert body["tokens"] == 11
