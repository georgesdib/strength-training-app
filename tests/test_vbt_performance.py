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


def test_bootstrap_interval_needs_the_descriptive_minimum():
    assert vbt_performance._bootstrap_ci([0.01, 0.02]) is None
