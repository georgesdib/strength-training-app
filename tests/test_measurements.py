"""Periodic measurements: declared direction, plausible range, append-only, CLI + web."""

from __future__ import annotations

import sqlite3

import pytest

from strength_coach import cli
from strength_coach.features import measurements
from strength_coach.store import db, repositories

CONFIG = measurements.MeasurementConfig.load()


def test_the_default_catalogue_has_the_longevity_metrics():
    assert {"vo2max", "grip_strength_kg", "sit_to_stand_5_s",
            "steps_per_day", "sitting_hours_per_day"} <= set(CONFIG.metrics)
    assert CONFIG.metrics["sit_to_stand_5_s"].higher_is_better is False
    assert CONFIG.metrics["vo2max"].higher_is_better is True


def test_recording_declares_the_metric_and_summarises_it():
    with db.Store(":memory:") as store:
        conn = store.connection
        measurements.record(conn, metric_key="vo2max", value=45.2,
                            measured_on="2026-01-10", method="step test")
        measurements.record(conn, metric_key="vo2max", value=47.0,
                            measured_on="2026-03-10", method="step test")
        defined = conn.execute(
            "SELECT higher_is_better, unit FROM metric_definition WHERE metric_key = 'vo2max'"
        ).fetchone()
        row = next(r for r in measurements.summary(conn) if r["key"] == "vo2max")

    assert defined["higher_is_better"] == 1
    assert defined["unit"] == "ml/kg/min"
    assert row["count"] == 2
    assert row["latest_value"] == 47.0
    assert row["change"] == 1.8


def test_an_unknown_metric_is_rejected_with_the_list():
    with db.Store(":memory:") as store, pytest.raises(
        measurements.MeasurementError, match="unknown measurement metric"
    ):
        measurements.record(store.connection, metric_key="bench_1rm", value=100)


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("vo2max", 5, "below the plausible minimum"),
        ("vo2max", 200, "above the plausible maximum"),
        ("sit_to_stand_5_s", -1, "below the plausible minimum"),
    ],
)
def test_implausible_values_are_rejected(key, value, message):
    with db.Store(":memory:") as store, pytest.raises(measurements.MeasurementError, match=message):
        measurements.record(store.connection, metric_key=key, value=value)


def test_a_direction_change_is_refused_after_declaration():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_metric_definition(
            conn, metric_key="vo2max", label="VO2max", higher_is_better=False,
            aggregation="last", unit="ml/kg/min",
        )
        with pytest.raises(measurements.MeasurementError, match="already declared"):
            measurements.record(conn, metric_key="vo2max", value=45)


def test_measurements_are_append_only():
    with db.Store(":memory:") as store:
        conn = store.connection
        measurements.record(conn, metric_key="vo2max", value=45)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE measurement SET value = 50")


def test_cli_logs_and_shows(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main(["--db", str(path), "measure", "--metric", "grip_strength_kg",
                     "--value", "52", "--method", "dynamometer"]) == 0
    out = capsys.readouterr().out
    assert "logged Grip strength: 52 kg" in out

    assert cli.main(["--db", str(path), "measure", "--show"]) == 0
    out = capsys.readouterr().out
    assert "grip_strength_kg" in out
    assert "52 kg on" in out
