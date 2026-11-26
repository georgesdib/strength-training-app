"""VBT calibration: clean-set filters, the sparsity ladder, and honest refusal.

The failure mode this guards against is a confident-looking target built from four sets. The
ladder must either widen its scope (and say so) or return nothing.
"""


import pytest
from conftest import make_readiness, make_training

from strength_coach.features import derived
from strength_coach.features import vbt_calibration as vbt
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
        {"Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "Reps_Done": "3", "RIR": rir, "Avg_velocity": "0.400000"}
        for day in ("2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22")
        for _ in range(6)
    ]


def test_trap_bar_shares_the_default_window():
    """DEC-WINDOW-01: after the amendment, RIR 2 is in window for the trap bar too."""
    assert calibrate(trap_bar_days("2")).lookup("trap_bar_deadlift", 3) is not None
    assert calibrate(trap_bar_days("3")).lookup("trap_bar_deadlift", 3) is not None


def test_a_per_lift_window_is_a_target_band_not_a_fit_filter(monkeypatch):
    """DEC-RIR-06: the fit band is 0-4; the per-lift window only shapes the stored target."""
    from strength_coach.domain import rir as rir_mod

    monkeypatch.setitem(rir_mod.PER_EXERCISE_RIR_TARGET, "trap_bar_deadlift", (3, 4))
    target = calibrate(trap_bar_days("2")).lookup("trap_bar_deadlift", 3)
    assert target is not None
    assert target.rir_band == (3, 4)


def line_days():
    rows = []
    for day in ("2024-01-01", "2024-01-08", "2024-01-15"):
        for load in (80, 95, 110, 125):
            rows.append({
                "Date": day, "Exercise": "Competition Bench Press",
                "Weight_Used": str(load), "Reps_Done": "3", "RIR": "2",
                "Avg_velocity": f"{1.05 - 0.0045 * load:.6f}",
            })
    return rows


def test_a_load_velocity_line_is_fitted_when_load_varies():
    target = calibrate(line_days()).lookup("bench_press", 3)
    assert target is not None
    assert target.fit_method == "line"
    assert target.velocity_slope == pytest.approx(-0.0045, abs=1e-5)
    assert target.load_min == 80
    assert target.load_max == 125
    assert target.velocity_residual_mad is not None


def test_the_target_is_predicted_at_the_prescribed_load():
    from types import SimpleNamespace

    from strength_coach.prescribe.engine import _target_values

    target = SimpleNamespace(
        fit_method="line", velocity_slope=-0.0045, velocity_intercept=1.05,
        velocity_rir_coef=0.0, velocity_rep_coef=None, velocity_residual_mad=0.01,
        load_min=80, load_max=125, rep_count=3, reps_min=None, reps_max=None,
        rir_band=(2, 3), velocity_median=0.6, velocity_low=0.55, velocity_high=0.65,
    )
    value, low, high, basis = _target_values(
        target, SimpleNamespace(load_kg=100.0, rir_target=2)
    )
    assert basis == "line"
    assert value == pytest.approx(1.05 - 0.45)
    assert low == pytest.approx(value - 0.02)
    assert high == pytest.approx(value + 0.02)

    # Outside the fitted load range the line would be an extrapolation.
    fallback = _target_values(target, SimpleNamespace(load_kg=200.0, rir_target=2))
    assert fallback == (0.6, 0.55, 0.65, "median")


def test_rir_zero_sets_enter_calibration():
    """DEC-RIR-06 / option (a): a test logged as a normal RIR-0 set is calibratable."""
    rows = [
        {
            "Date": day, "Exercise": "Competition Bench Press",
            "Weight_Used": str(load), "Reps_Done": "3", "RIR": "0",
            "Avg_velocity": f"{1.05 - 0.0045 * load:.6f}",
        }
        for day in ("2024-01-01", "2024-01-08", "2024-01-15")
        for load in (80, 95, 110, 125)
    ]
    target = calibrate(rows).lookup("bench_press", 3)
    assert target is not None
    assert target.n_sets == 12
    assert target.fit_method == "line"


def two_and_three_rep_days():
    return [
        {
            "Date": day, "Exercise": "Competition Bench Press",
            "Weight_Used": str(load), "Reps_Done": str(reps), "RIR": "2",
            "Avg_velocity": f"{1.10 - 0.0045 * load - 0.03 * reps:.6f}",
        }
        for day in ("2024-01-01", "2024-01-08", "2024-01-15")
        for load in (80, 95, 110, 125)
        for reps in (2, 3)
    ]


