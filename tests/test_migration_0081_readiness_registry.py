"""Migration 0081 adds the append-only, date-effective readiness registry."""

from __future__ import annotations

import json
import shutil
import sqlite3

import pytest

from strength_coach.store import db, queries, repositories


def _partial_migrations(tmp_path):
    source = db.MIGRATIONS_DIR
    partial = tmp_path / "migrations"
    partial.mkdir()
    for path in sorted(source.glob("*.sql")):
        if path.name.startswith("0081"):
            continue
        shutil.copy2(path, partial / path.name)
    return partial


def _connect(tmp_path):
    return db.connect(tmp_path / "coach.db")


def test_registry_is_additive_and_seeded(tmp_path):
    conn = _connect(tmp_path)
    try:
        db.migrate(conn, _partial_migrations(tmp_path))
        conn.execute("INSERT INTO readiness_day (on_date, sleep) VALUES ('2026-11-01', 4)")
        db.migrate(conn)

        row = conn.execute(
            "SELECT sleep FROM readiness_day WHERE on_date = '2026-11-01'"
        ).fetchone()
        assert row["sleep"] == 4

        rows = conn.execute("SELECT * FROM readiness_registry").fetchall()
        assert len(rows) == 1
        seed = rows[0]
        assert seed["effective_from"] == "1970-01-01"
        assert seed["schema_version"] == 1

        payload = json.loads(seed["payload_json"])
        assert payload["schema_version"] == 1
        assert payload["min_core_fields"] == 3
        assert payload["require_any_of"] == ["sleep", "energy"]
        assert payload["wearable_weight"] == 0.1
        metrics = {item["key"]: item for item in payload["metrics"]}
        assert list(metrics) == [
            "sleep", "energy", "mood", "stress", "soreness", "hrv_ms", "rhr_bpm",
        ]
        assert metrics["sleep"]["weight"] == 1.0
        assert metrics["sleep"]["counts_as_core"] is True
        assert metrics["hrv_ms"]["baseline_days"] == 28
        assert metrics["hrv_ms"]["min_readings"] == 7
        assert metrics["hrv_ms"]["role"] == "device"
        assert metrics["rhr_bpm"]["slope"] == 0.5

        definitions = queries.metric_definitions(conn)
        assert definitions["sleep"]["higher_is_better"] == 1
        assert definitions["sleep"]["source"] == "readiness"
        assert definitions["rhr_bpm"]["higher_is_better"] == 0
        assert definitions["hrv_ms"]["unit"] == "ms"

        effective = queries.readiness_registry_row(conn, "1999-01-01")
        assert effective["registry_id"] == seed["registry_id"]
    finally:
        conn.close()


def test_registry_is_append_only(tmp_path):
    conn = _connect(tmp_path)
    try:
        db.migrate(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE readiness_registry SET note = 'changed'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM readiness_registry")
    finally:
        conn.close()


def test_versions_are_date_effective_and_listed(tmp_path):
    conn = _connect(tmp_path)
    try:
        db.migrate(conn)
        version_two = repositories.append_readiness_registry(
            conn,
            effective_from="2026-11-25",
            payload_json=json.dumps({"schema_version": 1}),
            note="test version",
        )
        before = queries.readiness_registry_row(conn, "2026-11-24")
        after = queries.readiness_registry_row(conn, "2026-11-25")
        assert before["effective_from"] == "1970-01-01"
        assert after["registry_id"] == version_two
        history = queries.readiness_registry_history(conn)
        assert [row["registry_id"] for row in history][:2] == [version_two, 1]
    finally:
        conn.close()
