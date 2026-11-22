"""Offline rep segmentation (WP5): fixtures with a known displacement profile."""

from __future__ import annotations

import numpy as np
import pytest

from tools import motion_segmentation as seg

RATE = 100


def _cosine_move(duration_s: float, delta: float) -> np.ndarray:
    """Displacement over one phase: starts and ends at zero velocity, moves by `delta`."""
    steps = max(2, int(round(duration_s * RATE)))
    u = np.linspace(0.0, 1.0, steps, endpoint=False)
    return delta * 0.5 * (1 - np.cos(np.pi * u))


def _profile(reps: int, lower_s: float, lift_s: float, rest_s: float, rom: float):
    """Piecewise displacement for a set of reps, plus the still-rest mask."""
    x: list[float] = [0.0]
    for _ in range(reps):
        descent = _cosine_move(lower_s, rom)
        ascent = _cosine_move(lift_s, -rom)
        x.extend(float(value) for value in x[-1] + descent)
        x.extend(float(value) for value in x[-1] + ascent)
        hold = np.full(max(2, int(round(rest_s * RATE))), x[-1])
        x.extend(float(value) for value in hold)
    return np.asarray(x, dtype="float64")


def _recording(x: np.ndarray, *, axis: str = "vertical", noise: float = 0.0,
               gap_ok: bool = True) -> dict:
    t = np.arange(len(x)) / RATE
    accel = np.gradient(np.gradient(x, 1 / RATE), 1 / RATE)
    if noise:
        accel = accel + np.random.default_rng(7).normal(0, noise, accel.shape)
    samples = []
    for index in range(len(t)):
        a = accel[index]
        samples.append({
            "t": float(t[index]),
            "ax": float(a) if axis == "horizontal" else 0.0,
            "ay": 0.0,
            "az": float(-a) if axis == "vertical" else 0.0,
            "rx": 0.0, "ry": 0.0, "rz": 0.0,
            "gx": 0.0, "gy": 0.0, "gz": -1.0,
        })
    return {
        "schema": 1,
        "methodVersion": "tempo/1",
        "context": {"axis": axis},
        "gap": {"isHealthy": gap_ok, "gaps": 0 if gap_ok else 1, "droppedFraction": 0.0},
        "samples": samples,
    }


def test_three_reps_are_segmented_with_known_phases():
    x = _profile(reps=3, lower_s=1.5, lift_s=0.6, rest_s=0.5, rom=0.4)
    analysis = seg.analyse(_recording(x))

    assert analysis.abstention is None
    assert len(analysis.reps) == 3
    for rep in analysis.reps:
        assert rep.lower_ms == pytest.approx(1500, abs=60)
        assert rep.lift_ms == pytest.approx(600, abs=60)
        assert rep.rom_m == pytest.approx(0.4, abs=0.02)
        assert rep.mean_velocity_mps == pytest.approx(0.4 / 0.6, abs=0.04)


def test_a_pause_inside_a_rep_is_measured_not_split():
    x: list[float] = [0.0]
    descent = _cosine_move(1.2, 0.35)
    x.extend(float(v) for v in x[-1] + descent)
    x.extend([x[-1]] * 60)  # 0.6 s pause at the bottom
    ascent = _cosine_move(0.5, -0.35)
    x.extend(float(v) for v in x[-1] + ascent)
    x.extend([x[-1]] * 40)
    analysis = seg.analyse(_recording(np.asarray(x)))

    assert analysis.abstention is None
    assert len(analysis.reps) == 1
    assert analysis.reps[0].pause_ms >= 400


def test_an_unhealthy_gap_report_abstains():
    x = _profile(reps=2, lower_s=1.0, lift_s=0.5, rest_s=0.4, rom=0.3)
    analysis = seg.analyse(_recording(x, gap_ok=False))
    assert analysis.abstention == "gaps"
    assert not analysis.gap_ok


def test_a_recording_without_samples_abstains():
    analysis = seg.analyse({"samples": [], "gap": {"isHealthy": True}})
    assert analysis.abstention == "no_samples"


def test_a_rest_only_recording_abstains():
    x = np.zeros(RATE * 3)
    analysis = seg.analyse(_recording(x))
    assert analysis.abstention == "no_reps"


def test_horizontal_axis_segments_a_row():
    x = _profile(reps=2, lower_s=1.0, lift_s=0.8, rest_s=0.5, rom=0.5)
    analysis = seg.analyse(_recording(x, axis="horizontal"))
    assert analysis.abstention is None
    assert len(analysis.reps) == 2
    assert analysis.reps[0].rom_m == pytest.approx(0.5, abs=0.03)


def test_compare_reports_bias_and_limits_of_agreement():
    ours = [0.60, 0.58, 0.55, 0.52]
    reference = [0.62, 0.60, 0.57, 0.54]
    result = seg.compare(ours, reference)

    assert result["n"] == 4
    assert result["bias_mps"] == pytest.approx(-0.02, abs=1e-6)
    assert result["sd_mps"] == pytest.approx(0.0, abs=1e-6)
    assert result["loa_low"] == pytest.approx(-0.02, abs=1e-6)
    assert result["mdc95_mps"] == pytest.approx(0.0, abs=1e-6)
    assert result["pearson_r"] == pytest.approx(1.0, abs=1e-3)


def test_compare_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        seg.compare([0.5, 0.4], [0.5])
