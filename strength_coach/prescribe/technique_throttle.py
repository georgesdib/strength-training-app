"""MOD-TECH-001: a user-declared technique throttle for one session.

The athlete says technique felt off today; Python applies a bounded load cap and an RIR
floor to the scoped items. It is a *request*, not a derived rule: it reads no form rating,
stores no state, and does not repeat on the next session (docs/TECHNIQUE-THROTTLE.md).

The load reduction is compared with the cumulative factor the automatic modifiers already
applied, never multiplied on top, so an already-reduced session is left alone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from strength_coach.prescribe import loads
from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.utils import paths

MODIFIER = "MOD-TECH-001"


@dataclass(frozen=True)
class TechniqueThrottleConfig:
    load_multiplier: float = 0.90
    rir_floor: int = 3
    rir_cap: int = 4

    @classmethod
    def load(cls, path: str | Path | None = None) -> TechniqueThrottleConfig:
        source = Path(path or paths.config_dir("technique-throttle.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        multiplier = float(raw.get("load_multiplier", 0.90))
        floor = int(raw.get("rir_floor", 3))
        cap = int(raw.get("rir_cap", 4))
        if not 0 < multiplier <= 1.0:
            raise ValueError("load_multiplier must be in (0, 1]")
        if not 1 <= floor <= cap:
            raise ValueError("rir_floor must be between 1 and rir_cap")
        # RIR 6 marks a warm-up (DEC-RIR-01), so a throttle must never target it.
        if not 1 <= cap <= 5:
            raise ValueError("rir_cap must be between 1 and 5")
        return cls(load_multiplier=multiplier, rir_floor=floor, rir_cap=cap)


def _scope_patterns(
    pattern: str | Iterable[str] | None,
) -> tuple[bool, set[str] | None]:
    """Normalise the pattern scope into (include main work, named patterns).

    An empty value or an empty list means the default main work. A list may also contain an
    empty string, which represents the UI's selected "All lifts (main work)" option: that
    adds the essential items to any named patterns instead of replacing them.
    """
    if pattern is None:
        return True, None
    if isinstance(pattern, str):
        return (False, {pattern}) if pattern else (True, None)
    values = [str(value) for value in pattern]
    chosen = {value for value in values if value}
    if not chosen:
        return True, None
    return any(value == "" for value in values), chosen


def _scoped(item: PrescriptionItem, include_main: bool, scope: set[str] | None,
            patterns: Mapping[str, str]) -> bool:
    """Throttle main work and/or the selected movement patterns."""
    if scope is None:
        return bool(item.essential)
    if patterns.get(item.exercise_id) in scope:
        return True
    return include_main and bool(item.essential)


def _note_pattern(
    pattern: str | Iterable[str] | None, include_main: bool, scope: set[str] | None
) -> str | list[str] | None:
    """Keep one pattern as a string; list scopes are sorted and show the main-work flag."""
    if scope is None:
        return None
    if isinstance(pattern, str):
        return pattern
    return (["", *sorted(scope)] if include_main else sorted(scope))


def apply(items: Iterable[PrescriptionItem], patterns: Mapping[str, str], *,
          pattern: str | Iterable[str] | None = None,
          config: TechniqueThrottleConfig | None = None) -> dict[str, Any]:
    """Return items with the throttle applied, plus a provenance note.

    `patterns` maps exercise_id to its taxonomy movement pattern; it is only read when the
    caller names one or more patterns. Bodyweight work cannot shed external load, so it keeps
    its load and gets the RIR floor only — never a silently scaled total mass.
    """
    cfg = config or TechniqueThrottleConfig.load()
    current = list(items)
    include_main, scope = _scope_patterns(pattern)
    scoped = [item for item in current if _scoped(item, include_main, scope, patterns)]
    if not scoped:
        if scope is None:
            reason = "no main-lift item to throttle"
        elif len(scope) == 1:
            reason = f"no exercise in this session matches pattern {next(iter(scope))!r}"
        else:
            reason = f"no exercise in this session matches patterns {sorted(scope)!r}"
        return {
            "requested": True, "applied": False, "status": "no_match",
            "reason": reason,
            "pattern": _note_pattern(pattern, include_main, scope),
            "load_multiplier": cfg.load_multiplier,
            "rir_floor": cfg.rir_floor, "changed": [], "load_not_reducible": [],
            "items": tuple(current),
        }

    out: list[PrescriptionItem] = []
    changed: list[str] = []
    capped: list[str] = []
    floored: list[str] = []
    not_reducible: list[str] = []
    for item in current:
        if not _scoped(item, include_main, scope, patterns):
            out.append(item)
            continue
        if item.effort_model == "quality" or item.rir_target is None:
            # Power work has no RIR target and cannot be throttled by one (DEC-POWER-02).
            out.append(item)
            continue
        rir = min(cfg.rir_cap, max(int(item.rir_target), cfg.rir_floor))
        new_load = item.load_kg
        new_factor = item.load_factor
        if item.load_kg is None or item.load_kg <= 0:
            not_reducible.append(item.exercise_id)
        elif item.load_basis == "bodyweight_total":
            # Total bodyweight is not a plate to remove; the RIR floor still applies.
            not_reducible.append(item.exercise_id)
        else:
            # Compare, never multiply: never make an already-reduced item worse.
            target = min(item.load_factor, cfg.load_multiplier)
            applied = target / item.load_factor if item.load_factor > 0 else 1.0
            if applied < 1.0 - 1e-9:
                new_load = loads.round_down(
                    item.load_kg * applied, item.rounding_increment_kg
                )
                new_factor = target
        if (new_load is not None and item.load_kg is not None
                and abs(new_load - item.load_kg) > 1e-9):
            capped.append(item.exercise_id)
        if rir != item.rir_target:
            floored.append(item.exercise_id)
        if new_load == item.load_kg and rir == item.rir_target:
            out.append(item)
            continue
        changed.append(item.exercise_id)
        out.append(replace(
            item,
            load_kg=new_load,
            rir_target=rir,
            load_factor=new_factor,
            rationale_refs=tuple(item.rationale_refs) + (MODIFIER,),
        ))

    if changed:
        pieces = []
        if capped:
            pieces.append("load capped at "
                          f"{cfg.load_multiplier:.2f} on " + ", ".join(capped))
        if floored:
            pieces.append(f"RIR floor {cfg.rir_floor} on " + ", ".join(floored))
        if not_reducible:
            pieces.append("load not reducible on " + ", ".join(not_reducible))
        status, reason = "applied", "; ".join(pieces)
    elif not_reducible:
        status = "not_applicable"
        reason = ("load not reducible and RIR already at or above the floor on "
                  + ", ".join(not_reducible))
    else:
        status = "already_reduced"
        reason = ("already at or below the "
                  f"{cfg.load_multiplier:.2f} load factor and RIR floor")
    return {
        "requested": True, "applied": bool(changed), "status": status, "reason": reason,
        "pattern": _note_pattern(pattern, include_main, scope),
        "load_multiplier": cfg.load_multiplier,
        "rir_floor": cfg.rir_floor, "changed": changed,
        "load_not_reducible": not_reducible, "items": tuple(out),
    }
