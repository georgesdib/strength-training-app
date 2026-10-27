"""7a settings registry: definitions plus a read-only config snapshot.

This is the contract layer, not the profile store. Values still come from the existing YAML
files; 7a adds typed keys, classes, sources and ranges so step 4 can persist them without
inventing a second schema. Every feature loader remains the consumer in this step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import yaml

from strength_coach.features import continuity_calibration as continuity_feature
from strength_coach.features import fatigue_fitness as fatigue_feature
from strength_coach.features import high_intensity_exposure as exposure_feature
from strength_coach.features import test_cadence as cadence_feature
from strength_coach.features.deload import DeloadConfig
from strength_coach.features.e1rm_calibration import E1RMCalibrationConfig
from strength_coach.features.e1rm_decay import DecayConfig
from strength_coach.features.readiness import ReadinessConfig
from strength_coach.features.volume import VolumeConfig
from strength_coach.prescribe import schemes as schemes_mod
from strength_coach.prescribe import undulation as undulation_mod
from strength_coach.prescribe import warmup as warmup_feature
from strength_coach.prescribe.config import Thresholds
from strength_coach.utils import paths

LANDMARK_GROUPS = (
    "squat", "hinge", "hinge_unilateral", "horizontal_push", "horizontal_pull",
    "vertical_push", "vertical_pull", "core",
)
CLASSES = ("prescription_policy", "guarded_safety", "display")


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    group: str
    label: str
    kind: str
    default: Any
    source: str
    classification: str
    description: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()

    def validate(self, value: Any) -> None:
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{self.key} must be a boolean")
            return
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{self.key} must be an integer")
        elif self.kind == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.key} must be a number")
        elif self.kind == "str":
            if not isinstance(value, str):
                raise ValueError(f"{self.key} must be a string")
            if self.choices and value not in self.choices:
                raise ValueError(f"{self.key} must be one of {self.choices}")
            return
        elif self.kind == "table":
            if not isinstance(value, dict):
                raise ValueError(f"{self.key} must be a table")
            return
        elif self.kind == "list":
            if not isinstance(value, list):
                raise ValueError(f"{self.key} must be a list")
            return
        else:
            raise ValueError(f"{self.key} has unknown kind {self.kind!r}")
        if self.minimum is not None and float(value) < self.minimum:
            raise ValueError(f"{self.key} must be >= {self.minimum:g}")
        if self.maximum is not None and float(value) > self.maximum:
            raise ValueError(f"{self.key} must be <= {self.maximum:g}")


def _d(key, group, label, kind, default, source, classification, description, **kwargs):
    return SettingDefinition(
        key=key, group=group, label=label, kind=kind, default=default, source=source,
        classification=classification, description=description, **kwargs,
    )


def _definitions() -> tuple[SettingDefinition, ...]:
    items = [
        _d("undulation.enabled", "DUP", "DUP enabled", "bool", True,
           "templates/undulation.v1.yaml", "prescription_policy",
           "Use the weekly rep-scheme cycle."),
        _d("undulation.cycle_weeks", "DUP", "DUP cycle weeks", "int", 4,
           "templates/undulation.v1.yaml", "prescription_policy",
           "Length of the weekly cycle.", minimum=1, maximum=12),
        _d("undulation.weeks", "DUP", "DUP scheme table", "table", {},
           "templates/undulation.v1.yaml", "prescription_policy",
           "Weekly scheme assignment data."),
        _d("undulation.maximal_hinge_allowed", "DUP", "Allow maximal hinge",
           "bool", False, "templates/schemes.v1.yaml", "prescription_policy",
           "Allow the maximal scheme on hinge lifts; default keeps the back-history exclusion."),
        _d("spinal.override", "Spinal", "Spinal cap and costs", "table", {},
           "rules/programme.v1.yaml", "guarded_safety",
           "Guarded weekly cap and per-exercise costs for PRG-SPINE-001."),
        _d("deload.enabled", "Deload", "Deload enabled", "bool", True,
           "deload.v1.yaml", "prescription_policy", "Master deload switch."),
        _d("deload.scheduled.enabled", "Deload", "Scheduled deload", "bool", True,
           "deload.v1.yaml", "prescription_policy", "Use the block-week schedule."),
        _d("deload.scheduled.every_weeks", "Deload", "Scheduled every weeks", "int", 6,
           "deload.v1.yaml", "prescription_policy", "Scheduled deload interval.",
           minimum=1, maximum=52),
        _d("deload.scheduled.anchor_required", "Deload", "Anchor required", "bool", True,
           "deload.v1.yaml", "prescription_policy",
           "Require a declared block start before scheduling."),
        _d("deload.reactive.enabled", "Deload", "Reactive deload", "bool", True,
           "deload.v1.yaml", "prescription_policy", "Use reactive triggers."),
        _d("deload.reactive.consecutive_weeks", "Deload", "Reactive weeks", "int", 2,
           "deload.v1.yaml", "prescription_policy",
           "Consecutive over-cap weeks needed for a reactive deload.",
           minimum=1, maximum=8),
        _d("deload.reactive.consecutive_flares", "Deload", "Reactive flares", "int", 2,
           "deload.v1.yaml", "prescription_policy",
           "Consecutive flares needed for a reactive deload.",
           minimum=1, maximum=8),
        _d("deload.prescription.set_reduction", "Deload", "Set reduction", "int", 1,
           "deload.v1.yaml", "prescription_policy", "Sets removed per item on deload.",
           minimum=0, maximum=4),
        _d("deload.prescription.minimum_sets_per_item", "Deload", "Minimum sets", "int", 2,
           "deload.v1.yaml", "prescription_policy", "Deload set floor.",
           minimum=1, maximum=8),
        _d("deload.prescription.include_essential", "Deload", "Include essential", "bool", True,
           "deload.v1.yaml", "prescription_policy", "Apply deload sets to main lifts."),
        _d("deload.prescription.load_multiplier", "Deload", "Load multiplier", "float", 0.90,
           "deload.v1.yaml", "prescription_policy", "Deload load factor.",
           minimum=0.5, maximum=1.0),
        _d("deload.prescription.rir_add", "Deload", "RIR add", "int", 1,
           "deload.v1.yaml", "prescription_policy", "RIR added on deload.",
           minimum=0, maximum=5),
        _d("volume.apply_mrv_cap", "Volume", "Apply MRV cap", "bool", True,
           "volume.v1.yaml", "guarded_safety", "Trim accessories above MRV."),
        _d("volume.under_mev.enabled", "Volume", "Under-MEV progression", "bool", True,
           "volume.v1.yaml", "prescription_policy", "Add a set after persistent under-MEV."),
        _d("volume.under_mev.weeks", "Volume", "Under-MEV weeks", "int", 3,
           "volume.v1.yaml", "prescription_policy", "Weeks below MEV before adding.",
           minimum=1, maximum=12),
        _d("volume.under_mev.add_sets", "Volume", "Under-MEV add sets", "int", 1,
           "volume.v1.yaml", "prescription_policy", "Sets added.",
           minimum=1, maximum=4),
        _d("volume.under_mev.max_sets_per_item", "Volume", "Under-MEV max", "int", 8,
           "volume.v1.yaml", "prescription_policy", "Per-item ceiling.",
           minimum=1, maximum=12),
        _d("readiness.set_reduction.enabled", "Readiness", "Readiness set cut", "bool", True,
           "readiness.v1.yaml", "prescription_policy", "Reduce sets on a low score."),
        _d("readiness.set_reduction.score_below", "Readiness", "Readiness threshold", "float", 0.50,
           "readiness.v1.yaml", "prescription_policy", "Score below which sets are cut.",
           minimum=0.0, maximum=1.0),
        _d("readiness.set_reduction.sets", "Readiness", "Readiness sets cut", "int", 1,
           "readiness.v1.yaml", "prescription_policy", "Sets removed.",
           minimum=0, maximum=4),
        _d("readiness.set_reduction.include_essential", "Readiness", "Cut main lifts", "bool", False,
           "readiness.v1.yaml", "prescription_policy", "Include essential items."),
        _d("e1rm.window_days", "e1RM", "e1RM window days", "int", 84,
           "thresholds.v1.yaml", "prescription_policy", "Look-back for usable sets.",
           minimum=7, maximum=365),
        _d("e1rm.source", "e1RM", "e1RM source", "str", "median",
           "thresholds.v1.yaml", "prescription_policy", "Estimator used for the load.",
           choices=("best_usable", "median", "most_recent")),
        _d("e1rm.robust_window_days", "e1RM", "Robust window days", "int", 28,
           "thresholds.v1.yaml", "prescription_policy", "Median window.",
           minimum=7, maximum=365),
        _d("e1rm.plausibility.enabled", "e1RM", "Plausibility advisory", "bool", True,
           "thresholds.v1.yaml", "display", "Show the e1RM plausibility warning."),
        _d("e1rm.plausibility.reference_days", "e1RM", "Plausibility window", "int", 28,
           "thresholds.v1.yaml", "display", "Reference window.",
           minimum=7, maximum=365),
        _d("e1rm.plausibility.min_sets", "e1RM", "Plausibility min sets", "int", 3,
           "thresholds.v1.yaml", "display", "Minimum reference sets.",
           minimum=1, maximum=20),
        _d("e1rm.plausibility.max_above_reference", "e1RM", "Plausibility bound", "float", 0.05,
           "thresholds.v1.yaml", "display", "Maximum plausible excess.",
           minimum=0.0, maximum=1.0),
        _d("e1rm.decay.apply", "e1RM", "e1RM decay", "bool", True,
           "e1rm-decay.v1.yaml", "prescription_policy", "Apply age decay."),
        _d("e1rm.decay.grace_days", "e1RM", "Decay grace days", "int", 21,
           "e1rm-decay.v1.yaml", "prescription_policy", "Age before decay.",
           minimum=0, maximum=180),
        _d("e1rm.decay.weekly_decay", "e1RM", "Weekly decay", "float", 0.01,
           "e1rm-decay.v1.yaml", "prescription_policy", "Fraction lost per week.",
           minimum=0.0, maximum=0.5),
        _d("e1rm.decay.max_decay", "e1RM", "Maximum decay", "float", 0.10,
           "e1rm-decay.v1.yaml", "prescription_policy", "Decay ceiling.",
           minimum=0.0, maximum=0.5),
        _d("e1rm.calibration.apply", "e1RM", "Calibration", "bool", True,
           "e1rm-calibration.v1.yaml", "prescription_policy", "Apply calibrated e1RM."),
        _d("e1rm.calibration.min_tests", "e1RM", "Calibration tests", "int", 3,
           "e1rm-calibration.v1.yaml", "prescription_policy", "Measured tests required.",
           minimum=1, maximum=20),
        _d("e1rm.calibration.confidence", "e1RM", "Calibration confidence", "float", 0.95,
           "e1rm-calibration.v1.yaml", "prescription_policy", "Confidence level.",
           minimum=0.5, maximum=0.999),
        _d("e1rm.calibration.max_correction", "e1RM", "Calibration bound", "float", 0.10,
           "e1rm-calibration.v1.yaml", "prescription_policy", "Maximum correction.",
           minimum=0.0, maximum=0.5),
        _d("e1rm.calibration.bootstrap_samples", "e1RM", "Bootstrap samples", "int", 2000,
           "e1rm-calibration.v1.yaml", "prescription_policy", "Bootstrap draws.",
           minimum=100, maximum=20000),
        _d("e1rm.calibration.seed", "e1RM", "Calibration seed", "int", 20261020,
           "e1rm-calibration.v1.yaml", "prescription_policy", "Deterministic seed.",
           minimum=0, maximum=2147483647),
        _d("continuity.enabled", "Continuity", "Continuity calibration", "bool", True,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Master switch for calibrated return factors."),
        _d("continuity.apply", "Continuity", "Apply calibrated factor", "bool", True,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Use calibration; false keeps it report-only."),
        _d("continuity.min_returns_per_band", "Continuity", "Min returns/band", "int", 5,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Returns per continuity band.", minimum=1, maximum=100),
        _d("continuity.min_total_returns", "Continuity", "Min total returns", "int", 12,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Total returns required.", minimum=1, maximum=500),
        _d("continuity.max_gap_days", "Continuity", "Max gap days", "int", 365,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Longest usable return gap.", minimum=1, maximum=3650),
        _d("continuity.min_ratio", "Continuity", "Min ratio", "float", 0.50,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Reject implausibly low returns.", minimum=0.0, maximum=1.0),
        _d("continuity.max_ratio", "Continuity", "Max ratio", "float", 1.50,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Reject implausibly high returns.", minimum=1.0, maximum=3.0),
        _d("continuity.bootstrap_samples", "Continuity", "Bootstrap samples", "int", 1000,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Bootstrap draws.", minimum=100, maximum=20000),
        _d("continuity.confidence", "Continuity", "Confidence", "float", 0.95,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Confidence level.", minimum=0.5, maximum=0.999),
        _d("continuity.max_ci_width", "Continuity", "Max CI width", "float", 0.15,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Maximum usable interval.", minimum=0.0, maximum=1.0),
        _d("continuity.factor_floor", "Continuity", "Factor floor", "float", 0.85,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Lowest calibrated factor.", minimum=0.0, maximum=1.0),
        _d("continuity.allow_relax_fixed", "Continuity", "Allow relax fixed", "bool", False,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Allow calibration to relax the fixed reduction."),
        _d("continuity.seed", "Continuity", "Seed", "int", 20261020,
           "continuity-calibration.v1.yaml", "prescription_policy",
           "Deterministic bootstrap seed.", minimum=0, maximum=2147483647),
        _d("fatigue.enabled", "Fatigue", "Fatigue-fitness shadow", "bool", True,
           "fatigue-fitness.v1.yaml", "display", "Enable the shadow model/reports."),
        _d("fatigue.fitness_half_life_days", "Fatigue", "Fitness half-life", "float", 42.0,
           "fatigue-fitness.v1.yaml", "display", "Fitness decay half-life.",
           minimum=1.0, maximum=365.0),
        _d("fatigue.fatigue_half_life_days", "Fatigue", "Fatigue half-life", "float", 4.0,
           "fatigue-fitness.v1.yaml", "display", "Fatigue decay half-life.",
           minimum=0.5, maximum=60.0),
        _d("fatigue.min_observations", "Fatigue", "Min observations", "int", 8,
           "fatigue-fitness.v1.yaml", "display", "Minimum observations.",
           minimum=1, maximum=500),
        _d("fatigue.min_span_days", "Fatigue", "Min span days", "int", 28,
           "fatigue-fitness.v1.yaml", "display", "Minimum time span.",
           minimum=1, maximum=3650),
        _d("fatigue.min_r2", "Fatigue", "Min R2", "float", 0.30,
           "fatigue-fitness.v1.yaml", "display", "Minimum fit quality.",
           minimum=0.0, maximum=1.0),
        _d("fatigue.max_condition", "Fatigue", "Max condition", "float", 100000000.0,
           "fatigue-fitness.v1.yaml", "display", "Condition-number ceiling.",
           minimum=1.0, maximum=1000000000.0),
        _d("fatigue.pooling_k", "Fatigue", "Pooling k", "float", 10.0,
           "fatigue-fitness.v1.yaml", "display", "Partial-pooling strength.",
           minimum=0.0, maximum=1000.0),
        _d("test_cadence.enabled", "Test cadence", "Test cadence", "bool", True,
           "test-cadence.v1.yaml", "prescription_policy", "Enable strength-test prompts."),
        _d("test_cadence.every_weeks", "Test cadence", "Every weeks", "int", 10,
           "test-cadence.v1.yaml", "prescription_policy", "Test interval.",
           minimum=1, maximum=104),
        _d("test_cadence.schemes", "Test cadence", "Schemes", "list", [],
           "test-cadence.v1.yaml", "prescription_policy", "Test scheme list."),
        _d("warmup.enabled", "Warmup", "Warmup ramp", "bool", True,
           "warmup.v1.yaml", "prescription_policy", "Attach ramp sets."),
        _d("warmup.percents", "Warmup", "Percents", "list", [],
           "warmup.v1.yaml", "prescription_policy", "Ramp percentages."),
        _d("warmup.reps", "Warmup", "Reps", "list", [],
           "warmup.v1.yaml", "prescription_policy", "Ramp reps."),
        _d("warmup.apply_to_essential", "Warmup", "Essential only", "bool", True,
           "warmup.v1.yaml", "prescription_policy", "Only main lifts get ramps."),
        _d("high_intensity.override", "Exposure", "Exposure guard", "table", {},
           "high-intensity-exposure.v1.yaml", "guarded_safety",
           "Guarded lookback, symptom window and per-kind exposure windows."),


    ]
    for group in LANDMARK_GROUPS:
        for index, name in ((0, "mev"), (1, "mav_low"), (2, "mav_high"), (3, "mrv")):
            items.append(_d(
                f"volume.landmarks.{group}.{name}", "Volume",
                f"{group} {name}", "float", 0.0, "volume.v1.yaml",
                "prescription_policy", f"Configured {name} for {group}.",
                minimum=0.0, maximum=100.0,
            ))
    return tuple(items)


SETTINGS = _definitions()
BY_KEY = {setting.key: setting for setting in SETTINGS}


@dataclass(frozen=True)
class SettingsSnapshot:
    values: Mapping[str, Any]

    def get(self, key: str) -> Any:
        return self.values[key]


def _spinal_defaults() -> dict[str, Any]:
    raw = yaml.safe_load(
        paths.config_dir("rules/programme.v1.yaml").read_text(encoding="utf-8")
    ) or {}
    for rule in raw.get("rules") or []:
        if rule.get("id") == "PRG-SPINE-001":
            params = rule.get("params") or {}
            return {"cap": float(params.get("cap", 6)),
                    "costs": dict(params.get("costs") or {})}
    return {}


def _snapshot_values() -> dict[str, Any]:
    undulation = undulation_mod.Undulation.load()
    raw_undulation = yaml.safe_load(
        paths.undulation_yaml().read_text(encoding="utf-8")
    ) or {}
    deload = DeloadConfig.load()
    volume = VolumeConfig.load()
    readiness = ReadinessConfig.load()
    thresholds = Thresholds.load()
    decay = DecayConfig.load()
    calibration = E1RMCalibrationConfig.load()
    continuity = continuity_feature.CalibrationConfig.load()
    fatigue = fatigue_feature.ModelConfig.load()
    cadence = cadence_feature.CadenceConfig.load()
    warmup = warmup_feature.WarmupConfig.load()
    exposure = exposure_feature.ExposureConfig.load()
    values: dict[str, Any] = {
        "undulation.enabled": bool(undulation.enabled),
        "undulation.cycle_weeks": int(undulation.cycle_weeks),
        "undulation.weeks": dict(raw_undulation.get("weeks") or {}),
        "undulation.maximal_hinge_allowed": bool(
            schemes_mod.Schemes.load().maximal_hinge_allowed
        ),
        "spinal.override": _spinal_defaults(),
        "deload.enabled": bool(deload.enabled),
        "deload.scheduled.enabled": bool(deload.scheduled_enabled),
        "deload.scheduled.every_weeks": int(deload.every_weeks),
        "deload.scheduled.anchor_required": bool(deload.anchor_required),
        "deload.reactive.enabled": bool(deload.reactive_enabled),
        "deload.reactive.consecutive_weeks": int(deload.reactive_weeks),
        "deload.reactive.consecutive_flares": int(deload.reactive_flares),
        "deload.prescription.set_reduction": int(deload.set_reduction),
        "deload.prescription.minimum_sets_per_item": int(deload.minimum_sets),
        "deload.prescription.include_essential": bool(deload.include_essential),
        "deload.prescription.load_multiplier": float(deload.load_multiplier),
        "deload.prescription.rir_add": int(deload.rir_add),
        "volume.apply_mrv_cap": bool(volume.apply_mrv_cap),
        "volume.under_mev.enabled": bool(volume.under_mev_enabled),
        "volume.under_mev.weeks": int(volume.under_mev_weeks),
        "volume.under_mev.add_sets": int(volume.under_mev_add_sets),
        "volume.under_mev.max_sets_per_item": int(volume.under_mev_max_sets),
        "readiness.set_reduction.enabled": bool(readiness.set_reduction_enabled),
        "readiness.set_reduction.score_below": float(readiness.set_reduction_score_below),
        "readiness.set_reduction.sets": int(readiness.set_reduction_sets),
        "readiness.set_reduction.include_essential": bool(
            readiness.set_reduction_include_essential
        ),
        "e1rm.window_days": int(thresholds.e1rm_window_days),
        "e1rm.source": str(thresholds.e1rm_source),
        "e1rm.robust_window_days": int(thresholds.e1rm_robust_window_days),
        "e1rm.plausibility.enabled": bool(thresholds.plausibility_enabled),
        "e1rm.plausibility.reference_days": int(thresholds.plausibility_reference_days),
        "e1rm.plausibility.min_sets": int(thresholds.plausibility_min_sets),
        "e1rm.plausibility.max_above_reference": float(thresholds.plausibility_max_above_reference),
        "e1rm.decay.apply": bool(decay.apply),
        "e1rm.decay.grace_days": int(decay.grace_days),
        "e1rm.decay.weekly_decay": float(decay.weekly_decay),
        "e1rm.decay.max_decay": float(decay.max_decay),
        "e1rm.calibration.apply": bool(calibration.apply),
        "e1rm.calibration.min_tests": int(calibration.min_tests),
        "e1rm.calibration.confidence": float(calibration.confidence),
        "e1rm.calibration.max_correction": float(calibration.max_correction),
        "e1rm.calibration.bootstrap_samples": int(calibration.bootstrap_samples),
        "e1rm.calibration.seed": int(calibration.seed),
        "continuity.enabled": bool(continuity.enabled),
        "continuity.apply": bool(continuity.apply),
        "continuity.min_returns_per_band": int(continuity.min_returns_per_band),
        "continuity.min_total_returns": int(continuity.min_total_returns),
        "continuity.max_gap_days": int(continuity.max_gap_days),
        "continuity.min_ratio": float(continuity.min_ratio),
        "continuity.max_ratio": float(continuity.max_ratio),
        "continuity.bootstrap_samples": int(continuity.bootstrap_samples),
        "continuity.confidence": float(continuity.confidence),
        "continuity.max_ci_width": float(continuity.max_ci_width),
        "continuity.factor_floor": float(continuity.factor_floor),
        "continuity.allow_relax_fixed": bool(continuity.allow_relax_fixed),
        "continuity.seed": int(continuity.seed),
        "fatigue.enabled": bool(fatigue.enabled),
        "fatigue.fitness_half_life_days": float(fatigue.fitness_half_life_days),
        "fatigue.fatigue_half_life_days": float(fatigue.fatigue_half_life_days),
        "fatigue.min_observations": int(fatigue.min_observations),
        "fatigue.min_span_days": int(fatigue.min_span_days),
        "fatigue.min_r2": float(fatigue.min_r2),
        "fatigue.max_condition": float(fatigue.max_condition),
        "fatigue.pooling_k": float(fatigue.pooling_k),
        "test_cadence.enabled": bool(cadence.enabled),
        "test_cadence.every_weeks": int(cadence.every_weeks),
        "test_cadence.schemes": list(cadence.schemes),
        "warmup.enabled": bool(warmup.enabled),
        "warmup.percents": list(warmup.percents),
        "warmup.reps": list(warmup.reps),
        "warmup.apply_to_essential": bool(warmup.apply_to_essential),
        "high_intensity.override": {
            "lookback_days": int(exposure.lookback_days),
            "active_back_symptom_days": int(exposure.active_back_symptom_days),
            "windows_hours": dict(exposure.windows or {}),
        },
    }
    for group, landmark in (volume.landmarks or {}).items():
        if group not in LANDMARK_GROUPS:
            continue
        mev, mav_low, mav_high, mrv = landmark
        values[f"volume.landmarks.{group}.mev"] = float(mev)
        values[f"volume.landmarks.{group}.mav_low"] = float(mav_low)
        values[f"volume.landmarks.{group}.mav_high"] = float(mav_high)
        values[f"volume.landmarks.{group}.mrv"] = float(mrv)
    return values


def snapshot() -> SettingsSnapshot:
    values = _snapshot_values()
    missing = sorted(set(BY_KEY) - set(values))
    extra = sorted(set(values) - set(BY_KEY))
    if missing or extra:
        raise ValueError(f"settings registry mismatch: missing {missing}, extra {extra}")
    for key, value in values.items():
        BY_KEY[key].validate(value)
    return SettingsSnapshot(values)
