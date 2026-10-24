"""Heavy spinal exposure advisory: display-only, RIR-based, no cap effect."""

from __future__ import annotations

import pandas as pd

from strength_coach.features import heavy_spinal


def test_counts_only_high_fatigue_spinal_working_sets_at_or_below_rir_max():
    sets = pd.DataFrame([
        {"date": "2024-01-02", "session_id": "s1", "exercise_id": "trap_bar_deadlift",
         "rir": 1, "is_working_set": True},
        {"date": "2024-01-02", "session_id": "s1", "exercise_id": "trap_bar_deadlift",
         "rir": 2, "is_working_set": True},
        {"date": "2024-01-03", "session_id": "s2", "exercise_id": "trap_bar_deadlift",
         "rir": 0, "is_working_set": True},
        {"date": "2024-01-03", "session_id": "s2", "exercise_id": "competition_bench_press",
         "rir": 1, "is_working_set": True},
        {"date": "2024-01-04", "session_id": "s3", "exercise_id": "trap_bar_deadlift",
         "rir": 0, "is_working_set": False},
    ])
    report = heavy_spinal.compute(
        sets, on_date="2024-01-10",
        config=heavy_spinal.HeavySpinalConfig(window_weeks=4, rir_max=1),
    )
    assert report["total_sets"] == 2
    assert {row["week"] for row in report["weeks"]} == {"2024-W01"}
    assert report["weeks"][0]["exercises"] == {"trap_bar_deadlift": 2}


def test_empty_input_is_zero_not_an_error():
    report = heavy_spinal.compute(
        pd.DataFrame(), on_date="2024-01-10",
        config=heavy_spinal.HeavySpinalConfig(window_weeks=4, rir_max=1),
    )
    assert report["total_sets"] == 0
    assert "advisory" in report["note"].lower()
