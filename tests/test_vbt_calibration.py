"""VBT calibration: clean-set filters, the sparsity ladder, and honest refusal.

The failure mode this guards against is a confident-looking target built from four sets. The
ladder must either widen its scope (and say so) or return nothing.
"""

import pytest

from conftest import make_readiness, make_training
from strength_coach.features import derived, vbt_calibration as vbt
from strength_coach.ingest import clean

FAST = {"params": vbt.CalibrationParams()}


def calibrate(rows: list[dict]):
    result = clean.build_clean_sets(make_training(rows), make_readiness([{}]))
    sets = derived.enrich(result.sets)
    return vbt.calibrate(sets)


def bench_day(day: str, n: int, velocity: float = 0.35, rir: str = "2", reps: str = "3"):
    return [
        {
            "Date": day,
            "Exercise": "Competition Bench Press",
            "Weight_Used": "100",
            "Reps_Done": reps,
            "RIR": rir,
            "Avg_velocity": f"{velocity:.6f}",
        }
        for _ in range(n)
    ]


# --- the clean-set filter -------------------------------------------------
def test_warmups_are_excluded():
    """DEC-RIR-01: a warm-up velocity is not a calibration point."""
    result = calibrate(bench_day("2024-01-01", 20, rir="6"))
    assert result.excluded["warmup"] == 20
    assert result.lookup("bench_press", 3) is None


def test_sets_without_velocity_are_excluded():
    rows = bench_day("2024-01-01", 5)
    rows += [dict(r, Avg_velocity="0.000000") for r in bench_day("2024-01-02", 5)]
    result = calibrate(rows)
    assert result.excluded["no_velocity"] == 5


def test_sets_outside_the_effort_window_are_excluded():
    """A hard set (RIR 0) is outside the 2-3 band and must not set the target."""
    result = calibrate(bench_day("2024-01-01", 10, rir="0"))
    assert "no_effort_rating" in result.excluded or result.lookup("bench_press", 3) is None


def trap_bar_days(rir: str):
    """Enough sets across enough sessions to clear the lift-scope thresholds."""
    return [
        {"Date": day, "Exercise": "Competition Deadlift", "Weight_Used": "150",
         "Reps_Done": "3", "RIR": rir, "Avg_velocity": "0.400000"}
        for day in ("2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22")
        for _ in range(6)
    ]


def test_trap_bar_uses_its_own_effort_window():
    """Trap bar is 3-4 by the constitution, so RIR 2 is out of window even though RIR 2 is
    inside the bench window. Without this the trap bar silently would be calibrated against
    its own out-of-spec sets."""
    assert calibrate(trap_bar_days("2")).lookup("trap_bar_deadlift", 3) is None
    assert calibrate(trap_bar_days("3")).lookup("trap_bar_deadlift", 3) is not None


def test_long_sets_are_excluded():
    result = calibrate(bench_day("2024-01-01", 20, reps="12"))
    assert result.excluded["reps_out_of_range"] == 20


# --- the ladder -----------------------------------------------------------
def test_lift_scope_when_enough_data():
    rows = bench_day("2024-01-01", 6) + bench_day("2024-01-08", 6) + bench_day("2024-01-15", 6)
    result = calibrate(rows)
    target = result.lookup("bench_press", 3)
    assert target is not None
    assert target.scope == "lift"
    assert target.n_sets == 18
    assert target.n_sessions == 3


def test_no_target_when_too_few_sessions():
    """Twelve sets in one session is one observation, not twelve."""
    result = calibrate(bench_day("2024-01-01", 12))
    assert result.lookup("bench_press", 3) is None


def test_family_fallback_fills_a_sparse_lift():
    """SSB with 2 sets borrows from the squat family, and says so."""
    ssb = [
        {"Date": d, "Exercise": "Safety Squat Bar", "Weight_Used": "100", "Reps_Done": "3",
         "RIR": "2", "Avg_velocity": "0.450000"}
        for d in ("2024-01-01", "2024-01-08")
    ]
    comp = [
        {"Date": d, "Exercise": "Competition Squat", "Weight_Used": "120", "Reps_Done": "3",
         "RIR": "2", "Avg_velocity": "0.440000"}
        for d in ("2024-01-02", "2024-01-09", "2024-01-16", "2024-01-23")
        for _ in range(7)
    ]
    result = calibrate(ssb + comp)
    target = result.lookup("ssb_squat", 3)
    assert target is not None
    assert target.scope == "family"        # borrowed, and labelled as borrowed


def test_lookup_prefers_lift_over_family():
    ssb = [
        {"Date": d, "Exercise": "Safety Squat Bar", "Weight_Used": "100", "Reps_Done": "3",
         "RIR": "2", "Avg_velocity": "0.450000"}
        for d in ("2024-01-01", "2024-01-08", "2024-01-15")
        for _ in range(5)
    ]
    comp = [
        {"Date": d, "Exercise": "Competition Squat", "Weight_Used": "120", "Reps_Done": "3",
         "RIR": "2", "Avg_velocity": "0.400000"}
        for d in ("2024-01-02", "2024-01-09", "2024-01-16")
        for _ in range(8)
    ]
    result = calibrate(ssb + comp)
    assert result.lookup("ssb_squat", 3).scope == "lift"


# --- target shape ---------------------------------------------------------
def test_target_band_contains_the_median():
    rows = bench_day("2024-01-01", 6) + bench_day("2024-01-08", 6) + bench_day("2024-01-15", 6)
    target = calibrate(rows).lookup("bench_press", 3)
    assert target.velocity_low < target.velocity_median < target.velocity_high


def test_zero_dispersion_cannot_collapse_the_band():
    """Identical velocities give MAD 0; the relative floor keeps the target usable."""
    rows = bench_day("2024-01-01", 6) + bench_day("2024-01-08", 6) + bench_day("2024-01-15", 6)
    target = calibrate(rows).lookup("bench_press", 3)
    assert target.velocity_high > target.velocity_low


def test_targets_are_never_available_for_non_vbt_lifts():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "10",
         "Reps_Done": "12", "RIR": "2", "Avg_velocity": "0.500000"}
        for _ in range(30)
    ]
    result = calibrate(rows)
    assert all(t.exercise_id != "lateral_raise" for t in result.targets)


def test_calibration_is_deterministic():
    rows = bench_day("2024-01-01", 6) + bench_day("2024-01-08", 6) + bench_day("2024-01-15", 6)
    first = calibrate(rows).lookup("bench_press", 3)
    second = calibrate(rows).lookup("bench_press", 3)
    assert first == second


def test_method_version_is_recorded():
    rows = bench_day("2024-01-01", 6) + bench_day("2024-01-08", 6) + bench_day("2024-01-15", 6)
    assert calibrate(rows).lookup("bench_press", 3).method_version == vbt.METHOD_VERSION
