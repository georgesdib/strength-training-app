"""Age decay for an e1RM estimate or a measured override.

The 84-day window selects a best estimate, but a test from eight weeks ago is not today's
capacity. The decay is bounded and conservative; the rate is an assumption, not a finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
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
        stat = source.stat()
        return _load_stamped(str(source), stat.st_mtime_ns, stat.st_size)

    def factor(self, age_days: float) -> float:
        if not self.apply or age_days <= self.grace_days:
            return 1.0
        weeks = (float(age_days) - self.grace_days) / 7.0
        return max(1.0 - self.max_decay, 1.0 - self.weekly_decay * weeks)


@lru_cache(maxsize=8)
def _load_stamped(source: str, _mtime_ns: int, _size: int) -> DecayConfig:
    """Parse the decay file once per path/mtime/size stamp.

    The decay factor is asked for for every item of every candidate build (899 parses per
    resolver build before this cache). DecayConfig holds only scalars, so one instance can be
    shared by every caller and cannot be mutated. A config edit changes the stamp and
    re-parses; a profile write does not touch the file set and cannot make the values stale.
    """
    path = Path(source)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return DecayConfig(
        apply=bool(raw.get("apply", True)),
        grace_days=float(raw.get("grace_days", 21)),
        weekly_decay=float(raw.get("weekly_decay", 0.01)),
        max_decay=float(raw.get("max_decay", 0.10)),
        source_path=path,
    )


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
