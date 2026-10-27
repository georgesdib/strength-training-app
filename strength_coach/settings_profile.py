"""Settings profile: append-only overrides and prescription snapshots."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from strength_coach import settings_registry
from strength_coach.features import deload as deload_feature
from strength_coach.features import continuity_calibration as continuity_feature
from strength_coach.features import e1rm_calibration as calibration_feature
from strength_coach.features import e1rm_decay as decay_feature
from strength_coach.features import fatigue_fitness as fatigue_feature
from strength_coach.features import high_intensity_exposure as exposure_feature
from strength_coach.features import test_cadence as cadence_feature
from strength_coach.features import readiness as readiness_feature
from strength_coach.features import volume as volume_feature
from strength_coach.prescribe import schemes as schemes_feature
from strength_coach.prescribe import warmup as warmup_feature
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
        "reason": row.get("reason"),
    }


def history(conn) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": int(row["profile_id"]),
            "effective_from": str(row["effective_from"]),
            "overrides": _loads(row["overrides_json"]),
            "created_at": str(row["created_at"]),
            "reason": row.get("reason"),
        }
        for row in repositories.settings_profile_history(conn)
    ]


def _validate_overrides(
    overrides: Mapping[str, Any], *, allow_guarded: bool = False,
) -> dict[str, Any]:
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
        if definition.classification == "guarded_safety" and not allow_guarded:
            raise ValueError(f"{key} is guarded safety and needs confirmation")
        definition.validate(value)
        if key == "spinal.override":
            if not isinstance(value, dict):
                raise ValueError("spinal.override must be an object")
            cap = value.get("cap")
            costs = value.get("costs") or {}
            if cap is not None and float(cap) <= 0:
                raise ValueError("spinal cap must be positive")
            if not isinstance(costs, dict) or not all(
                isinstance(k, str) and isinstance(v, (int, float))
                for k, v in costs.items()
            ):
                raise ValueError("spinal costs must be a map of numbers")
        if key == "high_intensity.override":
            if not isinstance(value, dict):
                raise ValueError("high_intensity.override must be an object")
            if int(value.get("lookback_days", 1)) < 1:
                raise ValueError("high-intensity lookback must be positive")
            if int(value.get("active_back_symptom_days", 0)) < 0:
                raise ValueError("high-intensity symptom window must be non-negative")
            windows = value.get("windows_hours") or {}
            if not isinstance(windows, dict) or not all(
                isinstance(k, str) and isinstance(v, int) and v >= 1
                for k, v in windows.items()
            ):
                raise ValueError("high-intensity windows must be a map of positive hours")
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
    guard_confirmed: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    day = str(effective_from or dt.date.today().isoformat())
    current = latest(conn, day)
    merged: dict[str, Any] = {} if reset or current is None else dict(current["overrides"])
    for key in unset or []:
        merged.pop(str(key), None)
    for key, value in (set_values or {}).items():
        merged[str(key)] = value
    guarded = [
        key for key in merged
        if key == "spinal.override"
        or settings_registry.BY_KEY.get(str(key), None) is not None
        and settings_registry.BY_KEY[str(key)].classification == "guarded_safety"
    ]
    if guarded and not guard_confirmed:
        raise ValueError("guarded settings require confirmation: " + ", ".join(sorted(guarded)))
    if guarded and not (reason or "").strip():
        raise ValueError("guarded settings require a reason")
    merged = _validate_overrides(merged, allow_guarded=guard_confirmed)
    repositories.append_settings_profile(
        conn, effective_from=day, overrides=merged, reason=(reason or None),
    )
    return state(conn, day)


def budget_snapshot(config) -> dict[str, Any]:
    data = asdict(config)
    data.pop("source_path", None)
    return data


def state(conn, on_date: str) -> dict[str, Any]:
    from strength_coach.prescribe.volume_budget import BudgetConfig

    row = latest(conn, on_date)
    overrides = row["overrides"] if row else {}
    budget_config = BudgetConfig.load(conn=conn, on_date=on_date)
    budget = budget_snapshot(budget_config)
    budget["high_band"] = round(
        budget_config.total_target() * (1.0 + budget_config.tolerance), 1
    )
    return {
        "profile_id": row["profile_id"] if row else None,
        "effective_from": row["effective_from"] if row else None,
        "reason": row["reason"] if row else None,
        "overrides": overrides,
        "resolved": resolved_registry(overrides),
        "budget": budget,
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
    spinal_cap: float
    spinal_costs: dict[str, float]
    deload: deload_feature.DeloadConfig
    volume: volume_feature.VolumeConfig
    readiness: readiness_feature.ReadinessConfig
    thresholds: Thresholds
    decay: decay_feature.DecayConfig
    calibration: calibration_feature.E1RMCalibrationConfig
    continuity: continuity_feature.CalibrationConfig
    fatigue: fatigue_feature.ModelConfig
    test_cadence: cadence_feature.CadenceConfig
    warmup: warmup_feature.WarmupConfig
    exposure: exposure_feature.ExposureConfig
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

    continuity = continuity_feature.CalibrationConfig.load()
    continuity = replace(
        continuity,
        enabled=bool(values["continuity.enabled"]),
        apply=bool(values["continuity.apply"]),
        min_returns_per_band=int(values["continuity.min_returns_per_band"]),
        min_total_returns=int(values["continuity.min_total_returns"]),
        max_gap_days=int(values["continuity.max_gap_days"]),
        min_ratio=float(values["continuity.min_ratio"]),
        max_ratio=float(values["continuity.max_ratio"]),
        bootstrap_samples=int(values["continuity.bootstrap_samples"]),
        confidence=float(values["continuity.confidence"]),
        max_ci_width=float(values["continuity.max_ci_width"]),
        factor_floor=float(values["continuity.factor_floor"]),
        allow_relax_fixed=bool(values["continuity.allow_relax_fixed"]),
        seed=int(values["continuity.seed"]),
    )

    fatigue = fatigue_feature.ModelConfig.load()
    fatigue = replace(
        fatigue,
        enabled=bool(values["fatigue.enabled"]),
        fitness_half_life_days=float(values["fatigue.fitness_half_life_days"]),
        fatigue_half_life_days=float(values["fatigue.fatigue_half_life_days"]),
        min_observations=int(values["fatigue.min_observations"]),
        min_span_days=int(values["fatigue.min_span_days"]),
        min_r2=float(values["fatigue.min_r2"]),
        max_condition=float(values["fatigue.max_condition"]),
        pooling_k=float(values["fatigue.pooling_k"]),
    )

    test_cadence = cadence_feature.CadenceConfig.load()
    test_cadence = replace(
        test_cadence,
        enabled=bool(values["test_cadence.enabled"]),
        every_weeks=int(values["test_cadence.every_weeks"]),
        schemes=tuple(str(x) for x in (values["test_cadence.schemes"] or [])),
    )

    warmup = warmup_feature.WarmupConfig.load()
    warmup = replace(
        warmup,
        enabled=bool(values["warmup.enabled"]),
        percents=tuple(float(x) for x in (values["warmup.percents"] or [])),
        reps=tuple(int(x) for x in (values["warmup.reps"] or [])),
        apply_to_essential=bool(values["warmup.apply_to_essential"]),
    )

    exposure = exposure_feature.ExposureConfig.load()
    exposure_override = overrides.get("high_intensity.override") or {}
    if exposure_override:
        windows = {str(k): int(v) for k, v in (exposure.windows or {}).items()}
        windows.update({
            str(k): int(v)
            for k, v in (exposure_override.get("windows_hours") or {}).items()
        })
        exposure = replace(
            exposure,
            lookback_days=int(exposure_override.get("lookback_days", exposure.lookback_days)),
            active_back_symptom_days=int(
                exposure_override.get("active_back_symptom_days",
                                     exposure.active_back_symptom_days)
            ),
            windows=windows,
        )

    spinal_base = settings_registry._spinal_defaults()
    spinal_override = overrides.get("spinal.override") or {}
    spinal_cap = float(spinal_override.get("cap", spinal_base.get("cap", 6)))
    spinal_costs = {
        **{str(k): float(v) for k, v in (spinal_base.get("costs") or {}).items()},
        **{str(k): float(v) for k, v in (spinal_override.get("costs") or {}).items()},
    }
    budget = BudgetConfig.load(conn=conn, on_date=on_date)
    return FeatureSettings(
        profile_id=row["profile_id"] if row else None,
        undulation=undulation,
        maximal_hinge_allowed=bool(values["undulation.maximal_hinge_allowed"]),
        spinal_cap=spinal_cap,
        spinal_costs=spinal_costs,
        deload=deload,
        volume=volume,
        readiness=readiness,
        thresholds=thresholds,
        decay=decay,
        calibration=calibration,
        continuity=continuity,
        fatigue=fatigue,
        test_cadence=test_cadence,
        warmup=warmup,
        exposure=exposure,
        budget=budget,
    )
