"""Tests for raw longitudinal strength trends."""

from __future__ import annotations

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import strength_trend
from strength_coach.features.strength_observations import RawEstimate
from strength_coach.features.strength_trend import RawObservation
from strength_coach.store import db, importer


def _store():
    rows = []
    for day, load in (("2024-01-01", "100"), ("2024-01-08", "105"),
                      ("2024-01-15", "110"), ("2024-01-22", "115")):
        rows.append({"Date": day, "Exercise": "Competition Squat",
                     "Weight_Used": load, "RIR": "2", "Reps_Done": "5"})
    rows.append({"Date": "2024-02-01", "Exercise": "Competition Squat",
                 "Weight_Used": "120", "RIR": "2", "Reps_Done": "11"})
    training = make_training(rows)
    readiness = make_readiness([{"Date": day} for day in ("2024-01-01", "2024-01-08",
                                                           "2024-01-15", "2024-01-22",
                                                           "2024-02-01")])
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


def test_degraded_observations_are_separate_from_primary():
    with _store() as store:
        primary = strength_trend.observations(
            store.connection, "competition_squat", "2024-01-01", "2024-02-02"
        )
        degraded = strength_trend.degraded_observations(
            store.connection, "competition_squat", "2024-01-01", "2024-02-02"
        )

    assert len(primary) == 4
    assert len(degraded) == 1
    assert degraded[0].estimate.quality == "degraded"
    assert degraded[0].date == "2024-02-01"


def test_session_type_filter_is_applied():
    from strength_coach.store import queries

    with _store() as store:
        session_type = str(queries.sessions(store.connection).iloc[0]["session_type"])
        matching = strength_trend.observations(
            store.connection, "competition_squat", "2024-01-01", "2024-02-02",
            session_type=session_type,
        )
        excluded = strength_trend.observations(
            store.connection, "competition_squat", "2024-01-01", "2024-02-02",
            session_type="not-a-session-type",
        )
    assert matching
    assert excluded == []


def test_include_deloads_filter_is_applied():
    with _store() as store:
        conn = store.connection
        conn.execute("UPDATE session SET flags = ?", ('["deload"]',))
        excluded = strength_trend.observations(
            conn, "competition_squat", "2024-01-01", "2024-02-02",
            include_deloads=False,
        )
        included = strength_trend.observations(
            conn, "competition_squat", "2024-01-01", "2024-02-02",
            include_deloads=True,
        )
    assert excluded == []
    assert included


def test_series_break_detects_alias_and_load_basis_not_equipment():
    estimate = RawEstimate
    first = RawObservation("competition_squat", "s1", "2024-01-01", estimate(
        100, "epley_plus_rir", "ok", "s1", "2024-01-01", "competition_squat", 1,
        100, 100, 5, 2, (),
    ), "external", "Competition Squat")
    second = RawObservation("competition_squat", "s2", "2024-01-08", estimate(
        100, "epley_plus_rir", "ok", "s2", "2024-01-08", "competition_squat", 2,
        100, 100, 5, 2, (),
    ), "bodyweight_total", "Competition Squat (different alias)")
    breaks = strength_trend.series_breaks([first, second])
    assert any("raw exercise identity" in item.reason for item in breaks)
    assert any("load basis" in item.reason for item in breaks)


def test_series_breaks_are_explicit_not_inferred():
    with _store() as store:
        points = strength_trend.observations(
            store.connection, "competition_squat", "2024-01-01", "2024-01-31"
        )
    assert strength_trend.series_breaks(points) == []
