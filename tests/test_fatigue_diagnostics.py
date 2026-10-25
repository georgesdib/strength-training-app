"""Phase-1 fatigue diagnostics: chronology, metrics and basic sanity."""

from __future__ import annotations

import numpy as np
import pandas as pd

from strength_coach.eval import fatigue_diagnostics as diagnostics


def test_feature_map_excludes_same_day_and_future_loads():
    loads = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        "hard_sets": [2, 5],
    })
    values = diagnostics._feature_map(
        loads, ["2024-01-03"], 42.0
    )
    assert values["2024-01-03"] > 0
    # The same-day set is not available to a forecast made on that date.
    same = diagnostics._feature_map(loads, ["2024-01-02"], 42.0)
    assert same["2024-01-02"] < values["2024-01-03"]


def test_metrics_shape():
    forecasts = [
        diagnostics.Forecast("x", 100.0, 101.0, 1.0, 7, "2024-01-01"),
        diagnostics.Forecast("x", 100.0, 99.0, -1.0, 7, "2024-01-02"),
    ]
    metrics = diagnostics._metrics(forecasts)
    assert metrics["n"] == 2
    assert metrics["mae"] == 1.0
    assert metrics["bias"] == 0.0


