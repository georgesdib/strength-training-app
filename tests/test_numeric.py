"""Numeric coercion and the zero-sentinel policy.

The regression this file exists for: an early version reused the *date* null
tokens for numeric columns. That set contains "0", so genuine `RIR = 0`
observations were silently erased — which would have under-reported the very
RIR 0-1 violations the critique rubric is supposed to detect.
"""

import pandas as pd
import pytest

from strength_coach.utils import numeric


def test_rir_zero_is_preserved():
    """RIR 0 is a real observation (true failure), not a sentinel."""
    series = pd.Series(["0", "1", "2", "3"])
    out = numeric.coerce_numeric(series)
    assert out.tolist() == [0.0, 1.0, 2.0, 3.0]


def test_weight_zero_is_preserved():
    """Weight_Used 0 means an unweighted bodyweight movement (DQ-BW-01)."""
    out = numeric.coerce_numeric(pd.Series(["0.000000", "82.5"]))
    assert out.tolist() == [0.0, 82.5]


@pytest.mark.parametrize("token", ["(null)", "", "null", "nan", "-"])
def test_null_tokens_become_nan(token):
    assert pd.isna(numeric.coerce_numeric(pd.Series([token])).iloc[0])


def test_zero_sentinels_applied_per_field():
    """Velocity 0 is 'device off'; bodyweight 0 is 'missing'. Same literal, two meanings."""
    frame = pd.DataFrame({"Avg_velocity": [0.0, 0.62], "Weight_Used": [0.0, 100.0]})
    out = numeric.apply_zero_sentinels(frame)
    assert pd.isna(out["Avg_velocity"].iloc[0])          # sentinel
    assert out["Weight_Used"].iloc[0] == 0.0             # legitimate zero preserved


def test_zero_sentinels_rejects_object_dtype():
    """Guard rail: callers must coerce first, so the policy is never applied to text."""
    frame = pd.DataFrame({"Avg_velocity": ["0.0", "0.6"]})
    with pytest.raises(TypeError, match="coerce_frame"):
        numeric.apply_zero_sentinels(frame)


def test_sentinel_and_valid_sets_are_disjoint():
    assert not (set(numeric.ZERO_IS_MISSING) & set(numeric.ZERO_IS_VALID))


def test_readiness_sentinels_documented_fields():
    """Every readiness field that has no physical zero must be in the sentinel map."""
    for field in ["HRV", "RHR", "Weight", "Fat_Percent"]:
        assert field in numeric.ZERO_IS_MISSING


def test_count_zero_sentinels_ignores_absent_columns():
    frame = pd.DataFrame({"Avg_velocity": [0.0, 0.5], "unrelated": [0, 0]})
    counts = numeric.count_zero_sentinels(frame)
    assert counts == {"Avg_velocity": 1}


def test_coerce_frame_only_touches_named_columns():
    frame = pd.DataFrame({"a": ["1", "2"], "b": ["x", "y"]})
    out = numeric.coerce_frame(frame, ["a"])
    assert out["b"].tolist() == ["x", "y"]
