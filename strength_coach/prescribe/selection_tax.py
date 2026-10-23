"""Ordinal exercise-tax metadata for selection suggestions.

The values are config assumptions, not measurements. Unknown metadata never counts as
"lower tax"; this module only compares configured values.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from strength_coach.utils import paths


@dataclass(frozen=True)
class Tax:
    axial: int
    systemic: int
    skill: int
    rom: int

    def as_dict(self) -> dict:
        return {
            "axial": self.axial, "systemic": self.systemic,
            "skill": self.skill, "rom": self.rom,
        }

    def mandatory(self, essential: bool) -> tuple[int, int, int]:
        if essential:
            return (self.axial, self.systemic, self.skill)
        return (self.axial, self.skill)

    @property
    def high(self) -> bool:
        return self.axial >= 2 or self.systemic >= 3 or self.skill >= 3


@dataclass(frozen=True)
class TaxConfig:
    exercises: dict[str, Tax]
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "TaxConfig":
        source = Path(path or paths.config_dir("selection-tax.v1.yaml"))
        if not source.exists():
            return cls({}, source)
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        out = {}
        for exercise_id, values in (raw.get("exercises") or {}).items():
            try:
                tax = Tax(
                    axial=int(values["axial"]), systemic=int(values["systemic"]),
                    skill=int(values["skill"]), rom=int(values["rom"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if all(1 <= value <= 3 for value in tax.as_dict().values()):
                out[str(exercise_id)] = tax
        return cls(out, source)

    def for_exercise(self, exercise_id: str) -> Tax | None:
        return self.exercises.get(str(exercise_id))


def lower_tax(
    current: Tax | None, candidate: Tax | None, *, essential: bool,
) -> tuple[bool, str]:
    """True when candidate is no worse on mandatory axes and better on at least one."""
    if current is None or candidate is None:
        return False, "tax metadata unknown"
    left = current.mandatory(essential)
    right = candidate.mandatory(essential)
    if any(r > l for l, r in zip(left, right)):
        return False, "candidate is not lower-tax on a mandatory axis"
    if not any(r < l for l, r in zip(left, right)):
        return False, "candidate is not lower on any mandatory axis"
    rom = ""
    if candidate.rom > current.rom:
        rom = "; ROM is larger and should be reviewed"
    return True, "lower axial/systemic/skill load" + rom
