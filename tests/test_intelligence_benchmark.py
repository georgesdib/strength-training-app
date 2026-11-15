"""Extended Intelligence benchmark: discovery, arguments, stats, HTTP and safety."""

from __future__ import annotations

import contextlib
import importlib.util
import json
from pathlib import Path

import pytest
from conftest import make_readiness, make_training

from strength_coach.intelligence import IntelligenceConfig
from strength_coach.intelligence.registry import CAPABILITIES
from strength_coach.store import db, importer

ROOT = Path(__file__).resolve().parents[1]


def _load_benchmark():
    spec = importlib.util.spec_from_file_location(
        "intelligence_benchmark", ROOT / "tools/intelligence_benchmark.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench = _load_benchmark()


@pytest.fixture
def path(tmp_path):
    target = tmp_path / "coach.db"
    store = db.Store(target)
    training = make_training([
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "2"},
        {"Date": "2024-01-04", "Exercise": "Trap Bar Deadlift", "Weight_Used": "155", "RIR": "2"},
        {"Date": "2024-01-08", "Exercise": "Trap Bar Deadlift", "Weight_Used": "160", "RIR": "2"},
    ])
    readiness = make_readiness([{"Date": "2024-01-01"}])
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
    finally:
        store.close()
    return target


def test_every_registered_capability_is_discovered(path):
    conn = bench.connect_readonly(path)
    try:
        arguments, unsupported = bench.build_arguments(conn, __import__("datetime").date(2024, 1, 12))
    finally:
        conn.close()
    assert set(CAPABILITIES.names()) == set(arguments) | set(unsupported)
    assert not unsupported


def test_generated_arguments_parse_for_every_capability(path):
    import datetime as dt

    conn = bench.connect_readonly(path)
    config = IntelligenceConfig(enabled=True)
    today = dt.date(2024, 1, 12)
    try:
        arguments, unsupported = bench.build_arguments(conn, today)
    finally:
        conn.close()
    assert not unsupported
    for name, payload in arguments.items():
        spec = CAPABILITIES.get(name)
        parsed = spec.request_type.parse(payload, config=config, today=today)
        assert parsed.to_mapping()


def test_legacy_overview_invocation_still_returns_its_shape():
    report = bench.run(20, 2, 4)
    assert report["execution"]["capability"] == "get_training_overview"
    assert report["execution"]["runs"] == 2
    assert report["dataset"]["sessions"] == 20


def test_statistics_are_reported():
    stats = bench.statistics_for([1.0, 2.0, 3.0, 4.0])
    assert stats["n"] == 4
    assert stats["p50_ms"] == 2.0
    assert stats["max_ms"] == 4.0
    assert stats["p95_ms"] == 4.0
    assert bench.statistics_for([]) == {"n": 0}


def test_direct_mode_is_read_only(path):
    conn = db.Store(path)
    try:
        before = {
            table: conn.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("session", "clean_set", "workout_session", "prescription")
        }
    finally:
        conn.close()
    conn = bench.connect_readonly(path)
    try:
        arguments, unsupported = bench.build_arguments(conn, __import__("datetime").date(2024, 1, 12))
    finally:
        conn.close()
    result = bench.run_direct(path, arguments, unsupported, iterations=1, warmup=0)
    assert result["results"]["get_training_overview"]["success"] == 1
    conn = db.Store(path)
    try:
        after = {
            table: conn.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("session", "clean_set", "workout_session", "prescription")
        }
    finally:
        conn.close()
    assert after == before


def test_report_redacts_identifiers(path):
    conn = bench.connect_readonly(path)
    try:
        arguments, unsupported = bench.build_arguments(conn, __import__("datetime").date(2024, 1, 12))
    finally:
        conn.close()
    session_id = arguments["get_session_details"]["session_id"]
    direct = bench.run_direct(path, arguments, unsupported, iterations=1, warmup=0)
    report = bench._build_report(
        path=path, sessions=3, sets=3, readiness=1, source="database",
        arguments=arguments, unsupported=unsupported, direct=direct, http=None,
        iterations=1, warmup=0, threshold_ms=1000.0, url=None,
    )
    serialised = json.dumps(report)
    assert session_id not in serialised
    assert "<redacted>" in serialised


class _Tool:
    def __init__(self, name):
        self.name = name


class _FakeClient:
    def __init__(self, names, failing=()):
        self.names = names
        self.failing = set(failing)

    async def list_tools(self):
        return type("Tools", (), {"tools": [_Tool(name) for name in self.names]})()

    async def call_tool(self, name, arguments):
        if name in self.failing:
            raise TimeoutError("slow")
        return type("Result", (), {"isError": False})()


def test_http_mode_uses_discovered_tools_and_reports_errors(path, monkeypatch):
    conn = bench.connect_readonly(path)
    try:
        arguments, unsupported = bench.build_arguments(conn, __import__("datetime").date(2024, 1, 12))
    finally:
        conn.close()
    names = list(arguments)
    client = _FakeClient(names, failing={names[0]})

    @contextlib.asynccontextmanager
    async def fake_session(url, token, timeout):
        yield client

    monkeypatch.setattr(bench, "_http_session", fake_session)
    result = bench.run_http(
        "http://test/mcp", "token", 1.0, arguments, unsupported,
        iterations=2, warmup=0,
    )
    first = result["results"][names[0]]
    assert first["errors"] == 2
    assert first["success"] == 0
    second = result["results"][names[1]]
    assert second["success"] == 2
    assert "tool_error" not in second.get("error_examples", [])


def test_http_authentication_failure_is_reported(path, monkeypatch):
    conn = bench.connect_readonly(path)
    try:
        arguments, unsupported = bench.build_arguments(conn, __import__("datetime").date(2024, 1, 12))
    finally:
        conn.close()

    @contextlib.asynccontextmanager
    async def failing_session(url, token, timeout):
        raise PermissionError("401 unauthorized")
        yield  # pragma: no cover

    monkeypatch.setattr(bench, "_http_session", failing_session)
    result = bench.run_http(
        "http://test/mcp", "bad", 1.0, arguments, unsupported,
        iterations=1, warmup=0,
    )
    assert "PermissionError" in result["error"]


def test_http_arguments_use_tool_input_schemas():
    translated = bench.http_arguments({
        "get_readiness_history": {"from": "2024-01-01", "to": "2024-02-01"},
        "get_vbt_analysis": {
            "from": "2024-01-01", "to": "2024-02-01", "exercise_id": "x",
        },
        "get_training_overview": {"as_of": "2024-02-01"},
    })
    assert translated["get_readiness_history"] == {
        "start": "2024-01-01", "end": "2024-02-01",
    }
    assert translated["get_vbt_analysis"] == {
        "start": "2024-01-01", "end": "2024-02-01", "exercise_id": "x",
    }
    assert translated["get_training_overview"] == {"as_of": "2024-02-01"}


def test_unknown_capability_is_reported_not_skipped(tmp_path, path):
    report = bench.run_extended(
        sessions=3, iterations=1, warmup=0, db_path=str(path), mode="direct",
        url="http://test/mcp", token=None, timeout=1.0,
        only=["does_not_exist"], threshold_ms=1000.0, build_analytics=False,
    )
    assert report["configuration"]["unsupported"] == {
        "does_not_exist": "unknown capability"
    }
    assert "does_not_exist" in report["capabilities"]
