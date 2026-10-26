"""9c-3 drop settings overlay."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from strength_coach.prescribe import volume_settings
from strength_coach.prescribe import volume_budget


def _base(tmp_path: Path) -> Path:
    source = Path("config/volume.v1.yaml")
    target = tmp_path / "volume.v1.yaml"
    shutil.copyfile(source, target)
    return target


def test_drop_settings_save_to_the_local_overlay(tmp_path):
    base = _base(tmp_path)
    payload = {
        "enabled": True,
        "competition_confirm_days": 10,
        "max_slots_per_group": 2,
        "technique_minutes": 20,
        "tolerance": 0.2,
        "slots": {
            "horizontal_push": [{
                "exercise_id": "dumbbell_bench_press", "sets": 3,
                "reps_low": 8, "reps_high": 12, "rir_low": 2, "rir_high": 3,
                "rest_s": 90, "load_source": "double_progression",
            }],
        },
    }
    result = volume_settings.save_drop(payload, base_path=base)
    assert result["competition_confirm_days"] == 10
    assert result["max_slots_per_group"] == 2
    assert result["technique_minutes"] == 20
    assert result["high_band"] == pytest.approx(68.4)
    assert (tmp_path / "volume.local.yaml").is_file()
    cfg = volume_budget.BudgetConfig.load(base)
    assert cfg.drop_competition_confirm_days == 10
    assert cfg.drop_slots["horizontal_push"][0]["exercise_id"] == "dumbbell_bench_press"


def test_drop_settings_reject_an_out_of_range_window(tmp_path):
    base = _base(tmp_path)
    with pytest.raises(ValueError, match="confirmation days"):
        volume_settings.save_drop(
            {"enabled": True, "competition_confirm_days": 29}, base_path=base,
        )
    assert not (tmp_path / "volume.local.yaml").exists()


def test_drop_settings_reject_an_unknown_exercise(tmp_path):
    base = _base(tmp_path)
    with pytest.raises(ValueError, match="unknown exercise"):
        volume_settings.save_drop({
            "enabled": True,
            "slots": {
                "horizontal_push": [{
                    "exercise_id": "not_a_lift", "sets": 3,
                    "reps_low": 8, "reps_high": 12, "rir_low": 2, "rir_high": 3,
                    "rest_s": 90, "load_source": "double_progression",
                }],
            },
        }, base_path=base)
    assert not (tmp_path / "volume.local.yaml").exists()