def test_a_missing_rep_count_gets_a_labelled_pooled_target():
    """The 1-rep prescription borrows from the 2- and 3-rep sets via the rep term."""
    target = calibrate(two_and_three_rep_days()).lookup("bench_press", 1)
    assert target is not None
    assert target.fit_method == "pooled"
    assert target.velocity_rep_coef == pytest.approx(-0.03, abs=1e-3)
    assert (target.reps_min, target.reps_max) == (2, 3)
    assert target.n_sets == 24


def test_a_line_at_the_rep_count_wins_over_the_pooled_fallback():
    target = calibrate(two_and_three_rep_days()).lookup("bench_press", 3)
    assert target is not None
    assert target.fit_method == "line"


def test_the_pooled_target_is_predicted_at_the_prescribed_rep_count():
    from types import SimpleNamespace

    from strength_coach.prescribe.engine import _target_values

    target = SimpleNamespace(
        fit_method="pooled", velocity_slope=-0.0045, velocity_intercept=1.10,
        velocity_rir_coef=0.0, velocity_rep_coef=-0.03, velocity_residual_mad=0.01,
        load_min=80, load_max=125, reps_min=2, reps_max=3, rep_count=1,
        rir_band=(2, 3), velocity_median=0.6, velocity_low=0.55, velocity_high=0.65,
    )
    item = SimpleNamespace(load_kg=100.0, rir_target=2)
    value, low, high, basis = _target_values(target, item)
    assert basis == "pooled_extrapolated"      # 1 rep is outside the fitted 2-3
    assert value == pytest.approx(1.10 - 0.45 - 0.03)
    assert low == pytest.approx(value - 0.02)
    assert high == pytest.approx(value + 0.02)

    target.rep_count = 2
    assert _target_values(target, item)[3] == "pooled"


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
    assert target.vbt_family == "squat"
    assert target.velocity_mad is not None


def test_named_hinges_do_not_borrow_from_each_other():
    """Trap bar and sumo have different load-velocity curves, so they are separate families."""
    sumo = [
        {"Date": day, "Exercise": "Competition Deadlift", "Weight_Used": "180",
         "Reps_Done": "3", "RIR": "2", "Avg_velocity": "0.350000"}
        for day in ("2024-01-01", "2024-01-08", "2024-01-15")
        for _ in range(8)
    ]
    trap_bar = [
        {"Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
         "Reps_Done": "3", "RIR": "2", "Avg_velocity": "0.360000"}
        for day in ("2026-09-01", "2026-09-08")
    ]
    result = calibrate(sumo + trap_bar)
    assert result.lookup("sumo_deadlift", 3) is not None
    assert result.lookup("trap_bar_deadlift", 3) is None


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


def _enriched(rows):
    result = clean.build_clean_sets(make_training(rows), make_readiness([{}]))
    return derived.enrich(result.sets)


def test_calibration_cache_hits_identical_content_and_params(monkeypatch):
    frame = _enriched(trap_bar_days("2"))
    calls = 0
    original = vbt._calibrate_uncached

    def counted(sets, *, params=None):
        nonlocal calls
        calls += 1
        return original(sets, params=params)

    monkeypatch.setattr(vbt, "_calibrate_uncached", counted)
    vbt._CALIBRATION_CACHE.clear()
    first = vbt.calibrate(frame)
    second = vbt.calibrate(frame)
    assert calls == 1
    assert first.lookup("trap_bar_deadlift", 3) == second.lookup("trap_bar_deadlift", 3)


def test_calibration_cache_misses_for_frame_params_and_method_version(monkeypatch):
    calls = 0
    original = vbt._calibrate_uncached

    def counted(sets, *, params=None):
        nonlocal calls
        calls += 1
        return original(sets, params=params)

    monkeypatch.setattr(vbt, "_calibrate_uncached", counted)
    vbt._CALIBRATION_CACHE.clear()
    frame = _enriched(trap_bar_days("2"))
    vbt.calibrate(frame)
    changed = _enriched(trap_bar_days("3"))
    vbt.calibrate(changed)
    vbt.calibrate(changed, params=vbt.CalibrationParams(reps_max=7))
    monkeypatch.setattr(vbt, "METHOD_VERSION", "1.0.1")
    vbt.calibrate(changed)
    assert calls == 4


def test_cached_calibration_result_is_isolated_from_caller_mutation():
    frame = _enriched(trap_bar_days("2"))
    vbt._CALIBRATION_CACHE.clear()
    first = vbt.calibrate(frame)
    assert first.targets
    first.targets.clear()
    first.excluded["caller mutation"] = 99
    second = vbt.calibrate(frame)
    assert second.targets
    assert "caller mutation" not in second.excluded
