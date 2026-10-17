"""Robust statistics: outlier-resistant summaries for small, noisy samples."""

import numpy as np
import pandas as pd
import pytest

from strength_coach.utils import stats


def test_median_resists_a_single_typo():
    """One 1015-rep typo must not move the centre of the distribution."""
    clean = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
    with_typo = clean + [1015]
    assert stats.median(clean) == 5
    assert stats.median(with_typo) == 5


def test_mad_resists_a_single_typo():
    """One 1015-rep typo must not blow up the spread estimate.

    MAD is robust, not invariant: the median shifts slightly when the extra point
    is inserted, so we assert the estimate stays *small*, not that it is identical.
    """
    clean = [0.50, 0.52, 0.48, 0.51, 0.49]
    contaminated = clean + [9.99]
    assert stats.mad(contaminated) < 0.05
    assert stats.mad(contaminated) < 0.1 * 9.99


def test_mad_is_scaled_to_sigma():
    """MAD_TO_SIGMA makes MAD comparable to a standard deviation."""
    values = [1, 2, 3, 4, 5]
    raw = stats.mad(values, scale=False)
    assert stats.mad(values) == raw * stats.MAD_TO_SIGMA


def test_robust_band_is_centred_on_median():
    """MAD needs at least half the points off-centre; 3 of 5 identical gives MAD 0."""
    values = [0.40, 0.50, 0.60, 0.70, 0.80]
    low, high = stats.robust_band(values)
    assert low < 0.60 < high


def test_zero_dispersion_collapses_without_floor():
    """Four identical readings give MAD 0, so the band is a point — a known hazard."""
    low, high = stats.robust_band([0.60, 0.60, 0.60, 0.60])
    assert low == high == 0.60


def test_min_relative_spread_keeps_target_achievable():
    """With a 5% floor, a degenerate sample still yields a usable non-zero-width band."""
    low, high = stats.robust_band([0.60, 0.60, 0.60, 0.60], min_relative_spread=0.05)
    assert low < 0.60 < high
    assert high - low == pytest.approx(2 * 2.0 * 0.60 * 0.05)


def test_robust_lower_tightens_with_tighter_data():
    tight = stats.robust_lower([0.60, 0.60, 0.60, 0.60])
    loose = stats.robust_lower([0.40, 0.60, 0.80, 0.60])
    assert tight > loose


def test_robust_band_handles_single_value():
    low, high = stats.robust_band([0.55])
    assert low == high == 0.55


def test_empty_inputs_are_nan_not_crash():
    assert np.isnan(stats.median([]))
    assert np.isnan(stats.mad([]))
    low, high = stats.robust_band([])
    assert np.isnan(low) and np.isnan(high)


def test_nan_and_inf_are_dropped():
    values = [np.nan, 0.5, np.inf, 0.5, -np.inf]
    assert stats.median(values) == 0.5
    assert stats.finite(values).tolist() == [0.5, 0.5]


def test_safe_ratio_returns_nan_for_zero_denominator():
    """ACWR with no prior week is 'unknown', not infinite."""
    assert np.isnan(stats.safe_ratio(100, 0))
    assert stats.safe_ratio(100, 50) == 2.0


def test_pct_nan_safe():
    assert stats.pct(1, 4) == 25.0
    assert np.isnan(stats.pct(1, 0))


def test_describe_reports_n_and_centre():
    summary = stats.describe([1, 2, 3])
    assert summary["n"] == 3
    assert summary["median"] == 2


def test_group_size_distribution_counts_groups():
    """The test that distinguishes real set structure from duplication."""
    groups = pd.Series([2, 2, 3, 3, 3, 4])
    distribution = stats.group_size_distribution(groups)
    assert distribution.loc[2] == 2
    assert distribution.loc[3] == 3
    assert distribution.loc[4] == 1
