"""Numeric coercion plus one documented missing-value policy.

The trap this module exists to prevent: the same literal `0` means different
things in different columns of the same export.

  * `Avg_velocity = 0.000000`  -> "the device was not used"  (2/3 of all rows)
  * `TUT = 0`, `Avg_rom = 0`   -> same: the whole telemetry block is absent
  * `Reps_Done = 0`            -> should not occur; if it does, it is an error
  * readiness `Weight = 0.0`   -> missing (a 0 kg bodyweight is impossible)
  * readiness `HRV = 0`        -> missing (0 ms is incompatible with life)
  * readiness `RHR = 0`        -> missing (0 bpm is a corpse)
  * readiness `Sleep = 0`      -> impossible: the 1-5 scales have no zero bucket

So sentinel handling is per-field, never global. Every caller must name its fields.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

# Text tokens that mean "no value" in a numeric column.
#
# Deliberately does NOT reuse `dates.NULL_DATE_TOKENS`, because that set contains
# "0" (a legitimate null *date* placeholder) while 0 is a real, meaningful value in
# numeric columns: RIR 0 is genuine failure, and Weight_Used 0 means an unweighted
# bodyweight movement. Reusing the date tokens here silently erased genuine
# `RIR = 0` observations into NaN — found by tools/profile_data.py on first run.
NULL_NUMERIC_TOKENS: frozenset[str] = frozenset(
    {"(null)", "", "null", "NULL", "None", "none", "NaN", "nan", "-"}
)

# Fields where a physical 0 is impossible, so 0 can only be a sentinel.
# Keyed by the exact column name used in the raw CSVs.
ZERO_IS_MISSING: dict[str, str] = {
    # training log
    "Avg_velocity": "0.000000 encodes 'VBT device not used', not 'zero velocity'",
    "Avg_power": "absent telemetry block",
    "Avg_rom": "absent telemetry block",
    "TUT": "absent telemetry block",
    # readiness
    "HRV": "0 ms is physiologically impossible",
    "RHR": "0 bpm is physiologically impossible",
    "Weight": "0 kg bodyweight impossible; real values are always positive",
    "Fat_Percent": "0% body fat is impossible",
    "Squat_Readiness": "1-5 scale has no zero bucket",
    "Bench_Readiness": "1-5 scale has no zero bucket",
    "Deadlift_Readiness": "1-5 scale has no zero bucket",
}

# Fields where 0 is a legitimate observation and must be preserved.
ZERO_IS_VALID: frozenset[str] = frozenset(
    {
        "RIR",  # 0 RIR = true failure; its *reliability* is a data question (Q2),
        #        but 0 is not a sentinel and must not be erased here.
        "Weight_Used",  # 0 = unweighted bodyweight movement (DQ-BW-01)
        "ExertionLoad",
        "Form",
        "Fatigue",
    }
)


def coerce_numeric(series: pd.Series, *, strip: bool = True) -> pd.Series:
    """Text -> float, mapping every known null token to NaN. Never silently fills."""
    text = series.astype(str)
    if strip:
        text = text.str.strip()
    text = text.where(~text.isin(NULL_NUMERIC_TOKENS))
    return pd.to_numeric(text, errors="coerce")


def coerce_frame(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Return a copy with the named columns coerced to float64."""
    out = frame.copy()
    for column in columns:
        if column in out.columns:
            out[column] = coerce_numeric(out[column])
    return out


def apply_zero_sentinels(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace 0 with NaN in every column listed in `ZERO_IS_MISSING`.

    Expects already-coerced numeric columns — call `coerce_frame` first. Only
    columns present in the frame are touched, so the same function serves both the
    training log and the readiness file.
    """
    out = frame.copy()
    for column in ZERO_IS_MISSING:
        if column not in out.columns:
            continue
        assert column not in ZERO_IS_VALID, f"{column} is both valid-zero and sentinel"
        if not pd.api.types.is_numeric_dtype(out[column]):
            raise TypeError(
                f"apply_zero_sentinels needs numeric {column!r}; "
                f"got {out[column].dtype}. Run coerce_frame first."
            )
        out[column] = out[column].where(out[column] != 0, other=pd.NA)
    return out


def count_zero_sentinels(frame: pd.DataFrame) -> dict[str, int]:
    """Per-column count of zero values that will be treated as missing (for reports)."""
    counts: dict[str, int] = {}
    for column in ZERO_IS_MISSING:
        if column in frame.columns:
            counts[column] = int((frame[column] == 0).sum())
    return counts


def is_within_numeric(series: pd.Series, low: float, high: float, *, inclusive: bool = True) -> pd.Series:
    if inclusive:
        return series.between(low, high)
    return (series > low) & (series < high)
