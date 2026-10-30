"""Tests for raw longitudinal strength trends."""

from __future__ import annotations

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import strength_trend
from strength_coach.store import db, importer


def _store():
    rows = []
    for day, load in (("2024-01-01", "100"), ("2024-01-08", "105"),
                      ("2024-01-15", "110"), ("2024-01-22", "115")):
        rows.append({"Date": day, "Exercise": "Competition Squat",
                     "Weight_Used": load, "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{"Date": day} for day in ("2024-01-01", "2024-01-08",
                                                           "2024-01-15", "2024-01-22")])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_observations_are_raw_and_one_per_session():
    with _store() as store:
        points = strength_trend.observations(
            store.connection, "competition_squat", "2024-01-01", "2024-01-31"
        )
    assert len(points) == 4
    assert [point.date for point in points] == [
        "2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22"
    ]
    assert points[0].estimate.method == "epley_plus_rir"
    assert points[0].estimate.kg == pytest.approx(100 * (1 + 7 / 30))


def test_rolling_median_and_sparse_status():
    with _store() as store:
        points = strength_trend.observations(
            store.connection, "competition_squat", "2024-01-01", "2024-01-31"
        )
    trend = strength_trend.rolling_median(points)
    assert [point.rolling_median_kg for point in trend] == pytest.approx([
        100 * (1 + 7 / 30),
        102.5 * (1 + 7 / 30),
        105 * (1 + 7 / 30),
        110 * (1 + 7 / 30),
    ])
    assert strength_trend.summarize(points[:2])["status"] == "points_only"
    assert strength_trend.summarize(points[:4])["status"] == "limited"
    assert strength_trend.summarize(points[:4])["trend_statement"] is None


def test_series_breaks_are_explicit_not_inferred():
    with _store() as store:
        points = strength_trend.observations(
            store.connection, "competition_squat", "2024-01-01", "2024-01-31"
        )
    assert strength_trend.series_breaks(points) == []
