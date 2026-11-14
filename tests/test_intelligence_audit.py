"""Structured audit records: one per invocation, metadata only."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="optional intelligence MCP extra")
from conftest import make_readiness, make_training
from intelligence_support import enabled_config
from mcp import Client

from strength_coach.intelligence import audit
from strength_coach.intelligence.auth import Principal
from strength_coach.intelligence.mcp.app import build_server
from strength_coach.intelligence.mcp.security import authenticated
from strength_coach.store import db, importer

AUDIT_LOGGER = "strength_coach.intelligence.audit"
PRINCIPAL = Principal(identity="mcp-test", kind="mcp")


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


def _records(caplog) -> list[dict]:
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == AUDIT_LOGGER
    ]


def _call(db_path: Path, tool: str, arguments: dict) -> tuple:
    async def run():
        async with Client(build_server(db_path=db_path, config=enabled_config())) as client:
            with authenticated(PRINCIPAL):
                return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def test_tool_success_emits_one_complete_record(db_path, caplog):
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        result = _call(db_path, "get_training_overview", {"as_of": "2026-11-14"})
    assert result.is_error is False
    records = _records(caplog)
    assert len(records) == 1
    record = records[0]
    assert set(record) == {
        "schema", "request_id", "kind", "name", "client_id", "arguments_hash",
        "duration_ms", "result_rows", "response_bytes", "outcome", "status",
    }
    assert record["schema"] == "intelligence.audit.v1"
    assert record["kind"] == "tool"
    assert record["name"] == "get_training_overview"
    assert record["client_id"] == "mcp-test"
    assert record["outcome"] == "ok"
    assert record["status"] == "ok"
    assert record["arguments_hash"].startswith("sha256:")
    assert record["response_bytes"] > 0
    assert record["result_rows"] == 2
    assert record["request_id"].startswith("int-")


def test_session_tool_is_audited(db_path, caplog):
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        result = _call(db_path, "get_session_details", {"workout_id": "missing"})
    assert result.is_error is True
    records = _records(caplog)
    assert len(records) == 1
    assert records[0]["name"] == "get_session_details"
    assert records[0]["outcome"] == "not_found"
    assert records[0]["response_bytes"] == 0


def test_resource_read_is_audited(db_path, caplog):
    async def run():
        async with Client(build_server(db_path=db_path, config=enabled_config())) as client:
            with authenticated(PRINCIPAL):
                return await client.read_resource("strength://athlete/profile")

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        asyncio.run(run())
    records = _records(caplog)
    assert len(records) == 1
    assert records[0]["kind"] == "resource"
    assert records[0]["name"] == "strength://athlete/profile"
    assert records[0]["outcome"] == "ok"


def test_records_carry_no_arguments_payloads_or_tokens(db_path, caplog):
    token = "super-secret-token-value"
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        _call(db_path, "get_training_overview", {"as_of": "2026-11-14", "window_weeks": 4})
    text = caplog.text
    assert token not in text
    assert "2026-11-14" not in text
    assert "window_weeks" not in text
    assert "attendance" not in text
    assert "limitations" not in text


def test_invalid_arguments_are_audited_without_the_message(db_path, caplog):
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        result = _call(db_path, "get_training_overview", {"window_weeks": 99})
    assert result.is_error is True
    record = _records(caplog)[0]
    assert record["outcome"] == "invalid_argument"
    assert "99" not in json.dumps(record)


def test_request_ids_are_unique(db_path, caplog):
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        _call(db_path, "get_training_overview", {"as_of": "2026-11-14"})
        _call(db_path, "get_training_overview", {"as_of": "2026-11-14"})
    records = _records(caplog)
    assert len(records) == 2
    assert records[0]["request_id"] != records[1]["request_id"]


def test_argument_hash_is_stable_and_value_sensitive(db_path, caplog):
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        _call(db_path, "get_training_overview", {"as_of": "2026-11-14"})
        _call(db_path, "get_training_overview", {"as_of": "2026-11-14"})
        _call(db_path, "get_training_overview", {"as_of": "2026-11-07"})
    first, second, third = _records(caplog)
    assert first["arguments_hash"] == second["arguments_hash"]
    assert first["arguments_hash"] != third["arguments_hash"]


def test_a_logging_failure_does_not_change_the_result(db_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("logging exploded")

    monkeypatch.setattr(audit.LOGGER, "info", boom)
    result = _call(db_path, "get_training_overview", {"as_of": "2026-11-14"})
    assert result.is_error is False
    assert result.structured_content["status"] == "ok"
