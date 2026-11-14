"""MCP protocol: discovery, schemas, invocation, error semantics and the resource."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from conftest import make_readiness, make_training
from intelligence_support import enabled_config, service
from mcp import Client

from strength_coach import workout
from strength_coach.intelligence import INTERNAL_PRINCIPAL
from strength_coach.intelligence.mcp.app import build_server
from strength_coach.intelligence.mcp.security import authenticated
from strength_coach.store import db, importer

PLAN = {
    "for_date": "2026-11-02",
    "session_type": "hinge",
    "items": [
        {"exercise_id": "trap_bar_deadlift", "sets": 2, "reps_low": 3, "reps_high": 5,
         "load_kg": 100, "rir_target": 2, "e1rm_kg": 120.0, "e1rm_ref": "set:s0/1",
         "e1rm_quality": "ok", "e1rm_age_days": 2},
    ],
}
READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
             "nutrition": 4, "hydration": 4}


def _seed(path: Path) -> None:
    store = db.Store(path)
    training = make_training([
        {"Date": "2026-10-19", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2026-10-26", "Exercise": "Trap Bar Deadlift", "Weight_Used": "155",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2026-11-02", "Exercise": "Trap Bar Deadlift", "Weight_Used": "160",
         "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{"Date": "2026-10-26", "Sleep": "4", "Soreness": "2"}])
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


def _server(db_path: Path):
    return build_server(db_path=db_path, config=enabled_config())


def _call(db_path: Path, tool: str, arguments: dict):
    async def run():
        async with Client(_server(db_path)) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def test_tools_are_discoverable_with_input_schemas(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            return await client.list_tools()

    listed = asyncio.run(run())
    names = [tool.name for tool in listed.tools]
    assert names == ["get_training_overview", "get_session_details"]
    overview = next(tool for tool in listed.tools if tool.name == "get_training_overview")
    properties = (overview.input_schema or {})["properties"]
    assert set(properties) == {"as_of", "window_weeks"}
    assert properties["window_weeks"]["type"] == "integer"
    session = next(tool for tool in listed.tools if tool.name == "get_session_details")
    assert set((session.input_schema or {})["properties"]) == {
        "workout_id", "session_id", "include_ratios"
    }


def test_tools_declare_read_only_annotations(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            return await client.list_tools()

    for tool in asyncio.run(run()).tools:
        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is True
        assert annotations.destructive_hint is False
        assert annotations.idempotent_hint is True


def test_output_schema_is_the_envelope(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            return await client.list_tools()

    for tool in asyncio.run(run()).tools:
        schema = tool.output_schema or {}
        assert "facts" in schema["properties"]
        assert "provenance" in schema["properties"]
        assert "evidence" in schema["properties"]
        assert set(schema.get("required", [])) >= {"status", "as_of", "facts", "provenance"}


def test_overview_tool_matches_the_capability_service(db_path):
    result = _call(db_path, "get_training_overview",
                   {"as_of": "2026-11-14", "window_weeks": 4})
    assert result.is_error is False
    payload = result.structured_content
    assert payload["status"] == "ok"

    store = db.Store(db_path)
    try:
        direct = service(store.connection).execute(
            INTERNAL_PRINCIPAL,
            "get_training_overview",
            {"as_of": "2026-11-14", "window_weeks": 4},
        )
    finally:
        store.close()
    expected = direct.envelope.as_dict()
    assert payload["facts"] == expected["facts"]
    assert payload["coverage"] == expected["coverage"]
    assert payload["missing"] == expected["missing"]
    assert payload["limitations"] == expected["limitations"]
    assert payload["provenance"]["context_hash"] == expected["provenance"]["context_hash"]


def test_no_data_survives_the_transport(db_path):
    result = _call(db_path, "get_training_overview", {"as_of": "2025-01-01"})
    assert result.is_error is False
    assert result.structured_content["status"] == "no_data"
    assert "no completed sessions in the window" in result.structured_content["missing"]


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"bogus": 1}, "unknown argument"),
        ({"window_weeks": "4"}, "wrong type"),
        ({"window_weeks": True}, "wrong type"),
        ({"window_weeks": 99}, "window_weeks"),
        ({"as_of": "nope"}, "as_of"),
        ({"as_of": "2999-01-01"}, "future"),
    ],
)
def test_invalid_arguments_become_tool_errors(db_path, arguments, message):
    result = _call(db_path, "get_training_overview", arguments)
    assert result.is_error is True
    assert message in result.content[0].text
    assert result.structured_content is None


def test_session_tool_returns_detail_and_evidence(db_path):
    store = db.Store(db_path)
    try:
        started = workout.start(
            store.connection, for_date="2026-11-02", plan=PLAN, readiness=READINESS
        )
        workout.add_set(store.connection, started["workout_id"],
                        exercise_id="trap_bar_deadlift", load_kg=100, reps=5, rir=2)
        workout.end(store.connection, started["workout_id"], session_rpe=7, duration_min=50)
        workout_id = started["workout_id"]
    finally:
        store.close()

    result = _call(db_path, "get_session_details", {"workout_id": workout_id})
    assert result.is_error is False
    payload = result.structured_content
    assert payload["status"] == "ok"
    assert payload["facts"]["session"]["value"]["source"] == "workout"
    assert payload["evidence"], "the summary evidence must survive the transport"
    assert payload["facts"]["feedback"]["value"]["srpe"] == 7.0


def test_session_lookup_errors_are_tool_errors(db_path):
    result = _call(db_path, "get_session_details", {"workout_id": "missing"})
    assert result.is_error is True
    assert "not_found" in result.content[0].text


def test_resource_is_the_profile_envelope(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                listed = await client.list_resources()
                read = await client.read_resource("strength://athlete/profile")
                return listed, read

    listed, read = asyncio.run(run())
    assert [str(item.uri) for item in listed.resources] == ["strength://athlete/profile"]
    assert read.contents[0].mime_type == "application/json"
    payload = json.loads(read.contents[0].text)
    assert payload["capability"] == "athlete_profile"
    assert "profile" in payload["facts"] and "constraints" in payload["facts"]
    assert "injury constraints" in payload["privacy"]["excluded_fields"]


def test_calls_require_a_principal(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            return await client.call_tool("get_training_overview", {})

    result = asyncio.run(run())
    assert result.is_error is True


def test_modern_protocol_version_is_negotiated(db_path):
    async def run():
        async with Client(_server(db_path)) as client:
            return client.protocol_version

    assert asyncio.run(run()) == "2026-07-28"


def test_legacy_client_is_served_by_the_same_server(db_path):
    async def run():
        async with Client(_server(db_path), mode="legacy") as client:
            with authenticated(INTERNAL_PRINCIPAL):
                version = client.protocol_version
                result = await client.call_tool(
                    "get_training_overview", {"as_of": "2026-11-14"}
                )
                return version, result

    version, result = asyncio.run(run())
    assert version == "2025-11-25"
    assert result.is_error is False
    assert result.structured_content["status"] == "ok"
