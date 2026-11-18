"""Every MCP tool carries measured latency guidance; slow tools remain callable."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="optional intelligence MCP extra")

from strength_coach.intelligence import latency
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.mcp.tools import register_tools
from strength_coach.intelligence.registry import CAPABILITIES


class _RecordingServer:
    def __init__(self) -> None:
        self.tools: dict[str, dict] = {}

    def tool(self, **kwargs):
        def decorator(fn):
            self.tools[kwargs["name"]] = kwargs
            return fn

        return decorator


def _registered() -> dict[str, dict]:
    server = _RecordingServer()
    register_tools(server, db_path=Path("/tmp/benchmark.db"), config=IntelligenceConfig(enabled=True))
    return server.tools


def test_latency_table_covers_every_registered_capability():
    assert set(latency.MEASURED) == set(CAPABILITIES.names())


def test_every_tool_description_contains_classification_and_p95():
    tools = _registered()
    assert set(tools) == set(latency.MEASURED)
    for name, p95_kind in latency.MEASURED.items():
        p95, kind = p95_kind
        description = tools[name]["description"]
        assert kind in description
        assert f"{p95:,} ms" in description
        assert "not a runtime guarantee" in description
        assert "Never omit or alter required evidence" in description


def test_slow_tools_are_still_registered_and_callable():
    tools = _registered()
    for name in latency.MEASURED:
        assert name in tools
    assert {"get_session_details", "get_training_overview", "get_programme_block_summary"} <= set(
        tools
    )
    assert latency.classification("get_session_details") == "very_slow"
    assert "avoid repeated calls" in latency.description("get_session_details")


def test_fast_tools_prefer_use_and_slow_tools_allow_use():
    assert "Prefer this capability" in latency.description("get_exercise_progression")
    assert "materially useful" in latency.description("get_training_overview")
    assert "full evidence is needed" in latency.description("get_session_details")


def test_latency_catalogue_is_serialisable_and_sorted():
    catalogue = latency.catalogue()
    assert len(catalogue) == 11
    assert [row["capability"] for row in catalogue] == sorted(row["capability"] for row in catalogue)
    assert all(isinstance(row["p95_ms"], int) for row in catalogue)
