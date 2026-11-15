"""Runtime protections: per-call timeout and serialized result size."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="optional intelligence MCP extra")
from conftest import make_readiness, make_training
from intelligence_support import enabled_config
from intelligence_support import envelope as sample_envelope
from mcp import Client

from strength_coach.intelligence import INTERNAL_PRINCIPAL
from strength_coach.intelligence.mcp import tools as tools_module
from strength_coach.intelligence.mcp.app import build_server
from strength_coach.intelligence.mcp.security import authenticated
from strength_coach.intelligence.mcp.tools import rows_considered
from strength_coach.store import db, importer


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


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "coach.db"
    _seed(path)
    return path


def _call(db_path: Path, config, tool: str, arguments: dict):
    async def run():
        server = build_server(db_path=db_path, config=config)
        async with Client(server) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                started = time.perf_counter()
                result = await client.call_tool(tool, arguments)
                # Measure the response, not the event-loop shutdown: an abandoned worker thread
                # still delays process exit, which is a documented limitation.
                return result, time.perf_counter() - started

    return asyncio.run(run())


def test_timeout_returns_a_sanitised_error(db_path, monkeypatch):
    def slow(*args, **kwargs):
        time.sleep(3)
        return sample_envelope()

    monkeypatch.setattr(tools_module, "_execute", slow)
    config = dc.replace(enabled_config(), tool_timeout_seconds=1)
    result, elapsed = _call(
        db_path, config, "get_training_overview", {"as_of": "2026-11-14"}
    )
    assert result.is_error is True
    assert "tool_timeout" in result.content[0].text
    assert result.structured_content is None
    assert elapsed < 2.5, "the timeout must bound the response, not just the wait"


def test_oversized_tool_result_is_rejected_without_a_payload(db_path):
    config = dc.replace(enabled_config(), max_tool_result_bytes=1024)
    result, _ = _call(
        db_path, config, "get_training_overview", {"as_of": "2026-11-14"}
    )
    assert result.is_error is True
    assert "result_too_large" in result.content[0].text
    assert result.structured_content is None


def test_normal_result_fits_the_default_limit(db_path):
    result, _ = _call(db_path, enabled_config(), "get_training_overview",
                      {"as_of": "2026-11-14"})
    assert result.is_error is False
    assert result.structured_content["status"] == "ok"


def _flatten(exc: BaseException) -> str:
    parts = [str(exc)]
    for inner in getattr(exc, "exceptions", ()):
        parts.append(_flatten(inner))
    return " | ".join(parts)


def test_oversized_resource_read_is_rejected(db_path):
    config = dc.replace(enabled_config(), max_tool_result_bytes=1024)

    async def run():
        server = build_server(db_path=db_path, config=config)
        async with Client(server) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                return await client.read_resource("strength://athlete/profile")

    with pytest.raises(Exception) as error:
        asyncio.run(run())
    assert "result_too_large" in _flatten(error.value)


def test_rows_considered_prefers_the_row_count_keys():
    envelope = sample_envelope()
    assert rows_considered(envelope) is None
    coverage = dict(envelope.coverage)
    coverage["completed_sessions"] = 7
    assert rows_considered(dc.replace(envelope, coverage=coverage)) == 7
    other = dc.replace(envelope, coverage={"sets_considered": 9})
    assert rows_considered(other) == 9
