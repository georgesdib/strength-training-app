"""Unit checks for deterministic longitudinal VBT helpers."""

from __future__ import annotations

import statistics

from strength_coach.features import vbt_performance


def test_consecutive_weeks_requires_unbroken_weekly_spacing():
    assert vbt_performance._consecutive_weeks(
        ["2024-01-01", "2024-01-08", "2024-01-15"]
    ) == 3
    assert vbt_performance._consecutive_weeks(
        ["2024-01-01", "2024-01-08", "2024-01-22"]
    ) == 2
    assert vbt_performance._consecutive_weeks([]) == 0


def test_bootstrap_interval_is_deterministic_and_descriptive():
    values = [0.02, -0.01, 0.03, 0.00, -0.02, 0.01]
    first = vbt_performance._bootstrap_ci(values)
    second = vbt_performance._bootstrap_ci(values)
    assert first == second
    assert first is not None
    assert first["resamples"] == vbt_performance.BOOTSTRAP_RESAMPLES
    assert first["level"] == 0.95
    assert first["method"].startswith("deterministic percentile bootstrap")
    assert first["low"] <= statistics.fmean(values) <= first["high"]


def test_cohorts_split_by_comparison_basis():
    base = {
        "exercise_id": "ssb_squat", "scope": "lift", "family": "squat",
        "target_rep_count": 3, "target_rir_low": 2, "target_rir_high": 3,
        "comparison_basis": "line",
    }
    assert vbt_performance._cohort_key(base) != vbt_performance._cohort_key(
        dict(base, comparison_basis="planned")
    )
    assert vbt_performance._basis_for({"comparison_basis": "line_extrapolated"}) == "line"
    assert vbt_performance._basis_for({}) == "median"


def test_a_cohort_reports_its_comparison_basis():
    row = {
        "comparable": True, "delta_mps": 0.01, "delta_pct": 2.0,
        "comparison_basis": "line", "load_conditional": True,
        "exercise_id": "ssb_squat", "scope": "lift",
        "target_rep_count": 3, "target_rir_low": 2, "target_rir_high": 3,
    }
    cohort = vbt_performance._cohort([row])
    assert cohort["fit_method"] == "line"
    assert cohort["comparison_basis"] == "line"
    assert cohort["load_conditional"] is True


def test_bootstrap_interval_needs_the_descriptive_minimum():
    assert vbt_performance._bootstrap_ci([0.01, 0.02]) is None
