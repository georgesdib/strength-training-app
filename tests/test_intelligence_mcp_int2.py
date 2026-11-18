"""MCP exposure of the INT-2 catalogue: discovery, schemas, parity and strict arguments."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="optional intelligence MCP extra")

from conftest import make_readiness, make_training
from intelligence_support import enabled_config, service
from mcp import Client

from strength_coach.intelligence import INTERNAL_PRINCIPAL
from strength_coach.intelligence.mcp.app import build_server
from strength_coach.intelligence.mcp.security import authenticated
from strength_coach.store import db, importer, repositories

EXPECTED_TOOLS = {
    "get_training_overview",
    "get_session_details",
    "get_exercise_progression",
    "get_readiness_history",
    "get_adherence_analysis",
    "get_prescription",
    "get_vbt_analysis",
    "get_programme_block_summary",
    "compare_training_periods",
    "get_weekly_review",
    "get_longevity_assessment",
}


def _seed(path: Path) -> None:
    store = db.Store(path)
    conn = store.connection
    rows = []
    for index in range(6):
        day = (dt.date(2026, 9, 7) + dt.timedelta(days=7 * index)).isoformat()
        rows.append({"Date": day, "Exercise": "Trap Bar Deadlift",
                     "Weight_Used": str(140 + index * 5), "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{"Date": "2026-10-19", "Sleep": "4", "Soreness": "2"}])
    try:
        importer.import_export(
            conn, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        repositories.append_athlete_profile(
            conn, effective_from="2026-01-01", sessions_per_week_target=3
        )
    finally:
        store.close()


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "coach.db"
    _seed(path)
    return path


def _server(db_path: Path):
    return build_server(db_path=db_path, config=enabled_config())


def test_catalogue_is_discoverable_with_schemas(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            return await client.list_tools()

    tools = asyncio.run(run()).tools
    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    by_name = {tool.name: tool for tool in tools}
    progression = by_name["get_exercise_progression"].input_schema or {}
    assert set(progression["properties"]) == {
        "exercise_id", "as_of", "window_days", "include_sessions", "limit_sessions"
    }
    assert progression["properties"]["window_days"]["type"] == "integer"
    readiness = by_name["get_readiness_history"].input_schema or {}
    assert set(readiness["properties"]) == {"start", "end", "fields"}
    compare = by_name["compare_training_periods"].input_schema or {}
    assert set(compare["properties"]) == {"period_a", "period_b", "metric", "exercise_id"}
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert "facts" in (tool.output_schema or {}).get("properties", {})


def test_three_resources_are_discoverable(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                listed = await client.list_resources()
                reads = {}
                for uri in (
                    "strength://athlete/profile",
                    "strength://programme/current",
                    "strength://overview/current",
                ):
                    read = await client.read_resource(uri)
                    reads[uri] = json.loads(read.contents[0].text)
                return listed, reads

    listed, reads = asyncio.run(run())
    assert {str(item.uri) for item in listed.resources} == set(reads)
    for payload in reads.values():
        assert payload["schema_version"] == "intelligence.envelope.v1"
        assert "provenance" in payload


def test_progression_via_mcp_matches_the_service(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                return await client.call_tool(
                    "get_exercise_progression",
                    {"exercise_id": "trap_bar_deadlift", "as_of": "2026-11-14"},
                )

    result = asyncio.run(run())
    assert result.is_error is False
    store = db.Store(db_path)
    try:
        direct = service(store.connection).execute(
            INTERNAL_PRINCIPAL,
            "get_exercise_progression",
            {"exercise_id": "trap_bar_deadlift", "as_of": "2026-11-14"},
        )
    finally:
        store.close()
    assert result.structured_content["facts"] == direct.envelope.as_dict()["facts"]


def test_readiness_uses_start_and_end_and_rejects_from(db_path):
    async def run(arguments):
        async with Client(_server(db_path)) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                return await client.call_tool("get_readiness_history", arguments)

    good = asyncio.run(run({"start": "2026-09-01", "end": "2026-11-14"}))
    assert good.is_error is False
    assert "score_series" in good.structured_content["facts"]

    contract_spelling = asyncio.run(run({"from": "2026-09-01", "to": "2026-11-14"}))
    assert contract_spelling.is_error is True
    assert "unknown argument" in contract_spelling.content[0].text


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"exercise_id": "trap_bar_deadlift", "window_days": "84"}, "wrong type"),
        ({"exercise_id": "trap_bar_deadlift", "bogus": 1}, "unknown argument"),
        ({"exercise_id": 42}, "wrong type"),
    ],
)
def test_strict_arguments_apply_to_the_new_tools(db_path, arguments, message):
    async def run():
        async with Client(_server(db_path)) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                return await client.call_tool("get_exercise_progression", arguments)

    result = asyncio.run(run())
    assert result.is_error is True
    assert message in result.content[0].text


def test_compare_accepts_nested_periods(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                return await client.call_tool("compare_training_periods", {
                    "period_a": {"start": "2026-09-01", "end": "2026-10-01"},
                    "period_b": {"start": "2026-10-02", "end": "2026-11-14"},
                    "metric": "attendance",
                })

    result = asyncio.run(run())
    assert result.is_error is False
    assert result.structured_content["facts"]["comparison"]["value"]["metric"] == "attendance"


def test_raw_readiness_fields_are_blocked_over_mcp(db_path):
    async def call(arguments, *, allow_sensitive=False):
        server = build_server(
            db_path=db_path,
            config=enabled_config(allow_sensitive_readiness=allow_sensitive),
        )
        async with Client(server) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                return await client.call_tool("get_readiness_history", arguments)

    blocked = asyncio.run(call(
        {"start": "2026-09-01", "end": "2026-11-14", "fields": ["sleep"]}
    ))
    assert blocked.is_error is True
    assert "raw readiness fields are not available over MCP" in blocked.content[0].text

    score_only = asyncio.run(call(
        {"start": "2026-09-01", "end": "2026-11-14", "fields": ["score"]}
    ))
    assert score_only.is_error is False
    assert "score_series" in score_only.structured_content["facts"]

    opted_in = asyncio.run(call(
        {"start": "2026-09-01", "end": "2026-11-14", "fields": ["sleep"]},
        allow_sensitive=True,
    ))
    assert opted_in.is_error is False
    assert "readiness" in opted_in.structured_content["facts"]
