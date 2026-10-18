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
    session_time_cap_s: int
    source_path: Path = Path()

    def increment_for(self, exercise_id: str) -> float:
        return float(self.per_exercise_increment_kg.get(str(exercise_id), self.increment_kg))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Thresholds":
        source = Path(path or paths.thresholds_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        load = raw.get("load") or {}
        modifiers = raw.get("modifiers") or {}
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
            session_time_cap_s=int(prescription.get("session_time_cap_s", 4800)),
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
        "session_time_cap_s": thresholds.session_time_cap_s,
    }
