"""Cascade classification, coverage accounting and the continuity gate."""

from __future__ import annotations

import pytest

from strength_coach.features import cardio_metrics as metrics
from strength_coach.store import cardio, db

STRENGTH = "HKWorkoutActivityTypeTraditionalStrengthTraining"
RUN = "HKWorkoutActivityTypeRunning"


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "coach.db")
    db.migrate(connection)
    yield connection
    connection.close()


def _workout(conn, start, minutes, *, mets=None, avg_hr=None, activity=RUN):
    end = (
        __import__("datetime").datetime.fromisoformat(start)
        + __import__("datetime").timedelta(minutes=minutes)
    ).isoformat()
    row, _ = cardio.record_workout(
        conn,
        external_key=cardio.content_key(
            activity_type=activity, started_at=start, ended_at=end, duration_s=minutes * 60
        ),
        origin="export",
        activity_type=activity,
        started_at=start,
        ended_at=end,
        duration_s=minutes * 60,
        source_name="Watch",
        avg_mets=mets,
        avg_heart_rate=avg_hr,
        imported_at="2026-11-17T18:00:00+00:00",
    )
    return row


def test_met_bands_follow_the_who_thresholds():
    assert metrics.classify_met(2.9) == "light"
    assert metrics.classify_met(3.0) == "moderate"
    assert metrics.classify_met(6.0) == "moderate"
    assert metrics.classify_met(6.1) == "vigorous"
    assert metrics.classify_met(None) is None


def test_hr_fallback_uses_observed_maximum():
    assert metrics.classify_hr(127) == "light"        # 0.635 of 200
    assert metrics.classify_hr(140) == "moderate"     # 0.70
    assert metrics.classify_hr(170) == "vigorous"     # 0.85
    assert metrics.classify_hr(None) is None


def test_cascade_prefers_met_and_reports_tier(conn):
    _workout(conn, "2026-01-05T08:00:00+00:00", 30, mets=4.0, avg_hr=170)
    payload = metrics.report(conn)
    year = payload["years"]["2026"]
    assert year["moderate_minutes"] == 30
    assert year["tier_minutes"]["met"] == 30
    assert year["equivalent_minutes"] == 30


def test_unclassified_is_its_own_quantity(conn):
    _workout(conn, "2026-01-06T08:00:00+00:00", 20)
    year = metrics.report(conn)["years"]["2026"]
    assert year["unclassified_minutes"] == 20
    assert year["equivalent_minutes"] == 0
    assert year["classified_share"] == 0


def test_equivalent_minutes_weight_vigorous(conn):
    _workout(conn, "2026-01-07T08:00:00+00:00", 40, mets=9.0)
    _workout(conn, "2026-01-08T08:00:00+00:00", 20, mets=4.0)
    year = metrics.report(conn)["years"]["2026"]
    assert year["vigorous_minutes"] == 40
    assert year["moderate_minutes"] == 20
    assert year["equivalent_minutes"] == 100


def test_resistance_share_is_reported_separately(conn):
    _workout(conn, "2026-01-09T18:00:00+00:00", 60, mets=4.9, activity=STRENGTH)
    _workout(conn, "2026-01-10T08:00:00+00:00", 60, mets=9.0)
    year = metrics.report(conn)["years"]["2026"]
    assert year["resistance_minutes"] == 60
    assert year["resistance_classified_minutes"] == 60
    assert year["moderate_minutes"] == 60
    assert year["vigorous_minutes"] == 60


def test_activity_summary_is_weekly_and_cheap(conn):
    _workout(conn, "2026-01-05T08:00:00+00:00", 30, mets=4.0)
    _workout(conn, "2026-01-06T08:00:00+00:00", 40, mets=9.0)
    summary = metrics.activity_summary(conn, weeks=4)
    assert len(summary["weeks"]) == 1
    week = summary["weeks"][0]
    assert week["iso_week"] == "2026-W02"
    assert week["moderate_minutes"] == 30
    assert week["vigorous_minutes"] == 40
    assert week["equivalent_minutes"] == 110
    assert summary["years"]["2026"]["total_minutes"] == 70
    assert summary["rolling"]["7d"]["equivalent_minutes"] == 110


def test_continuity_admits_dense_series_and_rejects_sparse(conn):
    dense = _workout(conn, "2026-01-11T08:00:00+00:00", 10, mets=9.0)
    sparse = _workout(conn, "2026-01-12T08:00:00+00:00", 120, mets=4.0)
    import datetime as dt

    start = dt.datetime.fromisoformat("2026-01-11T08:00:00+00:00")
    for index in range(300):
        cardio.record_sample(
            conn,
            sample_key=cardio.sample_content_key(
                kind="heart_rate", sampled_at=(start + dt.timedelta(seconds=2 * index)).isoformat(),
                value=150.0, unit="count/min", source_bundle_id="Watch",
            ),
            kind="heart_rate",
            sampled_at=(start + dt.timedelta(seconds=2 * index)).isoformat(),
            value=150.0,
            unit="count/min",
            source_name="Watch",
            imported_at="2026-11-17T18:00:00+00:00",
            external_workout_id=dense["external_workout_id"],
            association="workout",
        )
    sparse_start = dt.datetime.fromisoformat("2026-01-12T08:00:00+00:00")
    for index in range(3):
        cardio.record_sample(
            conn,
            sample_key=cardio.sample_content_key(
                kind="heart_rate",
                sampled_at=(sparse_start + dt.timedelta(minutes=40 * index)).isoformat(),
                value=150.0, unit="count/min", source_bundle_id="Watch",
            ),
            kind="heart_rate",
            sampled_at=(sparse_start + dt.timedelta(minutes=40 * index)).isoformat(),
            value=150.0,
            unit="count/min",
            source_name="Watch",
            imported_at="2026-11-17T18:00:00+00:00",
            external_workout_id=sparse["external_workout_id"],
            association="workout",
        )
    clustered = _workout(conn, "2026-01-13T18:00:00+00:00", 60, mets=4.9, activity=STRENGTH)
    cluster_start = dt.datetime.fromisoformat("2026-01-13T18:00:00+00:00")
    for offset in (0, 5, 10, 15, 3600):
        cardio.record_sample(
            conn,
            sample_key=cardio.sample_content_key(
                kind="heart_rate",
                sampled_at=(cluster_start + dt.timedelta(seconds=offset)).isoformat(),
                value=130.0, unit="count/min", source_bundle_id="Watch",
            ),
            kind="heart_rate",
            sampled_at=(cluster_start + dt.timedelta(seconds=offset)).isoformat(),
            value=130.0,
            unit="count/min",
            source_name="Watch",
            imported_at="2026-11-17T18:00:00+00:00",
            external_workout_id=clustered["external_workout_id"],
            association="workout",
        )

    payload = metrics.report(conn)
    # dense + sparse rejected; the clustered series has a small median gap but a one-hour hole.
    assert payload["time_in_zone"]["eligible_workouts"] == 1
    assert payload["time_in_zone"]["eligible_by_year"] == {"2026": 1}
    assert payload["time_in_zone"]["minutes_by_year"]["2026"]["moderate"] == 10
