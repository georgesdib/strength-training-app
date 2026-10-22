"""Standardised main-lift ramp sets.

Warm-ups are separate from working sets: they are not counted as volume, not persisted as
clean sets, and not used for e1RM. Their loads are derived from the final working load and
rounded down to the item's increment, so a deload or readiness reduction also updates them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from strength_coach.prescribe import loads
from strength_coach.prescribe.models import PrescriptionItem, WarmupSet
from strength_coach.utils import paths


@dataclass(frozen=True)
class WarmupConfig:
    enabled: bool = True
    percents: tuple[float, ...] = (0.50, 0.70, 0.85)
    reps: tuple[int, ...] = (5, 3, 2)
    apply_to_essential: bool = True
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "WarmupConfig":
        source = Path(path or paths.config_dir("warmup.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        percents = tuple(float(x) for x in raw.get("percents", [0.50, 0.70, 0.85]))
        reps = tuple(int(x) for x in raw.get("reps", [5, 3, 2]))
        if len(percents) != len(reps):
            raise ValueError("warmup percents and reps must have the same length")
        if any(not 0 < p < 1 for p in percents) or any(r <= 0 for r in reps):
            raise ValueError("warmup percents must be in (0, 1) and reps positive")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            percents=percents,
            reps=reps,
            apply_to_essential=bool(raw.get("apply_to_essential", True)),
            source_path=source,
        )


def for_item(
    item: PrescriptionItem, config: WarmupConfig | None = None,
) -> tuple[WarmupSet, ...]:
    """Build ramp sets for a main lift from its final working load."""
    cfg = config or WarmupConfig.load()
    if not cfg.enabled or item.load_kg is None or item.load_kg <= 0:
        return ()
    if cfg.apply_to_essential and not item.essential:
        return ()
    out = []
    for percent, reps in zip(cfg.percents, cfg.reps):
        out.append(WarmupSet(
            percent=percent,
            reps=reps,
            load_kg=loads.round_down(
                item.load_kg * percent, item.rounding_increment_kg
            ),
        ))
    return tuple(out)


def attach(
    items: tuple[PrescriptionItem, ...], config: WarmupConfig | None = None,
) -> tuple[PrescriptionItem, ...]:
    cfg = config or WarmupConfig.load()
    return tuple(replace(item, warmup=for_item(item, cfg)) for item in items)


def refresh(
    items: tuple[PrescriptionItem, ...], config: WarmupConfig | None = None,
) -> tuple[PrescriptionItem, ...]:
    """Rebuild ramps after a load-changing modifier such as a deload."""
    return attach(items, config)
