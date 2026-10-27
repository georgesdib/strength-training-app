"""Weekly undulation: a cycle of rep-scheme layers keyed to the declared week.

Deliberately small. The evidence says undulating and linear periodization are comparable, so
this exists to vary the stimulus and manage fatigue, not to promise extra gains. When no block
anchor is declared there is no week index, and the day templates apply unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import yaml

from strength_coach.utils import paths


class UndulationError(ValueError):
    """The undulation schedule is invalid."""


@dataclass(frozen=True)
class Undulation:
    enabled: bool
    cycle_weeks: int
    weeks: Mapping[int, Mapping[str, str]]

    def for_week(self, week_index: int) -> Mapping[str, str] | None:
        if not self.enabled or self.cycle_weeks <= 0 or week_index < 1:
            return None
        position = ((week_index - 1) % self.cycle_weeks) + 1
        return self.weeks.get(position)

    @classmethod
    def load(cls, path: str | Path | None = None) -> Undulation:
        source = Path(path or paths.undulation_yaml())
        if not source.exists():
            return cls(enabled=False, cycle_weeks=0, weeks=MappingProxyType({}))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        cycle = int(raw.get("cycle_weeks", 0))
        raw_weeks = raw.get("weeks") or {}
        weeks: dict[int, Mapping[str, str]] = {}
        for key, plan in raw_weeks.items():
            week = int(key)
            if not 1 <= week <= cycle:
                raise UndulationError(f"week {week} is outside a {cycle}-week cycle")
            layers = {str(k): str(v) for k, v in (plan or {}).items()}
            bad = set(layers) - {"main", "accessory"}
            if bad:
                raise UndulationError(f"week {week} has unknown layers {sorted(bad)}")
            weeks[week] = MappingProxyType(layers)
        return cls(
            enabled=bool(raw.get("enabled", False)),
            cycle_weeks=cycle,
            weeks=MappingProxyType(weeks),
        )
