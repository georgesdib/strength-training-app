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

FORBIDDEN_IMPORTS = ("strength_coach.web", "strength_coach.agents", "mcp")


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_intelligence_package_imports_no_transport_or_model_layer():
    package = pathlib.Path(intelligence.__file__).parent
    files = sorted(package.rglob("*.py"))
    assert files, "the package should contain modules"
    for path in files:
        imported = _imports(path)
        for forbidden in FORBIDDEN_IMPORTS:
            offenders = [
                name
                for name in imported
                if name == forbidden or name.startswith(forbidden + ".")
            ]
            assert not offenders, f"{path.name} imports {offenders}"


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
