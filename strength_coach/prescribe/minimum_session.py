"""Minimum effective session: a volume-only, user-selected fallback.

This is not a fatigue model and never changes load, RIR or exercise identity. It removes
non-essential accessory work first; the deeper tier reduces main-lift sets to a floor. It is
applied after the automatic modifiers, so it can only take work away.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

import yaml

from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.utils import paths

MODIFIER = "MOD-MIN-001"


@dataclass(frozen=True)
class MinimumSessionConfig:
    targets_minutes: tuple[int, ...] = (30, 45, 60)
    default_target_minutes: int = 45
    accessory_floor_sets: int = 1
    main_lift_floor_sets: int = 2
    set_seconds: int = 30
    warmup_set_seconds: int = 30

    @classmethod
    def load(cls, path: str | Path | None = None) -> "MinimumSessionConfig":
        source = Path(path or paths.config_dir("minimum-session.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        targets = tuple(int(value) for value in (raw.get("targets_minutes") or (30, 45, 60)))
        default = int(raw.get("default_target_minutes") or 45)
        if not targets or any(value <= 0 for value in targets):
            raise ValueError("minimum-session targets must be positive")
        if default not in targets:
            raise ValueError("default_target_minutes must be one of targets_minutes")
        return cls(
            targets_minutes=targets,
            default_target_minutes=default,
            accessory_floor_sets=max(1, int(raw.get("accessory_floor_sets", 1))),
            main_lift_floor_sets=max(1, int(raw.get("main_lift_floor_sets", 2))),
            set_seconds=max(1, int(raw.get("set_seconds", 30))),
            warmup_set_seconds=max(1, int(raw.get("warmup_set_seconds", 30))),
        )


def estimate_minutes(items: Iterable[PrescriptionItem],
                     config: MinimumSessionConfig | None = None) -> float:
    """Planning estimate from sets, rests and warm-up sets. Not a measured duration."""
    cfg = config or MinimumSessionConfig.load()
    total = 0.0
    for item in items:
        rest = float(item.rest_s or 0)
        total += int(item.sets) * (cfg.set_seconds + rest)
        total += len(item.warmup) * cfg.warmup_set_seconds
    return round(total / 60.0, 1)


def _available(items: list[PrescriptionItem]) -> tuple[bool, str | None]:
    for item in items:
        if item.load_kg is None or item.unknown_load_reason:
            return False, f"{item.exercise_id} has no executable load"
    return True, None


def _change(item: PrescriptionItem, sets: int) -> PrescriptionItem:
    return replace(
        item,
        sets=int(sets),
        rationale_refs=tuple(item.rationale_refs) + (MODIFIER,),
    )


def apply(items: Iterable[PrescriptionItem], *, target_minutes: int,
          include_main: bool = False,
          config: MinimumSessionConfig | None = None) -> dict[str, Any]:
    """Return items and a provenance note. Never adds work or changes load/RIR."""
    cfg = config or MinimumSessionConfig.load()
    if target_minutes not in cfg.targets_minutes:
        raise ValueError(f"target_minutes must be one of {cfg.targets_minutes}")
    current = list(items)
    before = estimate_minutes(current, cfg)
    available, reason = _available(current)
    if not available:
        return {
            "requested": True, "applied": False, "status": "unavailable",
            "reason": reason, "target_minutes": target_minutes,
            "include_main": include_main, "before_minutes": before,
            "after_minutes": before, "removed_sets": 0, "removed_exercises": [],
            "items": tuple(current),
        }
    if before <= target_minutes:
        return {
            "requested": True, "applied": False, "status": "already_short",
            "reason": f"estimated {before:g} min is already within {target_minutes} min",
            "target_minutes": target_minutes, "include_main": include_main,
            "before_minutes": before, "after_minutes": before,
            "removed_sets": 0, "removed_exercises": [],
        }

    after = list(current)
    removed_sets = 0
    removed_exercises: list[str] = []
    # Accessory-only tier: reduce optional work to one set, then remove optional exercises.
    for index in range(len(after) - 1, -1, -1):
        item = after[index]
        if item.essential:
            continue
        floor = cfg.accessory_floor_sets
        if item.sets > floor:
            new_sets = floor
            removed_sets += item.sets - new_sets
            after[index] = _change(item, new_sets)
            if estimate_minutes(after, cfg) <= target_minutes:
                break
    if estimate_minutes(after, cfg) > target_minutes:
        for index in range(len(after) - 1, -1, -1):
            item = after[index]
            if item.essential:
                continue
            removed_exercises.append(item.exercise_id)
            removed_sets += int(item.sets)
            del after[index]
            if estimate_minutes(after, cfg) <= target_minutes:
                break

    if include_main and estimate_minutes(after, cfg) > target_minutes:
        for index in range(len(after) - 1, -1, -1):
            item = after[index]
            if not item.essential:
                continue
            if item.sets > cfg.main_lift_floor_sets:
                removed_sets += item.sets - cfg.main_lift_floor_sets
                after[index] = _change(item, cfg.main_lift_floor_sets)
                if estimate_minutes(after, cfg) <= target_minutes:
                    break

    final = estimate_minutes(after, cfg)
    if final > target_minutes:
        status = "partial"
        note_reason = (
            f"floors reached at an estimated {final:g} min; target {target_minutes} min"
        )
    else:
        status = "applied"
        note_reason = (
            f"estimated {before:g} -> {final:g} min; target {target_minutes} min"
        )
    return {
        "requested": True,
        "applied": bool(removed_sets or removed_exercises),
        "status": status,
        "reason": note_reason,
        "target_minutes": target_minutes,
        "include_main": include_main,
        "before_minutes": before,
        "after_minutes": final,
        "removed_sets": removed_sets,
        "removed_exercises": removed_exercises,
        "items": tuple(after),
    }
