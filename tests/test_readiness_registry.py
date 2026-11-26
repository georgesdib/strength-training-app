"""Readiness registry model and CLI (WP2)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from strength_coach import cli
from strength_coach.features import readiness as readiness_feature
from strength_coach.features import readiness_registry, readiness_score
from strength_coach.store import db, queries, repositories


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


def _add_metric(conn, payload, key="sleep_quality"):
    repositories.append_metric_definition(
        conn, metric_key=key, label="Sleep quality", higher_is_better=True,
        aggregation="last", scale_min=1, scale_max=5, source="readiness",
    )
    payload["metrics"].append({
        "key": key, "role": "core", "enabled": True, "weight": 1.0,
        "baseline_days": 0, "counts_as_core": True, "order": 8,
    })
    return payload


def test_a_registry_added_metric_is_accepted_and_scored(conn):
    payload = _add_metric(conn, _seed_payload(conn))
    readiness_registry.save(conn, payload, effective_from=dt.date.today().isoformat())
    readiness_feature.record_manual(
        conn, dt.date.today().isoformat(),
        {"sleep": 4, "energy": 4, "mood": 4, "stress": 4, "soreness": 4,
         "sleep_quality": 5},
    )
    assessment = readiness_score.compute(conn, dt.date.today().isoformat())
    component = next(c for c in assessment.components if c.field == "sleep_quality")
    assert component.normalised == 1.0


def test_an_unknown_metric_is_rejected(conn):
    with pytest.raises(ValueError, match="not an enabled readiness input"):
        readiness_feature.record_manual(
            conn, dt.date.today().isoformat(), {"vibes": 3},
        )


def test_a_disabled_metric_is_rejected(conn):
    payload = _seed_payload(conn)
    metrics = {metric["key"]: metric for metric in payload["metrics"]}
    metrics["energy"]["enabled"] = False
    payload["require_any_of"] = ["sleep"]
    readiness_registry.save(conn, payload, effective_from=dt.date.today().isoformat())
    with pytest.raises(ValueError, match="not an enabled readiness input"):
        readiness_feature.record_manual(
            conn, dt.date.today().isoformat(), {"energy": 4},
        )
    # The non-score inputs remain accepted.
    readiness_feature.record_manual(
        conn, dt.date.today().isoformat(), {"bodyweight_kg": 80, "wearable_score": 50},
    )


def test_a_new_metric_is_recognised_through_retrieval(conn):
    today = dt.date.today().isoformat()
    payload = _add_metric(conn, _seed_payload(conn))
    payload["min_core_fields"] = 1
    payload["require_any_of"] = ["sleep_quality"]
    readiness_registry.save(conn, payload, effective_from=today)
    readiness_feature.record_manual(conn, today, {"sleep_quality": 4})

    day = queries.readiness_day(conn, today)
    assert day is not None and day["sleep_quality"] == 4
    assert today in queries.readiness_dates(conn, today, today)
    series = queries.readiness_series(conn, today, today, ("sleep_quality",))
    assert series and series[0]["sleep_quality"] == 4
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    history = queries.readiness_history(conn, tomorrow, 7)
    assert any(row["sleep_quality"] == 4 for row in history)

    assessment = readiness_score.compute(conn, today)
    assert assessment.status == "ready"
    assert any(c.field == "sleep_quality" for c in assessment.components)


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda p: p["metrics"][0].update({"weight": float("nan")}), "metrics[0].weight"),
        (lambda p: p["metrics"][0].update({"weight": float("inf")}), "metrics[0].weight"),
        (lambda p: p.update({"wearable_weight": float("nan")}), "wearable_weight"),
        (lambda p: p["metrics"][5].update({"slope": float("inf")}), "metrics[5].slope"),
    ],
)
def test_non_finite_registry_numbers_are_rejected(conn, mutate, field):
    payload = _seed_payload(conn)
    mutate(payload)
    with pytest.raises(readiness_registry.RegistryError) as exc:
        readiness_registry.parse(payload, queries.metric_definitions(conn))
    assert "finite" in str(exc.value)


def test_effective_dates_are_canonical(conn):
    today = dt.date.today()
    basic = today.strftime("%Y%m%d")
    payload = _seed_payload(conn)
    saved = readiness_registry.save(conn, payload, effective_from=basic)
    assert saved.effective_from == today.isoformat()
    loaded = readiness_registry.load(conn, basic)
    assert loaded.registry_id == saved.registry_id
    preview = readiness_registry.preview(conn, payload, on_date=basic)
    assert preview["on_date"] == today.isoformat()


def test_multiple_versions_on_the_same_date_use_the_last_appended(conn):
    today = dt.date.today().isoformat()
    payload = _seed_payload(conn)
    payload["metrics"][0]["weight"] = 1.2
    first = readiness_registry.save(conn, payload, effective_from=today)
    payload["metrics"][0]["weight"] = 1.4
    second = readiness_registry.save(conn, payload, effective_from=today)
    effective = readiness_registry.load(conn, today)
    assert effective.registry_id == second.registry_id
    assert effective.metric("sleep").weight == 1.4
    assert first.registry_id < second.registry_id


def test_cli_rollback_appends_a_new_version(tmp_path):
    path = tmp_path / "coach.db"
    conn = db.connect(path)
    try:
        db.migrate(conn)
        payload = readiness_registry.load(conn, dt.date.today().isoformat()).to_payload()
        payload["metrics"][0]["weight"] = 1.5
        readiness_registry.save(conn, payload, note="v2")
    finally:
        conn.close()

    assert cli.main([
        "--db", str(path), "readiness", "registry", "rollback", "--version", "1",
    ]) == 0
    conn = db.connect(path)
    try:
        effective = readiness_registry.load(conn, dt.date.today().isoformat())
        assert effective.metric("sleep").weight == 1.0
        assert len(readiness_registry.history(conn)) == 3
    finally:
        conn.close()


def _define(conn, **overrides):
    values = dict(
        key="sleep_quality", label="Sleep quality", role="core", weight=1.0,
        scale_min=1, scale_max=5, required=True,
    )
    values.update(overrides)
    return readiness_registry.define_metric(conn, **values)


def test_define_metric_adds_the_definition_and_a_registry_version(conn):
    today = dt.date.today().isoformat()
    registry = _define(conn)
    metric = registry.metric("sleep_quality")
    assert metric is not None
    assert metric.role == "core" and metric.scale_max == 5
    assert metric.weight == 1.0 and metric.counts_as_core is True
    assert "sleep_quality" in registry.require_any_of

    readiness_feature.record_manual(conn, today, {"sleep_quality": 4})
    assessment = readiness_score.compute(conn, today)
    assert any(component.field == "sleep_quality" for component in assessment.components)


def test_define_device_metric_uses_its_baseline(conn):
    registry = _define(
        conn, key="skin_temp", label="Skin temperature", role="device", weight=0.5,
        scale_min=None, scale_max=None, baseline_days=28, min_readings=7, slope=0.5,
        higher_is_better=False, required=False,
    )
    metric = registry.metric("skin_temp")
    assert metric.role == "device"
    assert metric.baseline_days == 28 and metric.min_readings == 7
    assert metric.higher_is_better is False


def test_define_metric_rejects_duplicates_and_bad_arguments(conn):
    _define(conn)
    with pytest.raises(readiness_registry.RegistryError, match="already defined"):
        _define(conn)
    with pytest.raises(readiness_registry.RegistryError, match="lowercase"):
        _define(conn, key="Bad-Key")
    with pytest.raises(readiness_registry.RegistryError, match="scale"):
        _define(conn, key="no_scale", scale_min=None, scale_max=None)
    with pytest.raises(readiness_registry.RegistryError, match="baseline_days"):
        _define(conn, key="device_no_baseline", role="device", scale_min=None,
                scale_max=None, baseline_days=None, required=False)
    with pytest.raises(readiness_registry.RegistryError, match="weight"):
        _define(conn, key="heavy", weight=3.0)
    with pytest.raises(readiness_registry.RegistryError, match="required"):
        _define(conn, key="not_core", counts_as_core=False)


def test_a_failed_define_rolls_back_the_definition(conn):
    before = len(readiness_registry.history(conn))
    with pytest.raises(readiness_registry.RegistryError):
        _define(conn, order=1)
    assert conn.execute(
        "SELECT 1 FROM metric_definition WHERE metric_key = 'sleep_quality'"
    ).fetchone() is None
    assert len(readiness_registry.history(conn)) == before


def test_cli_define_metric(tmp_path):
    path = tmp_path / "coach.db"
    assert cli.main([
        "--db", str(path), "readiness", "registry", "define",
        "--key", "sleep_quality", "--label", "Sleep quality", "--role", "core",
        "--scale-min", "1", "--scale-max", "5", "--weight", "1", "--required",
    ]) == 0
    conn = db.connect(path)
    try:
        registry = readiness_registry.load(conn, dt.date.today().isoformat())
        assert registry.metric("sleep_quality") is not None
    finally:
        conn.close()
