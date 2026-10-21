"""Return-to-training calibration: enough data uses it, sparse data keeps fixed bands."""

from __future__ import annotations

import pandas as pd

from strength_coach.features import continuity_calibration as cc


def frame(returns):
    rows = []
    for index, (gap, ratio) in enumerate(returns):
        start = pd.Timestamp("2024-01-01")
        rows.append({
            "exercise_id": f"lift_{index}",
            "date": start,
            "e1rm_kg": 100.0,
            "is_working_set": True,
        })
        rows.append({
            "exercise_id": f"lift_{index}",
            "date": start + pd.Timedelta(days=gap),
            "e1rm_kg": 100.0 * ratio,
            "is_working_set": True,
        })
    return pd.DataFrame(rows)


def config(**overrides):
    values = dict(
        enabled=True, apply=True, min_returns_per_band=3, min_total_returns=9,
        max_gap_days=365, min_ratio=0.5, max_ratio=1.5,
        bootstrap_samples=200, confidence=0.95, max_ci_width=0.15,
        factor_floor=0.85, allow_relax_fixed=True, seed=7,
    )
    values.update(overrides)
    return cc.CalibrationConfig(**values)


def compute(frame_value, config_value):
    return cc.compute(
        frame_value, short_days=14, medium_days=28, long_days=56,
        medium_multiplier=0.95, long_multiplier=0.90, config=config_value,
    )


def test_enough_returns_use_the_band_medians():
    returns = [(14, 0.98)] * 3 + [(28, 0.94)] * 3 + [(56, 0.90)] * 3
    result = compute(frame(returns), config())
    assert result.n_total == 9
    assert result.applied is True
    assert result.bands["short"].factor == 0.98
    assert result.bands["medium"].factor == 0.94
    assert result.bands["long"].factor == 0.90
    assert all(result.bands[b].status == "ok" for b in ("short", "medium", "long"))


def test_sparse_returns_keep_the_fixed_rule():
    returns = [(14, 0.98)] + [(28, 0.94)] + [(56, 0.90)]
    result = compute(frame(returns), config())
    assert result.n_total == 3
    assert result.applied is False
    assert result.bands["short"].factor == 1.0
    assert result.bands["medium"].factor == 0.95
    assert result.bands["long"].factor == 0.90
    assert all(result.bands[b].status == "insufficient" for b in result.bands)


def test_a_wide_interval_keeps_the_fixed_rule():
    returns = [(28, 0.85), (28, 1.05), (28, 0.90)] * 1
    result = compute(frame(returns), config(min_returns_per_band=3, min_total_returns=3,
                                            max_ci_width=0.01))
    assert result.bands["medium"].factor == 0.95
    assert result.bands["medium"].status == "uncertain"


def test_allow_relax_fixed_is_written_without_dropping_the_config(tmp_path):
    path = tmp_path / "continuity.yaml"
    path.write_text("enabled: true\nallow_relax_fixed: true  # comment\n")
    cfg = cc.save_allow_relax_fixed(False, path=path)
    assert cfg.allow_relax_fixed is False
    text = path.read_text()
    assert "allow_relax_fixed: false" in text
    assert "enabled: true" in text
