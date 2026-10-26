"""5b modality registry.

The module list is metadata over existing settings: a module never owns a second enabled flag.
enabled_key points at the existing setting, and a toggle delegates to that setting's normal
path (settings profile or athlete profile). Factors are references to the same registry keys.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from strength_coach import settings_profile, settings_registry
from strength_coach.store import queries, repositories
from strength_coach.utils import paths

CLASSES = ("hard_safety", "guarded_safety", "prescription_policy", "display", "experiment")


@dataclass(frozen=True)
class Modality:
    id: str
    label: str
    classification: str
    enabled_key: str | None
    toggleable: bool
    dependencies: tuple[str, ...]
    citations: tuple[str, ...]
    factors: tuple[str, ...]
    doc: str


def _config(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path or paths.config_dir("modalities.v1.yaml"))
    return yaml.safe_load(source.read_text(encoding="utf-8")) or {}


def modules(path: str | Path | None = None) -> tuple[Modality, ...]:
    out = []
    for row in _config(path).get("modules") or []:
        classification = str(row.get("class") or "")
        if classification not in CLASSES:
            raise ValueError(f"unknown modality class {classification!r}")
        out.append(Modality(
            id=str(row["id"]), label=str(row.get("label", row["id"])),
            classification=classification,
            enabled_key=(str(row["enabled_key"]) if row.get("enabled_key") else None),
            toggleable=bool(row.get("toggleable", False)),
            dependencies=tuple(str(x) for x in (row.get("dependencies") or ())),
            citations=tuple(str(x) for x in (row.get("citations") or ())),
            factors=tuple(str(x) for x in (row.get("factors") or ())),
            doc=str(row.get("doc", "")),
        ))
    return tuple(out)


def _by_id(module_id: str) -> Modality:
    for module in modules():
        if module.id == module_id:
            return module
    raise ValueError(f"unknown modality {module_id!r}")


def _athlete_budget(conn) -> bool:
    profile = queries.athlete_profile(conn) or {}
    return bool(profile.get("volume_budget_enabled"))


def _module_state(conn, module: Modality, on_date: str) -> dict[str, Any]:
    settings = settings_profile.state(conn, on_date)
    if module.enabled_key == "athlete_profile.volume_budget_enabled":
        enabled = _athlete_budget(conn)
        source = "athlete_profile"
    elif module.enabled_key:
        enabled = settings["resolved"].get(module.enabled_key)
        source = "profile" if module.enabled_key in settings["overrides"] else "config"
    else:
        enabled = True
        source = "constitution"
    factors = []
    for key in module.factors:
        if key == "budget":
            factors.append({
                "key": "budget", "label": "Budget and drop",
                "value": settings["budget"], "classification": module.classification,
                "guarded": False,
            })
            continue
        definition = settings_registry.BY_KEY.get(key)
        if definition is None:
            continue
        factors.append({
            "key": key, "label": definition.label,
            "value": settings["resolved"].get(key),
            "classification": definition.classification,
            "guarded": definition.classification == "guarded_safety",
        })
    dependency_state = {}
    for dependency in module.dependencies:
        dependency_state[dependency] = any(
            item.id == dependency and _module_enabled(conn, item, on_date)
            for item in modules()
        )
    return {
        "id": module.id, "label": module.label,
        "class": module.classification, "enabled": bool(enabled),
        "enabled_source": source, "toggleable": module.toggleable,
        "dependencies": list(module.dependencies),
        "dependency_state": dependency_state,
        "citations": list(module.citations),
        "factors": factors, "doc": module.doc,
    }


def _module_enabled(conn, module: Modality, on_date: str) -> bool:
    if module.enabled_key == "athlete_profile.volume_budget_enabled":
        return _athlete_budget(conn)
    if not module.enabled_key:
        return True
    return bool(settings_profile.state(conn, on_date)["resolved"].get(module.enabled_key))


def state(conn, on_date: str | None = None) -> dict[str, Any]:
    day = on_date or dt.date.today().isoformat()
    return {
        "on_date": day,
        "modules": [_module_state(conn, module, day) for module in modules()],
    }


def show(conn, module_id: str, on_date: str | None = None) -> dict[str, Any]:
    return _module_state(conn, _by_id(module_id), on_date or dt.date.today().isoformat())


def _update_athlete_budget(conn, *, enabled: bool, effective_from: str) -> None:
    current = queries.athlete_profile(conn)
    if current is None:
        raise ValueError("record an athlete profile before toggling volume_budget")
    repositories.append_athlete_profile(
        conn,
        effective_from=effective_from,
        primary_goal=current["primary_goal"],
        goal_rank=json.loads(current["goal_rank"] or "[]"),
        focus_lifts=json.loads(current["focus_lifts"] or "[]"),
        competition_date=current["competition_date"],
        sessions_per_week_target=current["sessions_per_week_target"],
        max_session_minutes=current["max_session_minutes"],
        block_start_date=current["block_start_date"],
        volume_budget_enabled=enabled,
        main_lift_policy=current.get("main_lift_policy", "preserve"),
    )


def update(
    conn,
    module_id: str,
    *,
    enabled: bool | None = None,
    factors: dict[str, Any] | None = None,
    guard_confirmed: bool = False,
    reason: str | None = None,
    effective_from: str | None = None,
) -> dict[str, Any]:
    module = _by_id(module_id)
    day = effective_from or dt.date.today().isoformat()
    allowed = set(module.factors)
    set_values: dict[str, Any] = {}
    for key, value in (factors or {}).items():
        if key not in allowed:
            raise ValueError(f"{key} is not a factor of {module_id}")
        set_values[key] = value
    if enabled is not None:
        if not module.toggleable:
            raise ValueError(f"{module_id} is not toggleable")
        if module.enabled_key == "athlete_profile.volume_budget_enabled":
            _update_athlete_budget(conn, enabled=bool(enabled), effective_from=day)
        elif module.enabled_key:
            set_values[module.enabled_key] = bool(enabled)
        else:
            raise ValueError(f"{module_id} has no enabled key")
    if set_values:
        settings_profile.save(
            conn, set_values=set_values, effective_from=day,
            guard_confirmed=guard_confirmed,
            reason=reason,
        )
    return show(conn, module_id, day)
