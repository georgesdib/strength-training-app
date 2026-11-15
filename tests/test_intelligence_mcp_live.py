"""End-to-end over the real Streamable HTTP transport.

Starts the actual ASGI application under uvicorn, authenticates with the official MCP client over
HTTP, and exercises both tools and the resource. No transport is mocked.
"""

# ruff: noqa: E402  (the optional MCP extras are skipped before their imports)
from __future__ import annotations

import asyncio
import http.client
import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="optional intelligence MCP extra")
pytest.importorskip("httpx2", reason="MCP client dependency")
import httpx2
import uvicorn
from conftest import make_readiness, make_training
from intelligence_support import enabled_config
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from strength_coach import workout
from strength_coach.intelligence.mcp.app import build_app
from strength_coach.intelligence.tokens import TokenStore
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
TABLES = ("session", "clean_set", "workout_session", "workout_set", "prescription",
          "readiness_day", "session_feedback")


def _counts(path: Path) -> dict[str, int]:
    store = db.Store(path)
    try:
        return {
            table: store.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }
    finally:
        store.close()


def _seed(path: Path) -> str:
    store = db.Store(path)
    training = make_training([
        {"Date": "2026-10-19", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2026-11-02", "Exercise": "Trap Bar Deadlift", "Weight_Used": "160",
         "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{"Date": "2026-10-19", "Sleep": "4", "Soreness": "2"}])
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        started = workout.start(
            store.connection, for_date="2026-11-02", plan=PLAN, readiness=READINESS
        )
        workout.add_set(store.connection, started["workout_id"],
                        exercise_id="trap_bar_deadlift", load_kg=100, reps=5, rir=2)
        workout.end(store.connection, started["workout_id"], session_rpe=7, duration_min=50)
        return started["workout_id"]
    finally:
        store.close()


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    root = tmp_path_factory.mktemp("mcp-live")
    path = root / "coach.db"
    workout_id = _seed(path)
    before = _counts(path)
    store = TokenStore.load(root / "intelligence.local.yaml")
    _, token = store.create("Live test client")
    app = build_app(db_path=path, config=enabled_config(), store=store)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.01)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield {"port": port, "token": token, "workout_id": workout_id, "path": path,
               "before": before}
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        assert not thread.is_alive(), "server did not shut down cleanly"


def _scenario(port: int, token: str, workout_id: str) -> dict:
    async def run():
        results: dict = {}
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx2.AsyncClient(headers=headers, timeout=30) as http_client:
            transport = streamable_http_client(
                f"http://127.0.0.1:{port}/mcp", http_client=http_client
            )
            async with Client(transport) as client:
                results["protocol"] = client.protocol_version
                tools = await client.list_tools()
                results["tools"] = [tool.name for tool in tools.tools]
                overview = await client.call_tool(
                    "get_training_overview", {"as_of": "2026-11-14"}
                )
                results["overview"] = overview
                session = await client.call_tool(
                    "get_session_details", {"workout_id": workout_id}
                )
                results["session"] = session
                resource = await client.read_resource("strength://athlete/profile")
                results["resource"] = json.loads(resource.contents[0].text)
                results["resource_mime"] = resource.contents[0].mime_type
                programme = await client.read_resource("strength://programme/current")
                results["programme_resource"] = json.loads(programme.contents[0].text)
                progression = await client.call_tool(
                    "get_exercise_progression",
                    {"exercise_id": "trap_bar_deadlift", "as_of": "2026-11-14"},
                )
                results["progression"] = progression
                no_data = await client.call_tool(
                    "get_training_overview", {"as_of": "2025-01-01"}
                )
                results["no_data"] = no_data
                invalid = await client.call_tool(
                    "get_training_overview", {"window_weeks": 99}
                )
                results["invalid"] = invalid
                missing = await client.call_tool(
                    "get_session_details", {"session_id": "missing"}
                )
                results["missing"] = missing
        return results

    return asyncio.run(run())


def _unauthenticated_post(port: int) -> int:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(
            "POST", "/mcp", body=body,
            headers={"Content-Type": "application/json",
                     "Host": f"127.0.0.1:{port}"},
        )
        return connection.getresponse().status
    finally:
        connection.close()


def test_live_http_tools_and_resource(live):
    results = _scenario(live["port"], live["token"], live["workout_id"])

    assert results["protocol"] == "2026-07-28"
    assert results["tools"] == [
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
    ]

    overview = results["overview"]
    assert overview.is_error is False
    envelope = overview.structured_content
    assert envelope["schema_version"] == "intelligence.envelope.v1"
    assert envelope["capability"] == "get_training_overview"
    assert envelope["status"] == "ok"
    assert envelope["provenance"]["context_hash"].startswith("sha256:")
    assert envelope["privacy"]["class"] == "training"

    session = results["session"]
    assert session.is_error is False
    assert session.structured_content["facts"]["session"]["value"]["source"] == "workout"
    assert session.structured_content["evidence"], "evidence must survive HTTP"

    assert results["resource_mime"] == "application/json"
    assert results["resource"]["capability"] == "athlete_profile"
    assert "profile" in results["resource"]["facts"]

    assert results["programme_resource"]["capability"] == "programme_current"
    assert "profile" in results["programme_resource"]["facts"]

    progression = results["progression"]
    assert progression.is_error is False
    assert progression.structured_content["capability"] == "get_exercise_progression"
    assert "summary" in progression.structured_content["facts"]

    assert results["no_data"].structured_content["status"] == "no_data"
    assert results["invalid"].is_error is True
    assert "invalid_argument" in results["invalid"].content[0].text
    assert results["missing"].is_error is True
    assert "not_found" in results["missing"].content[0].text


def test_live_http_rejects_unauthenticated_before_capability(live):
    assert _unauthenticated_post(live["port"]) == 401


def test_live_http_leaves_the_database_unchanged(live):
    async def ping():
        headers = {"Authorization": f"Bearer {live['token']}"}
        async with httpx2.AsyncClient(headers=headers, timeout=30) as http_client:
            transport = streamable_http_client(
                f"http://127.0.0.1:{live['port']}/mcp", http_client=http_client
            )
            async with Client(transport) as client:
                return await client.call_tool(
                    "get_training_overview", {"as_of": "2026-11-14"}
                )

    assert asyncio.run(ping()).is_error is False
    assert _counts(live["path"]) == live["before"]
