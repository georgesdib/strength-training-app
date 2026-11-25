"""Readiness registry model and CLI (WP2)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from strength_coach import cli
from strength_coach.features import readiness_registry
from strength_coach.store import db, queries


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "coach.db")
    db.migrate(connection)
    yield connection
    connection.close()


def _seed_payload(conn) -> dict:
    registry = readiness_registry.load(conn, "2026-11-25")
    assert registry is not None
    return registry.to_payload()


def _with(**changes) -> dict:
    return changes


def test_seed_loads_with_definition_metadata(conn):
    registry = readiness_registry.load(conn, "2026-11-25")
    assert registry is not None
    assert registry.registry_id == 1
    assert registry.effective_from == "1970-01-01"
    assert registry.min_core_fields == 3
    assert registry.require_any_of == ("sleep", "energy")
    assert registry.wearable_weight == 0.1
    assert [metric.key for metric in registry.metrics] == [
        "sleep", "energy", "mood", "stress", "soreness", "hrv_ms", "rhr_bpm",
    ]
    sleep = registry.metric("sleep")
    assert sleep.role == "core" and sleep.weight == 1.0 and sleep.enabled
    assert sleep.label == "Sleep" and sleep.scale_min == 1 and sleep.scale_max == 5
    hrv = registry.metric("hrv_ms")
    assert hrv.role == "device" and hrv.baseline_days == 28
    assert hrv.min_readings == 7 and hrv.slope == 0.5


def test_default_seed_reparses(conn):
    payload = _seed_payload(conn)
    parsed = readiness_registry.parse(payload, queries.metric_definitions(conn))
    assert parsed.to_payload() == payload


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda p: p["metrics"].append({**p["metrics"][0], "key": "banana", "order": 9}),
         "metrics[7].key"),
        (lambda p: p["metrics"][1].update({"key": "sleep"}), "metrics"),
        (lambda p: p["metrics"][0].update({"weight": 2.5}), "metrics[0].weight"),
        (lambda p: p["metrics"][5].update({"weight": 1.5}), "metrics[5].weight"),
        (lambda p: p["metrics"][0].update({"weight": 0}), "metrics[0].weight"),
        (lambda p: p.update({"min_core_fields": 6}), "min_core_fields"),
        (lambda p: p.update({"require_any_of": ["banana"]}), "require_any_of"),
        (lambda p: p["metrics"][5].update({"baseline_days": 0}), "metrics[5].baseline_days"),
        (lambda p: p["metrics"][0].update({"baseline_days": 28}), "metrics[0].baseline_days"),
        (lambda p: p.update({"schema_version": 2}), "schema_version"),
        (lambda p: p.update({"wearable_weight": 0.6}), "wearable_weight"),
    ],
)
def test_validation_rejects(conn, mutate, field):
    payload = _seed_payload(conn)
    mutate(payload)
    with pytest.raises(readiness_registry.RegistryError) as exc:
        readiness_registry.parse(payload, queries.metric_definitions(conn))
    assert field in str(exc.value) or field in exc.value.fields


def test_save_appends_and_is_date_effective(conn):
    payload = _seed_payload(conn)
    payload["metrics"][0]["weight"] = 2.0
    today = dt.date.today().isoformat()
    saved = readiness_registry.save(conn, payload, note="test edit")
    assert saved.registry_id == 2
    assert saved.effective_from == today
    effective = readiness_registry.load(conn, today)
    assert effective.metric("sleep").weight == 2.0
    before = readiness_registry.load(conn, "2026-11-24")
    assert before.metric("sleep").weight == 1.0


def test_save_rejects_backdating(conn):
    payload = _seed_payload(conn)
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with pytest.raises(readiness_registry.RegistryError):
        readiness_registry.save(conn, payload, effective_from=yesterday)


def test_preview_reports_the_diff(conn):
    payload = _seed_payload(conn)
    payload["metrics"][0]["weight"] = 1.5
    result = readiness_registry.preview(conn, payload)
    assert result["ok"] is True
    assert any("sleep.weight: 1.0 -> 1.5" in line for line in result["changes"])


def test_cli_lists_shows_sets_and_previews(conn, tmp_path, capsys):
    db_path = tmp_path / "cli.db"
    assert cli.main(["--db", str(db_path), "readiness", "registry", "list"]) == 0
    output = capsys.readouterr().out
    assert "1970-01-01" in output

    assert cli.main(["--db", str(db_path), "readiness", "registry", "show",
                     "--date", "2026-11-25"]) == 0
    output = capsys.readouterr().out
    assert "sleep" in output and "hrv_ms" in output

    payload = _seed_payload(conn)
    payload["metrics"][0]["weight"] = 1.5
    payload_file = tmp_path / "registry.json"
    payload_file.write_text(json.dumps(payload), encoding="utf-8")

    assert cli.main(["--db", str(db_path), "readiness", "registry", "preview",
                     "--file", str(payload_file)]) == 0
    output = capsys.readouterr().out
    assert "sleep.weight: 1.0 -> 1.5" in output

    assert cli.main(["--db", str(db_path), "readiness", "registry", "set",
                     "--file", str(payload_file), "--note", "cli edit"]) == 0
    output = capsys.readouterr().out
    assert "version 2" in output

    invalid = _seed_payload(conn)
    invalid["metrics"][0]["weight"] = 9
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text(json.dumps(invalid), encoding="utf-8")
    assert cli.main(["--db", str(db_path), "readiness", "registry", "preview",
                     "--file", str(invalid_file)]) == 2
    assert "out of bounds" in capsys.readouterr().out
