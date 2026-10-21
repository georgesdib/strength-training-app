"""Per-lift readiness: transparent components, missing data handled, VBT optional."""

from __future__ import annotations

import pandas as pd

from strength_coach.features import lift_readiness, vbt_calibration


def frame(rows):
    return pd.DataFrame(rows).assign(date=lambda d: pd.to_datetime(d["date"]))


def rows(day, *, e1rm=100.0, rir=2, velocity=None, reps=5, count=3):
    out = []
    for _ in range(count):
        out.append({
            "date": day, "exercise_id": "ssb_squat", "is_working_set": True,
            "rir": rir, "e1rm_kg": e1rm, "velocity_present": velocity is not None,
            "velocity_mps": velocity, "reps": reps,
        })
    return out


def test_performance_and_rir_move_the_score_below_the_subjective_base():
    report = lift_readiness.compute(
        frame(rows("2024-01-01", rir=2, e1rm=120.0)
              + rows("2024-01-08", rir=0, e1rm=80.0)),
        {"ssb_squat": 0.9},
        "2024-01-09",
    )
    entry = report["ssb_squat"]
    assert entry.score < 0.9
    assert entry.status in {"monitor", "low"}
    assert set(entry.components) >= {"subjective", "e1rm", "rir"}


def test_missing_history_falls_back_to_the_global_base():
    report = lift_readiness.compute(
        pd.DataFrame(), {"ssb_squat": 0.8}, "2024-01-09",
    )
    entry = report["ssb_squat"]
    assert entry.score == 0.8
    assert entry.components == {"subjective": 0.8}
    assert entry.n_sets == 0


def test_a_vbt_calibration_adds_a_velocity_component_when_available():
    target = vbt_calibration.CalibrationTarget(
        exercise_id="ssb_squat", scope="lift", rep_count=5, rir_band=(1, 3),
        velocity_median=0.5, velocity_low=0.45, velocity_high=0.55,
        n_sets=12, n_sessions=3,
    )
    calibration = vbt_calibration.CalibrationResult(
        targets=[target], excluded={}, params={},
    )
    slow = lift_readiness.compute(
        frame(rows("2024-01-08", velocity=0.40)),
        {"ssb_squat": 0.9}, "2024-01-09", calibration=calibration,
    )["ssb_squat"]
    fast = lift_readiness.compute(
        frame(rows("2024-01-08", velocity=0.55)),
        {"ssb_squat": 0.9}, "2024-01-09", calibration=calibration,
    )["ssb_squat"]

    assert "vbt" in slow.components
    assert slow.score < fast.score
