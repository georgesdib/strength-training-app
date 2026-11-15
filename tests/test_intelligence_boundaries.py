"""Layering and read-only boundaries that INT-1 must not cross."""

from __future__ import annotations

import ast
import pathlib
import sqlite3

import pytest
from conftest import make_readiness, make_training
from intelligence_support import seed_store, service

import strength_coach.intelligence as intelligence
from strength_coach.intelligence import INTERNAL_PRINCIPAL
from strength_coach.store import db, importer

FORBIDDEN_IMPORTS = ("strength_coach.web", "strength_coach.agents")
TRANSPORT_FORBIDDEN = ("mcp",)


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_capability_package_imports_no_web_model_or_transport_layer():
    package = pathlib.Path(intelligence.__file__).parent
    files = sorted(package.rglob("*.py"))
    assert files, "the package should contain modules"
    for path in files:
        parts = path.relative_to(package).parts
        if "mcp" in parts:
            continue
        # ADR-INT-002 keeps the model layer above the agents layer: `intelligence/model/` may use
        # `agents.client` (its LLM client and error types), while the capability and context layers
        # may not. Everything below still forbids the web layer and the MCP transport everywhere.
        allowed = {"strength_coach.agents"} if parts and parts[0] == "model" else set()
        imported = _imports(path)
        for forbidden in (*FORBIDDEN_IMPORTS, *TRANSPORT_FORBIDDEN):
            if forbidden in allowed:
                continue
            offenders = [
                name
                for name in imported
                if name == forbidden or name.startswith(forbidden + ".")
            ]
            assert not offenders, f"{path.name} imports {offenders}"


def test_only_the_transport_package_imports_the_mcp_sdk():
    package = pathlib.Path(intelligence.__file__).parent
    users = [
        path.relative_to(package).as_posix()
        for path in sorted(package.rglob("*.py"))
        if any(name == "mcp" or name.startswith("mcp.") for name in _imports(path))
    ]
    assert users, "the transport package should import the SDK"
    assert all(name.startswith("mcp/") for name in users), users


def test_overview_runs_on_a_read_only_connection(tmp_path):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training([
        {"Date": "2026-11-02", "Exercise": "Trap Bar Deadlift", "Weight_Used": "160",
         "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{}])
    try:
        importer.import_export(
            store.connection,
            training,
            readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
    finally:
        store.close()

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        result = service(conn).execute(
            INTERNAL_PRINCIPAL,
            "get_training_overview",
            {"as_of": "2026-11-14", "window_weeks": 4},
        )
        assert result.ok, result.error
        assert result.envelope.status == "ok"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(
                "INSERT INTO ios_pairing_code "
                "(code_hash, created_at, expires_at, attempts, used_at) "
                "VALUES ('x', 'x', 'x', 0, NULL)"
            )
    finally:
        conn.close()


def test_registry_exposes_no_mutation_shaped_capability():
    from strength_coach.intelligence import CAPABILITIES

    banned = ("create_", "update_", "delete_", "set_", "start_", "complete_", "apply_", "remove_")
    for name in CAPABILITIES.names():
        assert not name.startswith(banned), name
        assert name.startswith(("get_", "compare_")), name


def test_seeded_store_helper_is_synthetic_only():
    store = seed_store()
    try:
        rows = store.connection.execute(
            "SELECT COUNT(*) AS n FROM clean_set"
        ).fetchone()["n"]
        assert rows >= 1
    finally:
        store.close()
