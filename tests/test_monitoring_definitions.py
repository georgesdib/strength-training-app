"""Tests for pure monitoring definitions."""

from __future__ import annotations

import pandas as pd
import pytest

from strength_coach.features import exposure, monitoring


def frame(rows):
    return pd.DataFrame(rows)


def row(**overrides):
    values = {
        "set_id": 1,
        "session_id": "s1",
        "date": "2026-01-01",
        "exercise_id": "squat",
        "load_kg": 80.0,
        "load_basis": "external",
        "total_load_kg": 80.0,
        "reps": 5,
        "reps_unit": "reps",
        "rir": 2,
        "is_working_set": True,
        "tonnage_kg": 400.0,
        "velocity_present": True,
        "velocity_mps": 0.5,
    }
    values.update(overrides)
    return values


def test_monitoring_config_loads_the_display_parameters():
    cfg = monitoring.MonitoringConfig.load()

    assert cfg.recent_observations == 3
    assert cfg.recent_max_age_days == 84
    assert cfg.relative_bands["heavy"] == 0.80
    assert cfg.relative_bands["very_light"] == 0.0
    assert cfg.comparability_min_overlap == 0.50


def test_completion_reps_and_tonnage_exclude_warmups():
    data = frame(
        [
            row(set_id=1),
            row(set_id=2, reps=3, rir=1, tonnage_kg=240.0),
            row(set_id=3, is_working_set=False, rir=6, reps=10, tonnage_kg=500.0),
        ]
    )

    assert monitoring.completed_working_sets(data, "s1") == 2
    assert monitoring.completed_reps(data, "s1") == 8
    assert monitoring.exercise_tonnage(data, "squat") == 640.0
    assert monitoring.hard_sets(data, exposure.ExposureConfig(effort_max_rir=4)) == 2
    assert monitoring.near_failure_sets(data) == 2


def test_missing_reps_or_tonnage_is_unavailable_not_zero():
    missing_reps = frame([row(reps=None)])
    missing_tonnage = frame([row(tonnage_kg=None)])

    assert isinstance(monitoring.completed_reps(missing_reps, "s1"), monitoring.Unavailable)
    assert isinstance(monitoring.exercise_tonnage(missing_tonnage, "squat"), monitoring.Unavailable)


def test_rir_distribution_counts_missing_and_warmup():
    result = monitoring.rir_distribution(
        frame([row(rir=0), row(rir=5), row(rir=None), row(rir=6)])
    )

    assert result["0"] == 1
    assert result["5"] == 1
    assert result["missing"] == 1
    assert result["warmup"] == 1


def test_relative_intensity_and_bands():
    base = {"squat": 100.0}
    data = frame(
        [
            row(set_id=1, load_kg=80.0),
            row(set_id=2, load_kg=75.0),
            row(set_id=3, load_kg=65.0),
            row(set_id=4, load_kg=50.0),
            row(set_id=5, load_kg=None),
        ]
    )

    assert monitoring.relative_intensity(row(load_kg=80.0), 100.0) == 0.8
    result = monitoring.relative_intensity_distribution(data, base)
    assert result["heavy"] == 1
    assert result["moderate"] == 1
    assert result["light"] == 1
    assert result["very_light"] == 1
    assert result["unknown"] == 1
    assert result["n"] == 5


def test_added_load_without_total_is_unavailable_for_relative_intensity():
    result = monitoring.relative_intensity(
        row(load_basis="added", load_kg=20.0, total_load_kg=20.0), 100.0
    )

    assert isinstance(result, monitoring.Unavailable)


def test_session_load():
    assert monitoring.session_load({"srpe": 7, "duration_min": 60}) == 420
    assert isinstance(monitoring.session_load({"srpe": 7}), monitoring.Unavailable)
    assert isinstance(monitoring.session_load({"srpe": 0, "duration_min": 60}), monitoring.Unavailable)


def test_power_exposure_uses_taxonomy_pattern():
    data = frame(
        [
            row(exercise_id="jump_squats", reps=5),
            row(exercise_id="jump_squats", reps=4),
            row(exercise_id="squat"),
        ]
    )
    taxonomy = {"jump_squats": {"pattern": "power_jump"}, "squat": {"pattern": "squat"}}

    result = monitoring.power_exposure(data, taxonomy)

    assert result == {"sets": 2, "reps": 9, "exercises": ["jump_squats"]}


def test_mean_velocity_change_requires_same_load_and_two_sets():
    data = frame(
        [
            row(set_id=1, velocity_mps=0.50, load_kg=100.0),
            row(set_id=2, velocity_mps=0.45, load_kg=100.0),
            row(set_id=3, velocity_mps=0.40, load_kg=90.0),
        ]
    )

    result = monitoring.mean_velocity_change(data, "squat", 100.0)
    missing = monitoring.mean_velocity_change(data, "squat", 80.0)

    assert isinstance(result, monitoring.VelocityChange)
    assert result.n == 2
    assert result.change_mps == pytest.approx(-0.05)
    assert result.change_pct == pytest.approx(-10.0)
    assert isinstance(missing, monitoring.Unavailable)


def test_spinal_summary_is_pass_through_only():
    costs = {"2026-W01": {"cost": 3.0, "exercises": {"squat": 1}}}
    result = monitoring.spinal_summary(costs, "s1")
    empty = monitoring.spinal_summary({}, "s1")

    assert result["weeks"] == costs
    assert result["status"] == "observed"
    assert empty["status"] == "unavailable"


class Catalogue:
    def level(self, exercise_id, dimension):
        assert dimension == "axial_spinal"
        return {"squat": "high", "row": "low"}.get(exercise_id, "unknown")


def test_axial_demand_counts_keep_unknown_separate():
    data = frame(
        [
            row(set_id=1, exercise_id="squat"),
            row(set_id=2, exercise_id="row"),
            row(set_id=3, exercise_id="curl"),
        ]
    )

    result = monitoring.axial_demand_counts(data, Catalogue())

    assert result == {"high": 1, "moderate": 0, "low": 1, "unknown": 1}


def test_pattern_distribution_uses_volume_target_key():
    data = frame([row(exercise_id="squat"), row(exercise_id="bench")])
    taxonomy = {"squat": {"pattern": "squat"}, "bench": {"pattern": "horizontal_push"}}

    result = monitoring.pattern_distribution(data, taxonomy)

    assert result == {"horizontal_push": 1, "squat": 1}
