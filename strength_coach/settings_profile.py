"""Settings profile: append-only overrides and prescription snapshots."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from strength_coach import settings_registry
from strength_coach.features import deload as deload_feature
from strength_coach.features import e1rm_calibration as calibration_feature
from strength_coach.features import e1rm_decay as decay_feature
from strength_coach.features import readiness as readiness_feature
from strength_coach.features import volume as volume_feature
from strength_coach.prescribe import schemes as schemes_feature
from strength_coach.prescribe import undulation as undulation_feature
from strength_coach.prescribe.config import Thresholds
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


@dataclass(frozen=True)
class FeatureSettings:
    profile_id: int | None
    undulation: undulation_feature.Undulation
    maximal_hinge_allowed: bool
    deload: deload_feature.DeloadConfig
    volume: volume_feature.VolumeConfig
    readiness: readiness_feature.ReadinessConfig
    thresholds: Thresholds
    decay: decay_feature.DecayConfig
    calibration: calibration_feature.E1RMCalibrationConfig
    budget: Any


def feature_settings(conn, on_date: str) -> FeatureSettings:
    row = latest(conn, on_date)
    overrides = row["overrides"] if row else {}
    values = resolved_registry(overrides)
    from strength_coach.prescribe.volume_budget import BudgetConfig

    undulation = undulation_feature.Undulation.load()
    if "undulation.enabled" in overrides or "undulation.cycle_weeks" in overrides:
        weeks = undulation.weeks
        if "undulation.weeks" in overrides:
            weeks = {int(key): value for key, value in overrides["undulation.weeks"].items()}
        undulation = replace(
            undulation,
            enabled=bool(values["undulation.enabled"]),
            cycle_weeks=int(values["undulation.cycle_weeks"]),
            weeks=weeks,
        )

    deload = deload_feature.DeloadConfig.load()
    deload = replace(
        deload,
        enabled=bool(values["deload.enabled"]),
        scheduled_enabled=bool(values["deload.scheduled.enabled"]),
        every_weeks=int(values["deload.scheduled.every_weeks"]),
        anchor_required=bool(values["deload.scheduled.anchor_required"]),
        reactive_enabled=bool(values["deload.reactive.enabled"]),
        reactive_weeks=int(values["deload.reactive.consecutive_weeks"]),
        reactive_flares=int(values["deload.reactive.consecutive_flares"]),
        set_reduction=int(values["deload.prescription.set_reduction"]),
        minimum_sets=int(values["deload.prescription.minimum_sets_per_item"]),
        include_essential=bool(values["deload.prescription.include_essential"]),
        load_multiplier=float(values["deload.prescription.load_multiplier"]),
        rir_add=int(values["deload.prescription.rir_add"]),
    )

    volume = volume_feature.VolumeConfig.load()
    landmarks = dict(volume.landmarks or {})
    for group in settings_registry.LANDMARK_GROUPS:
        landmark = list(landmarks.get(group) or (0.0, 0.0, 0.0, 0.0))
        for index, name in enumerate(("mev", "mav_low", "mav_high", "mrv")):
            key = f"volume.landmarks.{group}.{name}"
            if key in overrides:
                landmark[index] = float(overrides[key])
        landmarks[group] = tuple(landmark)
    volume = replace(
        volume,
        landmarks=landmarks,
        apply_mrv_cap=bool(values["volume.apply_mrv_cap"]),
        under_mev_enabled=bool(values["volume.under_mev.enabled"]),
        under_mev_weeks=int(values["volume.under_mev.weeks"]),
        under_mev_add_sets=int(values["volume.under_mev.add_sets"]),
        under_mev_max_sets=int(values["volume.under_mev.max_sets_per_item"]),
    )

    readiness = readiness_feature.ReadinessConfig.load()
    readiness = replace(
        readiness,
        set_reduction_enabled=bool(values["readiness.set_reduction.enabled"]),
        set_reduction_score_below=float(values["readiness.set_reduction.score_below"]),
        set_reduction_sets=int(values["readiness.set_reduction.sets"]),
        set_reduction_include_essential=bool(
            values["readiness.set_reduction.include_essential"]
        ),
    )

    thresholds = Thresholds.load()
    thresholds = replace(
        thresholds,
        e1rm_window_days=int(values["e1rm.window_days"]),
        e1rm_source=str(values["e1rm.source"]),
        e1rm_robust_window_days=int(values["e1rm.robust_window_days"]),
        plausibility_enabled=bool(values["e1rm.plausibility.enabled"]),
        plausibility_reference_days=int(values["e1rm.plausibility.reference_days"]),
        plausibility_min_sets=int(values["e1rm.plausibility.min_sets"]),
        plausibility_max_above_reference=float(
            values["e1rm.plausibility.max_above_reference"]
        ),
    )

    decay = decay_feature.DecayConfig.load()
    decay = replace(
        decay,
        apply=bool(values["e1rm.decay.apply"]),
        grace_days=float(values["e1rm.decay.grace_days"]),
        weekly_decay=float(values["e1rm.decay.weekly_decay"]),
        max_decay=float(values["e1rm.decay.max_decay"]),
    )

    calibration = calibration_feature.E1RMCalibrationConfig.load()
    calibration = replace(
        calibration,
        apply=bool(values["e1rm.calibration.apply"]),
        min_tests=int(values["e1rm.calibration.min_tests"]),
        confidence=float(values["e1rm.calibration.confidence"]),
        max_correction=float(values["e1rm.calibration.max_correction"]),
        bootstrap_samples=int(values["e1rm.calibration.bootstrap_samples"]),
        seed=int(values["e1rm.calibration.seed"]),
    )

    budget = BudgetConfig.load(conn=conn, on_date=on_date)
    return FeatureSettings(
        profile_id=row["profile_id"] if row else None,
        undulation=undulation,
        maximal_hinge_allowed=bool(values["undulation.maximal_hinge_allowed"]),
        deload=deload,
        volume=volume,
        readiness=readiness,
        thresholds=thresholds,
        decay=decay,
        calibration=calibration,
        budget=budget,
    )



