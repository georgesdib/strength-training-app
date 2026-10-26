"""Settings profile: append-only overrides and prescription snapshots."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict
from typing import Any, Mapping

from strength_coach import settings_registry
from strength_coach.store import repositories


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("settings_profile overrides must be an object")
    return data


def latest(conn, on_date: str) -> dict[str, Any] | None:
    row = repositories.settings_profile_latest(conn, on_date)
    if row is None:
        return None
    return {
        "profile_id": int(row["profile_id"]),
        "effective_from": str(row["effective_from"]),
        "overrides": _loads(row["overrides_json"]),
        "created_at": str(row["created_at"]),
    }


def history(conn) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": int(row["profile_id"]),
            "effective_from": str(row["effective_from"]),
            "overrides": _loads(row["overrides_json"]),
            "created_at": str(row["created_at"]),
        }
        for row in repositories.settings_profile_history(conn)
    ]


def _validate_overrides(overrides: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in overrides.items():
        if key == "budget":
            if not isinstance(value, dict):
                raise ValueError("budget override must be an object")
            clean["budget"] = dict(value)
            continue
        definition = settings_registry.BY_KEY.get(str(key))
        if definition is None:
            raise ValueError(f"unknown settings key {key!r}")
        if definition.classification == "guarded_safety":
            raise ValueError(f"{key} is guarded safety; step 5 requires confirmation")
        definition.validate(value)
        clean[str(key)] = value
    if "budget" in clean:
        from strength_coach.prescribe.volume_budget import BudgetConfig
        BudgetConfig.load(profile_budget=clean["budget"])
    return clean


def resolved_registry(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    values = dict(settings_registry.snapshot().values)
    for key, value in (overrides or {}).items():
        if key == "budget":
            continue
        definition = settings_registry.BY_KEY.get(str(key))
        if definition is None:
            raise ValueError(f"unknown settings key {key!r}")
        definition.validate(value)
        values[str(key)] = value
    return values


def budget_overrides(conn, on_date: str) -> dict[str, Any]:
    row = latest(conn, on_date)
    if row is None:
        return {}
    budget = row["overrides"].get("budget")
    return dict(budget) if isinstance(budget, dict) else {}


def save(
    conn,
    *,
    set_values: Mapping[str, Any] | None = None,
    unset: list[str] | None = None,
    reset: bool = False,
    effective_from: str | None = None,
) -> dict[str, Any]:
    day = str(effective_from or dt.date.today().isoformat())
    current = latest(conn, day)
    merged: dict[str, Any] = {} if reset or current is None else dict(current["overrides"])
    for key in unset or []:
        merged.pop(str(key), None)
    for key, value in (set_values or {}).items():
        merged[str(key)] = value
    merged = _validate_overrides(merged)
    repositories.append_settings_profile(conn, effective_from=day, overrides=merged)
    return state(conn, day)


def budget_snapshot(config) -> dict[str, Any]:
    data = asdict(config)
    data.pop("source_path", None)
    return data


def state(conn, on_date: str) -> dict[str, Any]:
    from strength_coach.prescribe.volume_budget import BudgetConfig

    row = latest(conn, on_date)
    overrides = row["overrides"] if row else {}
    return {
        "profile_id": row["profile_id"] if row else None,
        "effective_from": row["effective_from"] if row else None,
        "overrides": overrides,
        "resolved": resolved_registry(overrides),
        "budget": budget_snapshot(BudgetConfig.load(conn=conn, on_date=on_date)),
        "history": history(conn),
    }


def snapshot_prescription(conn, prescription_id: str, on_date: str) -> None:
    from strength_coach.prescribe.volume_budget import BudgetConfig

    if repositories.prescription_profile(conn, prescription_id) is not None:
        return
    row = latest(conn, on_date)
    overrides = row["overrides"] if row else {}
    settings = {
        "registry": resolved_registry(overrides),
        "budget": budget_snapshot(BudgetConfig.load(conn=conn, on_date=on_date)),
    }
    encoded = json.dumps(settings, sort_keys=True, default=str)
    repositories.append_prescription_profile(
        conn,
        prescription_id=prescription_id,
        profile_id=row["profile_id"] if row else None,
        settings=settings,
        config_hash=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )


