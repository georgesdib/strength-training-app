"""Thresholds that change a prescribed load.

Kept separate from the rule document on purpose: the constitution says *what* is acceptable
(RIR 2-3), this file says *how* to turn an e1RM into a number on the bar (increment,
rounding, e1RM window). Both are config; neither belongs in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from strength_coach.utils import paths


@dataclass(frozen=True)
class Thresholds:
    increment_kg: float
    per_exercise_increment_kg: Mapping[str, float]
    rounding: str
    e1rm_window_days: int
    e1rm_source: str
    fatigue_load_multiplier: float
    back_flare_erector_sets: int
    back_flare_erector_added_kg: float
    back_flare_main_rir: int
    session_time_cap_s: int
    proposal_max_set_change: int = 2
    proposal_max_sets: int = 8
    proposal_main_substitution_min_interval_days: int = 42
    test_min_interval_days: int = 28
    test_max_single_min_interval_days: int = 56
    continuity_short_days: int = 14
    continuity_medium_days: int = 28
    continuity_long_days: int = 56
    continuity_medium_multiplier: float = 0.95
    continuity_long_multiplier: float = 0.90
    continuity_rir_bump: int = 1
    source_path: Path = Path()

    def increment_for(self, exercise_id: str) -> float:
        return float(self.per_exercise_increment_kg.get(str(exercise_id), self.increment_kg))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Thresholds":
        source = Path(path or paths.thresholds_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        load = raw.get("load") or {}
        modifiers = raw.get("modifiers") or {}
        testing = raw.get("testing") or {}
        continuity = raw.get("continuity") or {}
        prescription = raw.get("prescription") or {}
        if str(load.get("rounding", "down")) != "down":
            # Rounding up would prescribe a load above the target RIR, so only "down" is
            # implemented; the config value exists to make that a deliberate choice.
            raise ValueError(f"unsupported rounding mode: {load.get('rounding')!r}")
        return cls(
            increment_kg=float(load.get("increment_kg", 2.5)),
            per_exercise_increment_kg=MappingProxyType(
                {str(k): float(v) for k, v in (load.get("per_exercise_increment_kg") or {}).items()}
            ),
            rounding="down",
            e1rm_window_days=int(load.get("e1rm_window_days", 84)),
            e1rm_source=str(load.get("e1rm_source", "best_usable")),
            fatigue_load_multiplier=float(modifiers.get("fatigue_load_multiplier", 0.95)),
            back_flare_erector_sets=int(modifiers.get("back_flare_erector_sets", 3)),
            back_flare_erector_added_kg=float(modifiers.get("back_flare_erector_added_kg", 0)),
            back_flare_main_rir=int(modifiers.get("back_flare_main_rir", 3)),
            session_time_cap_s=int(prescription.get("session_time_cap_s", 4800)),
            proposal_max_set_change=int(prescription.get("proposal_max_set_change", 2)),
            proposal_max_sets=int(prescription.get("proposal_max_sets", 8)),
            proposal_main_substitution_min_interval_days=int(
                prescription.get("proposal_main_substitution_min_interval_days", 42)
            ),
            test_min_interval_days=int(testing.get("min_interval_days", 28)),
            test_max_single_min_interval_days=int(
                testing.get("max_single_min_interval_days", 56)
            ),
            continuity_short_days=int(continuity.get("short_gap_days", 14)),
            continuity_medium_days=int(continuity.get("medium_gap_days", 28)),
            continuity_long_days=int(continuity.get("long_gap_days", 56)),
            continuity_medium_multiplier=float(
                continuity.get("medium_load_multiplier", 0.95)
            ),
            continuity_long_multiplier=float(
                continuity.get("long_load_multiplier", 0.90)
            ),
            continuity_rir_bump=int(continuity.get("rir_bump", 1)),
            source_path=source,
        )


def as_dict(thresholds: Thresholds) -> dict[str, Any]:
    return {
        "increment_kg": thresholds.increment_kg,
        "per_exercise_increment_kg": dict(thresholds.per_exercise_increment_kg),
        "rounding": thresholds.rounding,
        "e1rm_window_days": thresholds.e1rm_window_days,
        "e1rm_source": thresholds.e1rm_source,
        "fatigue_load_multiplier": thresholds.fatigue_load_multiplier,
        "back_flare_erector_sets": thresholds.back_flare_erector_sets,
        "back_flare_erector_added_kg": thresholds.back_flare_erector_added_kg,
        "back_flare_main_rir": thresholds.back_flare_main_rir,
        "session_time_cap_s": thresholds.session_time_cap_s,
        "proposal_max_set_change": thresholds.proposal_max_set_change,
        "proposal_max_sets": thresholds.proposal_max_sets,
        "proposal_main_substitution_min_interval_days":
            thresholds.proposal_main_substitution_min_interval_days,
        "test_min_interval_days": thresholds.test_min_interval_days,
        "test_max_single_min_interval_days": thresholds.test_max_single_min_interval_days,
        "continuity_short_days": thresholds.continuity_short_days,
        "continuity_medium_days": thresholds.continuity_medium_days,
        "continuity_long_days": thresholds.continuity_long_days,
        "continuity_medium_multiplier": thresholds.continuity_medium_multiplier,
        "continuity_long_multiplier": thresholds.continuity_long_multiplier,
        "continuity_rir_bump": thresholds.continuity_rir_bump,
    }
