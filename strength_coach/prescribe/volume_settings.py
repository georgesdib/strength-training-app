"""Settings for the 9c drop engine, stored in the local volume overlay."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from strength_coach.prescribe import templates, volume_budget
from strength_coach.utils import exercises, paths


def _locations(base_path: str | Path | None = None) -> tuple[Path, Path]:
    base = Path(base_path or paths.config_dir("volume.v1.yaml"))
    overlay = base.with_name("volume.local.yaml")
    return base, overlay


def load_drop(base_path: str | Path | None = None) -> dict[str, Any]:
    base, overlay = _locations(base_path)
    cfg = volume_budget.BudgetConfig.load(base)
    return {
        "enabled": cfg.drop_enabled,
        "competition_confirm_days": cfg.drop_competition_confirm_days,
        "max_slots_per_group": cfg.drop_max_slots_per_group,
        "technique_minutes": cfg.drop_technique_minutes,
        "tolerance": cfg.tolerance,
        "high_band": round(cfg.total_target() * (1.0 + cfg.tolerance), 1),
        "slots": {
            group: [dict(entry) for entry in entries]
            for group, entries in cfg.drop_slots.items()
        },
        "source": str(overlay if overlay.is_file() else base),
    }


def _validated_slots(raw: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        raise ValueError("drop slots must be an object keyed by movement group")
    taxonomy = exercises.taxonomy().entities
    out: dict[str, list[dict[str, Any]]] = {}
    for group, entries in raw.items():
        if group not in volume_budget.MANAGED_KEYS:
            raise ValueError(f"unknown drop group {group!r}")
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"drop group {group!r} needs at least one candidate")
        clean: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("each drop candidate must be an object")
            exercise = str(entry.get("exercise_id") or "")
            if exercise not in taxonomy:
                raise ValueError(f"unknown exercise {exercise!r}")
            sets = int(entry.get("sets", 3))
            reps_low = int(entry.get("reps_low", 8))
            reps_high = int(entry.get("reps_high", 12))
            rir_low = int(entry.get("rir_low", 2))
            rir_high = int(entry.get("rir_high", 3))
            rest = int(entry.get("rest_s", 90))
            source = str(entry.get("load_source", "double_progression"))
            if sets < 1 or reps_low < 1 or reps_high < reps_low or rest < 0:
                raise ValueError(f"invalid sets/reps/rest for {exercise!r}")
            if not 0 <= rir_low <= rir_high <= 6:
                raise ValueError(f"invalid RIR for {exercise!r}")
            if source not in templates.LOAD_SOURCES:
                raise ValueError(f"unsupported load source {source!r}")
            clean.append({
                "exercise_id": exercise,
                "sets": sets,
                "reps_low": reps_low,
                "reps_high": reps_high,
                "rir_low": rir_low,
                "rir_high": rir_high,
                "rest_s": rest,
                "load_source": source,
            })
        out[str(group)] = clean
    return out


def save_drop(payload: dict[str, Any], *, base_path: str | Path | None = None) -> dict[str, Any]:
    base, overlay = _locations(base_path)
    current = load_drop(base)
    enabled = bool(payload.get("enabled", current["enabled"]))
    days = int(payload.get("competition_confirm_days", current["competition_confirm_days"]))
    max_slots = int(payload.get("max_slots_per_group", current["max_slots_per_group"]))
    technique = int(payload.get("technique_minutes", current["technique_minutes"]))
    tolerance = float(payload.get("tolerance", current["tolerance"]))
    if not 0 <= days <= 28:
        raise ValueError("competition confirmation days must be between 0 and 28")
    if not 1 <= max_slots <= 4:
        raise ValueError("max slots per group must be between 1 and 4")
    if not 1 <= technique <= 120:
        raise ValueError("technique minutes must be between 1 and 120")
    if not 0.0 <= tolerance <= 1.0:
        raise ValueError("tolerance must be between 0 and 1")
    slots = _validated_slots(payload.get("slots", current["slots"]))

    existing = {}
    old_text = overlay.read_text(encoding="utf-8") if overlay.is_file() else None
    if old_text:
        existing = yaml.safe_load(old_text) or {}
    budget = existing.setdefault("budget", {})
    budget["tolerance"] = tolerance
    budget["drop"] = {
        "enabled": enabled,
        "competition_confirm_days": days,
        "max_slots_per_group": max_slots,
        "technique_minutes": technique,
        "slots": slots,
    }
    overlay.parent.mkdir(parents=True, exist_ok=True)
    tmp = overlay.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
    os.replace(tmp, overlay)
    try:
        volume_budget.BudgetConfig.load(base)
    except Exception:
        if old_text is None:
            overlay.unlink(missing_ok=True)
        else:
            overlay.write_text(old_text, encoding="utf-8")
        raise
    return load_drop(base)
