"""Cascade classification, coverage accounting and the continuity gate."""

from __future__ import annotations

import datetime as dt

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
    summary = metrics.activity_summary(conn, weeks=4, as_of="2026-01-10")

    assert len(summary["weeks"]) == 4  # empty weeks are present, not omitted
    week = next(w for w in summary["weeks"] if w["iso_week"] == "2026-W02")
    assert week["moderate_minutes"] == 30
    assert week["vigorous_minutes"] == 40
    assert week["equivalent_minutes"] == 110
    assert summary["years"]["2026"]["total_minutes"] == 70
    assert summary["rolling"]["7d"]["equivalent_minutes"] == 110


def test_dashboard_card_averages_the_last_four_equivalent_weeks():
    summary = {"weeks": [
        {"workouts": 1, "equivalent_minutes": 999.0},
        {"workouts": 1, "equivalent_minutes": 0.0},
        {"workouts": 2, "equivalent_minutes": 60.0},
        {"workouts": 0, "equivalent_minutes": 0.0},
        {"workouts": 3, "equivalent_minutes": 150.0},
        {"workouts": 1, "equivalent_minutes": 210.0},
        {"workouts": 4, "equivalent_minutes": 90.0},
    ]}

    card = metrics.dashboard_card(summary)

    assert card["average_weekly_minutes"] == 112.5  # last four: 0, 150, 210, 90
    assert card["sessions"] == 12
    assert (card["reference_min"], card["reference_max"]) == (150, 300)


def test_rolling_windows_end_at_as_of_not_at_the_last_workout(conn):
    # Five days ago relative to the anchor: inside the last seven days, and today has no workout.
    _workout(conn, "2026-03-05T18:00:00+00:00", 45, mets=5.0)
    summary = metrics.activity_summary(conn, weeks=4, as_of="2026-03-10")

    assert summary["rolling"]["7d"]["total_minutes"] == 45
    assert summary["rolling"]["28d"]["total_minutes"] == 45

    # A quiet week later, the same workout falls out of the 7-day window without any data change.
    later = metrics.activity_summary(conn, weeks=4, as_of="2026-03-20")
    assert later["rolling"]["7d"]["total_minutes"] == 0
    assert later["rolling"]["28d"]["total_minutes"] == 45
    assert len(later["weeks"]) == 4
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

def _samples(conn, workout, start_iso, count=3):
    start = dt.datetime.fromisoformat(start_iso)
    for offset in range(count):
        at = (start + dt.timedelta(seconds=30 * offset)).isoformat()
        cardio.record_sample(
            conn,
            sample_key=cardio.sample_content_key(
                kind="heart_rate", sampled_at=at, value=120.0,
                unit="count/min", source_bundle_id="Watch",
            ),
            kind="heart_rate",
            sampled_at=at,
            value=120.0,
            unit="count/min",
            source_name="Watch",
            imported_at="2026-11-17T18:00:00+00:00",
            external_workout_id=workout["external_workout_id"],
            association="workout",
        )


def test_hr_values_for_loads_only_the_named_workouts(conn):
    first = _workout(conn, "2026-11-10T08:00:00+00:00", 40, avg_hr=130)
    second = _workout(conn, "2026-11-12T08:00:00+00:00", 40, avg_hr=150)
    _samples(conn, first, "2026-11-10T08:00:00+00:00")
    _samples(conn, second, "2026-11-12T08:00:00+00:00")

    values = metrics.hr_values_for(conn, [first["external_workout_id"]])
    assert set(values) == {first["external_workout_id"]}
    assert len(values[first["external_workout_id"]]) == 3


# --- Longevity assessment -------------------------------------------------

TODAY = "2026-11-18"  # Wednesday; the completed week is 2026-11-09..15


def _assessment(conn, **kwargs):
    return metrics.assessment(conn, as_of=TODAY, **kwargs)


def _vo2max(conn, *, measured_at="2026-11-12T08:00:00+00:00", value=48.0):
    cardio.record_vo2max(
        conn,
        external_id=f"vo2-{measured_at}",
        measured_at=measured_at,
        value=value,
        method="Apple Watch",
        noted_at=measured_at,
    )


def test_adequacy_moderate_week_is_inside_the_reference(conn):
    for day in ("10", "11", "12"):
        _workout(conn, f"2026-11-{day}T08:00:00+00:00", 60, mets=4.0)
    last_week = _assessment(conn)["last_week"]
    assert last_week["equivalent_minutes"] == 180.0
    assert last_week["relation"] == "inside"
    assert last_week["remaining_minutes"] is None
    assert last_week["gate"] == "signal"


def test_adequacy_vigorous_week_reports_the_gap(conn):
    _workout(conn, "2026-11-10T08:00:00+00:00", 40, mets=9.0)
    last_week = _assessment(conn)["last_week"]
    assert last_week["equivalent_minutes"] == 80.0
    assert last_week["relation"] == "below"
    assert last_week["remaining_minutes"] == 70.0


def test_adequacy_combined_week_weights_vigorous_double(conn):
    _workout(conn, "2026-11-10T08:00:00+00:00", 100, mets=4.0)
    _workout(conn, "2026-11-12T08:00:00+00:00", 30, mets=9.0)
    last_week = _assessment(conn)["last_week"]
    assert last_week["moderate_minutes"] == 100.0
    assert last_week["vigorous_minutes"] == 30.0
    assert last_week["equivalent_minutes"] == 160.0
    assert last_week["relation"] == "inside"


def test_adequacy_boundary_is_inclusive(conn):
    _workout(conn, "2026-11-10T08:00:00+00:00", 150, mets=4.0)
    last_week = _assessment(conn)["last_week"]
    assert last_week["equivalent_minutes"] == 150.0
    assert last_week["relation"] == "inside"
    assert last_week["remaining_minutes"] is None


def test_adequacy_abstains_when_classification_is_incomplete(conn):
    _workout(conn, "2026-11-10T08:00:00+00:00", 20, mets=4.0)
    _workout(conn, "2026-11-11T08:00:00+00:00", 200)
    last_week = _assessment(conn)["last_week"]
    assert last_week["classified_share"] < metrics.CLASSIFIED_FLOOR
    assert last_week["gate"] == "insufficient"
    assert last_week["relation"] == "unknown"
    assert last_week["remaining_minutes"] is None


def test_current_week_reports_progress_without_a_relation(conn):
    _workout(conn, "2026-11-10T08:00:00+00:00", 60, mets=4.0)
    _workout(conn, "2026-11-17T08:00:00+00:00", 30, mets=4.0)
    assessment = _assessment(conn)
    assert "relation" not in assessment["current_week"]
    assert assessment["current_week"]["equivalent_minutes"] == 30.0
    assert assessment["current_week"]["days_remaining"] == 4
    assert assessment["last_week"]["relation"] == "below"


def test_vo2max_stale_readings_are_not_current_fitness(conn):
    _vo2max(conn, measured_at="2026-06-01T08:00:00+00:00")
    vo2max = _assessment(conn)["vo2max"]
    assert vo2max["status"] == "stale"
    assert vo2max["age_days"] > metrics.VO2MAX_STALE_DAYS


def test_vo2max_absent_is_not_poor_fitness(conn):
    vo2max = _assessment(conn)["vo2max"]
    assert vo2max["status"] == "absent"
    assert vo2max["value"] is None
    assert vo2max["measured_on"] is None


def test_optional_blocks_are_absent_unless_requested(conn):
    _vo2max(conn)
    assessment = _assessment(conn)
    assert assessment["time_in_zone"] is None
    assert assessment["patterns"] is None
