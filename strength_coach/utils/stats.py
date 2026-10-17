"""Robust statistics.

Training data has real outliers (a `1015` rep typo, a mis-keyed 200 kg warm-up) and
small samples (40 clean SSB sets). Mean and standard deviation are the wrong tools:
one typo moves a mean by more than a year of real progress moves it. Everything
here is median / MAD based.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# MAD -> sigma consistency factor for normally distributed data.
MAD_TO_SIGMA = 1.4826


def finite(values) -> np.ndarray:
    """Array of finite floats, dropping NaN/inf."""
    array = np.asarray(values, dtype="float64").ravel()
    return array[np.isfinite(array)]


def median(values) -> float:
    array = finite(values)
    if array.size == 0:
        return float("nan")
    return float(np.median(array))


def mad(values, *, scale: bool = True) -> float:
    """Median absolute deviation, optionally scaled to be sigma-comparable."""
    array = finite(values)
    if array.size == 0:
        return float("nan")
    centre = np.median(array)
    raw = float(np.median(np.abs(array - centre)))
    return raw * MAD_TO_SIGMA if scale else raw


def robust_band(
    values,
    *,
    k: float = 2.0,
    min_relative_spread: float = 0.0,
) -> tuple[float, float]:
    """(lower, upper) = median -/+ k * scaled MAD.

    `min_relative_spread` exists because velocity samples are small: with four near
    identical readings the MAD is zero, the band collapses onto the median, and every
    subsequent set trivially "violates" the floor. A floor expressed as a fraction of
    the centre keeps the target achievable while still refusing to invent precision.
    """
    centre = median(values)
    spread = mad(values)
    if math.isnan(centre):
        return (float("nan"), float("nan"))
    if math.isnan(spread):
        spread = 0.0
    if min_relative_spread > 0:
        spread = max(spread, abs(centre) * min_relative_spread)
    return (centre - k * spread, centre + k * spread)


def robust_lower(values, *, k: float = 2.0, min_relative_spread: float = 0.0) -> float:
    """Lower edge of the robust band — the VBT floor a set must stay above."""
    return robust_band(values, k=k, min_relative_spread=min_relative_spread)[0]


def coefficient_of_variation(values) -> float:
    array = finite(values)
    if array.size == 0:
        return float("nan")
    centre = float(np.median(array))
    if centre == 0:
        return float("nan")
    return mad(array) / abs(centre)


def safe_ratio(numerator: float, denominator: float) -> float:
    """Division that returns NaN instead of ZeroDivisionError.

    Used for ACWR and readiness composites, where a zero denominator means
    'not enough history', not 'infinite load'.
    """
    if denominator is None or numerator is None:
        return float("nan")
    if not np.isfinite(denominator) or denominator == 0:
        return float("nan")
    return float(numerator) / float(denominator)


def pct(part: float, whole: float) -> float:
    """Percentage, NaN-safe."""
    value = safe_ratio(part, whole)
    return float("nan") if math.isnan(value) else value * 100.0


def describe(values) -> dict[str, float]:
    """Compact numeric summary used by the profile tool and run reports."""
    array = finite(values)
    if array.size == 0:
        return {"n": 0}
    return {
        "n": int(array.size),
        "min": float(np.min(array)),
        "median": float(np.median(array)),
        "mean": float(np.mean(array)),
        "max": float(np.max(array)),
        "mad": mad(array),
    }


def group_size_distribution(series: pd.Series) -> pd.Series:
    """Count of groups by size — the test used to tell real sets from duplicates.

    Two-to-five identical rows is what ordinary set structure looks like; a long
    tail of large groups is what duplication looks like.
    """
    return series.value_counts().sort_index()
