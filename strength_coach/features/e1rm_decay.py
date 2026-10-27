"""Age decay for an e1RM estimate or a measured override.

The 84-day window selects a best estimate, but a test from eight weeks ago is not today's
capacity. The decay is bounded and conservative; the rate is an assumption, not a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from strength_coach.utils import paths


@dataclass(frozen=True)
class DecayConfig:
    apply: bool
    grace_days: float
    weekly_decay: float
    max_decay: float
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> DecayConfig:
        source = Path(path or paths.e1rm_decay_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        return cls(
            apply=bool(raw.get("apply", True)),
            grace_days=float(raw.get("grace_days", 21)),
            weekly_decay=float(raw.get("weekly_decay", 0.01)),
            max_decay=float(raw.get("max_decay", 0.10)),
            source_path=source,
        )

    def factor(self, age_days: float) -> float:
        if not self.apply or age_days <= self.grace_days:
            return 1.0
        weeks = (float(age_days) - self.grace_days) / 7.0
        return max(1.0 - self.max_decay, 1.0 - self.weekly_decay * weeks)


def factor(age_days: float, config: DecayConfig | None = None) -> float:
    return (config or DecayConfig.load()).factor(age_days)


def as_dict(config: DecayConfig | None = None) -> dict:
    cfg = config or DecayConfig.load()
    return {
        "apply": cfg.apply,
        "grace_days": cfg.grace_days,
        "weekly_decay": cfg.weekly_decay,
        "max_decay": cfg.max_decay,
    }
