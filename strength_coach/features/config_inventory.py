"""Read-only inventory of monitoring and related methodology parameters.

The inventory is intentionally curated. It exposes effective values, their relative source
and whether the UI may edit them; it never exposes database contents or athlete records.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from strength_coach import __version__
from strength_coach.domain.e1rm import E1RM_METHOD_VERSION
from strength_coach.features import (
    e1rm_calibration,
    exposure,
    monitoring,
    monitoring_analysis,
    readiness,
    relative_strength,
    volume,
)
from strength_coach.prescribe.config import Thresholds
from strength_coach.prescribe.volume_budget import BudgetConfig
from strength_coach.utils import paths

PHASE_5A_START = "2026-10-30"
PHASE_5A_REVIEW = "2027-01-22"


def _relative(path: Path) -> str:
    root = paths.config_dir().parent
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _mapping(raw: Any, dotted: str, default: Any = None) -> tuple[Any, bool]:
    current = raw
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default, False
        current = current[part]
    return current, True


def _parameter(
    key: str,
    label: str,
    value: Any,
    *,
    source: str,
    unit: str | None = None,
    configured: bool = True,
    editable: bool = False,
    editability: str = "read_only",
    source_kind: str = "canonical_config",
    reason: str = "",
    doc: str = "docs/MONITORING-ANALYSIS.md",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "source": source,
        "source_kind": source_kind,
        "configured": configured,
        "editable": editable,
        "editability": editability,
        "reason": reason,
        "doc": doc,
    }


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def revision(groups: list[dict[str, Any]]) -> str:
    """Hash the complete effective inventory deterministically.

    The hash covers effective values and provenance, including Python defaults and fixed code
    constants, not just the YAML files that happen to exist.
    """
    payload = json.dumps(groups, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relationship_source() -> tuple[str, str]:
    return "canonical config: config/strength-relationships.v1.yaml", "canonical_config"


def _monitoring_group() -> dict[str, Any]:
    cfg = monitoring.MonitoringConfig.load()
    raw = _load(paths.config_dir("monitoring.v1.yaml"))
    rows = []

    def add(key, label, value, dotted, unit=None, edit="phase5a_locked"):
        _, configured = _mapping(raw, dotted)
        source, source_kind = (
            (_relative(paths.config_dir("monitoring.v1.yaml")), "canonical_config")
            if configured
            else ("python-default: strength_coach/features/monitoring.py", "python_default")
        )
        rows.append(
            _parameter(
                key,
                label,
                value,
                source=source,
                source_kind=source_kind,
                unit=unit,
                configured=configured,
                editable=False,
                editability=edit,
                reason="Monitoring definition; frozen during Phase 5A.",
            )
        )

    add(
        "monitoring.recent_reference.observations",
        "Recent reference observations",
        cfg.recent_observations,
        "recent_reference.observations",
        "observations",
    )
    add(
        "monitoring.recent_reference.max_age_days",
        "Recent reference maximum age",
        cfg.recent_max_age_days,
        "recent_reference.max_age_days",
        "days",
    )
    for key, value in cfg.relative_bands.items():
        add(
            f"monitoring.relative_intensity.bands.{key}",
            f"Relative-intensity band: {key}",
            value,
            f"relative_intensity.bands.{key}",
            "ratio",
        )
    add(
        "monitoring.ratios.max_gap_days",
        "Configured ratio maximum gap",
        cfg.ratio_max_gap_days,
        "ratios.max_gap_days",
        "days",
    )
    add(
        "monitoring.ratios.max_age_days",
        "Configured ratio maximum age",
        cfg.ratio_max_age_days,
        "ratios.max_age_days",
        "days",
    )
    add(
        "monitoring.ratios.min_observations",
        "Configured ratio minimum observations",
        cfg.ratio_min_observations,
        "ratios.min_observations",
        "observations",
    )
    add(
        "monitoring.hard_sets.near_failure_max_rir",
        "Near-failure display cut",
        cfg.near_failure_max_rir,
        "hard_sets.near_failure_max_rir",
        "RIR",
    )
    add("monitoring.power.pattern", "Power pattern", cfg.power_pattern, "power.pattern")
    add(
        "monitoring.session_load.late_feedback_days",
        "Late-feedback threshold",
        cfg.late_feedback_days,
        "session_load.late_feedback_days",
        "days",
    )
    add(
        "monitoring.session_load.long_session_multiplier",
        "Long-session display multiplier",
        cfg.long_session_multiplier,
        "session_load.long_session_multiplier",
        "multiplier",
    )
    add(
        "monitoring.comparability.window_weeks",
        "Comparable-session window",
        cfg.comparability_window_weeks,
        "comparability.window_weeks",
        "weeks",
    )
    add(
        "monitoring.comparability.min_exercise_overlap",
        "Comparable-session minimum overlap",
        cfg.comparability_min_overlap,
        "comparability.min_exercise_overlap",
        "share",
    )
    add(
        "monitoring.comparability.min_prior_sessions",
        "Comparable-session minimum priors",
        cfg.comparability_min_prior_sessions,
        "comparability.min_prior_sessions",
        "sessions",
    )
    add(
        "monitoring.display.precision_kg",
        "Display kg precision",
        cfg.precision_kg,
        "display.precision_kg",
        "decimals",
    )
    add(
        "monitoring.display.precision_pct",
        "Display percent precision",
        cfg.precision_pct,
        "display.precision_pct",
        "decimals",
    )
    for key, value in cfg.features.items():
        add(f"monitoring.features.{key}", f"Optional feature: {key}", bool(value), f"features.{key}")
    return {"key": "monitoring", "label": "Monitoring definitions", "parameters": rows}


def _exposure_group() -> dict[str, Any]:
    cfg = exposure.ExposureConfig.load()
    raw = _load(paths.exposure_yaml())
    rows = []

    def add(key, label, value, dotted, unit=None):
        _, configured = _mapping(raw, dotted)
        source, source_kind = (
            (_relative(paths.exposure_yaml()), "canonical_config")
            if configured
            else ("python-default: strength_coach/features/exposure.py", "python_default")
        )
        rows.append(
            _parameter(
                key,
                label,
                value,
                source=source,
                source_kind=source_kind,
                unit=unit,
                configured=configured,
                editability="phase5a_locked",
                reason="Exposure definition; frozen during Phase 5A.",
            )
        )

    for key, label, unit in [
        ("acute_days", "Acute exposure window", "days"),
        ("chronic_days", "Chronic exposure window", "days"),
        ("effort_max_rir", "Hard-set maximum RIR", "RIR"),
        ("min_sessions", "Minimum exposure sessions", "sessions"),
        ("min_coverage", "Minimum RIR coverage", "share"),
        ("high_ratio", "High exposure ratio", "ratio"),
        ("low_ratio", "Low exposure ratio", "ratio"),
        ("gap_days", "Exposure gap days", "days"),
    ]:
        add(f"exposure.{key}", label, getattr(cfg, key), key, unit)
    add(
        "exposure.trim.max_sets_per_session",
        "Exposure trim maximum per session",
        cfg.trim_max_sets_per_session,
        "trim.max_sets_per_session",
        "sets",
    )
    add(
        "exposure.trim.max_sets_per_item",
        "Exposure trim maximum per item",
        cfg.trim_max_sets_per_item,
        "trim.max_sets_per_item",
        "sets",
    )
    add("exposure.trim.floor_sets", "Exposure trim floor", cfg.trim_floor_sets, "trim.floor_sets", "sets")
    return {"key": "exposure", "label": "Exposure and dose", "parameters": rows}


def _calibration_group() -> dict[str, Any]:
    cfg = e1rm_calibration.E1RMCalibrationConfig.load()
    path = paths.e1rm_calibration_yaml()
    raw = _load(path)
    rows = []

    def add(key, label, value, dotted, unit=None, editability="read_only"):
        _, configured = _mapping(raw, dotted) if dotted else (value, False)
        if dotted and configured:
            source, source_kind = _relative(path), "canonical_config"
        elif dotted:
            source, source_kind = (
                "python-default: strength_coach/features/e1rm_calibration.py",
                "python_default",
            )
        else:
            source, source_kind = "code: strength_coach/features/e1rm_calibration.py", "fixed_code"
        rows.append(
            _parameter(
                key,
                label,
                value,
                source=source,
                source_kind=source_kind,
                unit=unit,
                configured=configured,
                editability=editability,
                reason="Calibration algorithm input; changing it requires a separate decision.",
                doc="docs/FATIGUE-FITNESS.md",
            )
        )

    add(
        "calibration.window_days",
        "Calibration lookback window",
        e1rm_calibration.DEFAULT_WINDOW_DAYS,
        None,
        "days",
        "fixed",
    )
    add("calibration.apply", "Apply calibration correction", cfg.apply, "apply")
    add("calibration.min_tests", "Minimum measured tests", cfg.min_tests, "min_tests", "tests")
    add("calibration.confidence", "CI confidence", cfg.confidence, "confidence", "share")
    add("calibration.max_correction", "Maximum correction", cfg.max_correction, "max_correction", "share")
    add(
        "calibration.bootstrap_samples",
        "Bootstrap samples",
        cfg.bootstrap_samples,
        "bootstrap_samples",
        "samples",
    )
    add("calibration.seed", "Bootstrap seed", cfg.seed, "seed")
    add("e1rm.method_version", "e1RM method version", E1RM_METHOD_VERSION, None, None, "fixed")
    return {"key": "calibration", "label": "Calibration context", "parameters": rows}


def _relationship_group() -> dict[str, Any]:
    relationships = relative_strength.load_relationships()
    source, source_kind = _relationship_source()
    rows = [
        _parameter(
            "relationships.count",
            "Configured relationship count",
            len(relationships),
            source=source,
            unit="pairs",
            editability="read_only",
            source_kind=source_kind,
            reason="Pair CRUD is planned separately; this inventory is read-only.",
            doc="docs/MONITORING-ANALYSIS.md",
        )
    ]
    for item in relationships:
        for field, label, unit in [
            ("max_gap_days", "maximum gap", "days"),
            ("max_age_days", "maximum age", "days"),
            ("min_observations", "minimum observations", "observations"),
        ]:
            rows.append(
                _parameter(
                    f"relationships.{item.id}.{field}",
                    f"{item.label}: {label}",
                    getattr(item, field),
                    source=source,
                    source_kind=source_kind,
                    unit=unit,
                    editability="read_only",
                    reason="Pair configuration; CRUD is a separate workstream.",
                    doc="docs/MONITORING-ANALYSIS.md",
                )
            )
    return {"key": "relationships", "label": "Relative-strength pairs", "parameters": rows}


def _readiness_group() -> dict[str, Any]:
    cfg = readiness.ReadinessConfig.load()
    path = paths.readiness_yaml()
    raw = _load(path)
    rows = []

    def add(key, label, value, dotted, unit=None):
        _, configured = _mapping(raw, dotted)
        source, source_kind = (
            (_relative(path), "canonical_config")
            if configured
            else ("python-default: strength_coach/features/readiness.py", "python_default")
        )
        rows.append(
            _parameter(
                key,
                label,
                value,
                source=source,
                source_kind=source_kind,
                unit=unit,
                configured=configured,
                editability="read_only",
                reason="Readiness policy is not editable from the monitoring inventory.",
                doc="docs/READINESS.md",
            )
        )

    add("readiness.merge.strategy", "Readiness merge strategy", cfg.merge_strategy, "merge.strategy")
    add("readiness.merge.tie_break", "Readiness tie-break", cfg.tie_break, "merge.tie_break")
    add(
        "readiness.modifier.at_or_below",
        "Readiness modifier threshold",
        cfg.at_or_below,
        "modifier.at_or_below",
        "score",
    )
    add(
        "readiness.set_reduction.enabled",
        "Readiness set reduction",
        cfg.set_reduction_enabled,
        "set_reduction.enabled",
    )
    add(
        "readiness.set_reduction.score_below",
        "Readiness set-reduction threshold",
        cfg.set_reduction_score_below,
        "set_reduction.score_below",
        "score",
    )
    add(
        "readiness.set_reduction.sets",
        "Readiness set-reduction sets",
        cfg.set_reduction_sets,
        "set_reduction.sets",
        "sets",
    )
    add(
        "readiness.score.baseline_days",
        "Readiness baseline window",
        cfg.baseline_days,
        "score.baseline_days",
        "days",
    )
    add(
        "readiness.score.baseline_min_readings",
        "Readiness baseline minimum readings",
        cfg.baseline_min_readings,
        "score.baseline_min_readings",
        "readings",
    )
    return {"key": "readiness", "label": "Readiness parameters", "parameters": rows}


VOLUME_CANONICAL = "config/volume.v1.yaml"
VOLUME_LOCAL = "config/volume.local.yaml"


def _budget_map_provenance(
    canonical: dict,
    local: dict,
    dotted: str,
) -> tuple[str, str, bool]:
    local_keys = set((_mapping(local, dotted, {})[0] or {}).keys())
    canonical_keys = set((_mapping(canonical, dotted, {})[0] or {}).keys())
    if local_keys and canonical_keys:
        return (
            "merged config: config/volume.v1.yaml + config/volume.local.yaml",
            "local_override",
            True,
        )
    if local_keys:
        return "local override: config/volume.local.yaml", "local_override", True
    if canonical_keys:
        return VOLUME_CANONICAL, "canonical_config", True
    return (
        "python-default: strength_coach/prescribe/volume_budget.py",
        "python_default",
        False,
    )


def _explicit_value(raw: dict, dotted: str) -> bool:
    value, present = _mapping(raw, dotted)
    return present and value is not None


def _budget_total_provenance(
    canonical: dict,
    local: dict,
    *,
    explicit: str,
    map_key: str,
    fallback_map: str | None = None,
) -> tuple[str, str, bool]:
    if _explicit_value(local, explicit):
        return "local override: config/volume.local.yaml", "local_override", True
    if _explicit_value(canonical, explicit):
        return VOLUME_CANONICAL, "canonical_config", True
    source, kind, configured = _budget_map_provenance(canonical, local, map_key)
    if configured:
        return source, kind, True
    if fallback_map is not None:
        source, kind, configured = _budget_map_provenance(canonical, local, fallback_map)
        if configured:
            return source, kind, True
    return (
        "python-default: strength_coach/prescribe/volume_budget.py",
        "python_default",
        False,
    )


def _prescription_group() -> dict[str, Any]:
    threshold_path = paths.thresholds_yaml()
    volume_path = paths.config_dir("volume.v1.yaml")
    thresholds = Thresholds.load()
    volume_cfg = volume.VolumeConfig.load()
    budget = BudgetConfig.load()
    thresholds_raw = _load(threshold_path)
    volume_raw = _load(volume_path)
    volume_local = _load(paths.config_dir("volume.local.yaml"))
    rows = []

    def add(
        key,
        label,
        value,
        dotted,
        unit=None,
        *,
        source,
        raw,
        default_source="python-default: strength_coach/prescribe/config.py",
        local_raw=None,
    ):
        _, configured = _mapping(raw, dotted)
        local_configured = bool(local_raw is not None and _mapping(local_raw, dotted)[1])
        if local_configured:
            configured = True
            source_label, source_kind = (
                "local override: config/volume.local.yaml",
                "local_override",
            )
        elif configured:
            source_label, source_kind = _relative(source), "canonical_config"
        else:
            source_label, source_kind = default_source, "python_default"
        rows.append(
            _parameter(
                key,
                label,
                value,
                source=source_label,
                source_kind=source_kind,
                unit=unit,
                configured=configured,
                editability="read_only",
                reason="Prescription/volume policy; editing is not part of this workstream.",
                doc="docs/WEB-UI.md",
            )
        )

    add(
        "prescription.load.increment_kg",
        "Load increment",
        thresholds.increment_kg,
        "load.increment_kg",
        "kg",
        source=threshold_path,
        raw=thresholds_raw,
    )
    add(
        "prescription.load.rounding",
        "Load rounding",
        thresholds.rounding,
        "load.rounding",
        None,
        source=threshold_path,
        raw=thresholds_raw,
    )
    add(
        "prescription.load.e1rm_window_days",
        "e1RM load window",
        thresholds.e1rm_window_days,
        "load.e1rm_window_days",
        "days",
        source=threshold_path,
        raw=thresholds_raw,
    )
    add(
        "prescription.load.e1rm_source",
        "e1RM load source",
        thresholds.e1rm_source,
        "load.e1rm_source",
        None,
        source=threshold_path,
        raw=thresholds_raw,
    )
    add(
        "prescription.load.e1rm_robust_window_days",
        "Robust e1RM window",
        thresholds.e1rm_robust_window_days,
        "load.e1rm_robust_window_days",
        "days",
        source=threshold_path,
        raw=thresholds_raw,
    )
    add(
        "prescription.session_time_cap_s",
        "Session-time target",
        thresholds.session_time_cap_s,
        "prescription.session_time_cap_s",
        "seconds",
        source=threshold_path,
        raw=thresholds_raw,
    )
    add(
        "prescription.testing.min_interval_days",
        "Minimum test interval",
        thresholds.test_min_interval_days,
        "testing.min_interval_days",
        "days",
        source=threshold_path,
        raw=thresholds_raw,
    )
    add(
        "prescription.testing.max_single_min_interval_days",
        "Maximum-single interval",
        thresholds.test_max_single_min_interval_days,
        "testing.max_single_min_interval_days",
        "days",
        source=threshold_path,
        raw=thresholds_raw,
    )
    add(
        "volume.window_weeks",
        "Volume window",
        volume_cfg.window_weeks,
        "window_weeks",
        "weeks",
        source=volume_path,
        raw=volume_raw,
        default_source="python-default: strength_coach/features/volume.py",
    )
    add(
        "volume.ledger.coverage",
        "Volume ledger coverage",
        volume_cfg.ledger_coverage,
        "ledger.coverage",
        None,
        source=volume_path,
        raw=volume_raw,
        default_source="python-default: strength_coach/features/volume.py",
    )
    add(
        "volume.ledger.set_accounting",
        "Volume set accounting",
        volume_cfg.set_accounting,
        "ledger.set_accounting",
        None,
        source=volume_path,
        raw=volume_raw,
        default_source="python-default: strength_coach/features/volume.py",
    )
    add(
        "volume.apply_mrv_cap",
        "Apply MRV cap",
        volume_cfg.apply_mrv_cap,
        "apply_mrv_cap",
        None,
        source=volume_path,
        raw=volume_raw,
        default_source="python-default: strength_coach/features/volume.py",
    )
    add(
        "volume.under_mev.enabled",
        "Under-MEV top-up",
        volume_cfg.under_mev_enabled,
        "under_mev.enabled",
        None,
        source=volume_path,
        raw=volume_raw,
        default_source="python-default: strength_coach/features/volume.py",
    )
    total_source, total_kind, total_configured = _budget_total_provenance(
        volume_raw,
        volume_local,
        explicit="budget.weekly_total",
        map_key="budget.weekly_target",
    )
    rows.append(
        _parameter(
            "volume.budget.weekly_total",
            "Weekly volume target",
            budget.weekly_total if budget.weekly_total is not None else budget.total_target(),
            source=total_source,
            source_kind=total_kind,
            unit="sets",
            configured=total_configured,
            editability="read_only",
            reason="Prescription/volume policy; editing is not part of this workstream.",
            doc="docs/WEB-UI.md",
        )
    )
    effective_source, effective_kind, effective_configured = _budget_total_provenance(
        volume_raw,
        volume_local,
        explicit="budget.weekly_total_effective",
        map_key="budget.weekly_target_effective",
        fallback_map="budget.weekly_target",
    )
    rows.append(
        _parameter(
            "volume.budget.weekly_total_effective",
            "Effective weekly target",
            budget.weekly_total_effective
            if budget.weekly_total_effective is not None
            else budget.total_for("effective"),
            source=effective_source,
            source_kind=effective_kind,
            unit="sets",
            configured=effective_configured,
            editability="read_only",
            reason="Prescription/volume policy; editing is not part of this workstream.",
            doc="docs/WEB-UI.md",
        )
    )
    return {"key": "prescription", "label": "Prescription and volume", "parameters": rows}


def _analysis_group() -> dict[str, Any]:
    module = "code: strength_coach/features/monitoring_analysis.py"
    return {
        "key": "analysis",
        "label": "Analysis constants",
        "parameters": [
            _parameter(
                "analysis.version",
                "Monitoring analysis version",
                monitoring_analysis.ANALYSIS_VERSION,
                source=module,
                source_kind="fixed_code",
                configured=False,
                editability="fixed",
                reason="Code constant.",
                doc="docs/MONITORING-ANALYSIS.md",
            ),
            _parameter(
                "analysis.seed",
                "Monitoring analysis seed",
                monitoring_analysis.SEED,
                source=module,
                source_kind="fixed_code",
                configured=False,
                editability="fixed",
                reason="Reproducibility constant.",
                doc="docs/MONITORING-ANALYSIS.md",
            ),
            _parameter(
                "analysis.correlation_min_pairs",
                "Minimum pairs for a correlation",
                monitoring_analysis.MIN_CORRELATION_PAIRS,
                source=module,
                source_kind="fixed_code",
                configured=False,
                unit="pairs",
                editability="fixed",
                reason="Insufficient-data rule; not a user setting.",
                doc="docs/MONITORING-ANALYSIS.md",
            ),
        ],
    }


def build_inventory(today: str | None = None) -> dict[str, Any]:
    on_date = today or datetime.date.today().isoformat()
    if on_date < PHASE_5A_START:
        period = "before"
        phase_note = "Phase 5A has not started; monitoring and exposure values are locked."
    elif on_date <= PHASE_5A_REVIEW:
        period = "active"
        phase_note = "Phase 5A is active; monitoring and exposure values are locked."
    else:
        period = "post_review"
        phase_note = (
            "Phase 5A review date has passed; monitoring values remain locked until the "
            "review outcome is recorded."
        )
    groups = [
        _monitoring_group(),
        _exposure_group(),
        _calibration_group(),
        _relationship_group(),
        _readiness_group(),
        _prescription_group(),
        _analysis_group(),
    ]
    return {
        "application_version": __version__,
        "revision": revision(groups),
        "read_only": True,
        "phase": {
            "name": "Phase 5A",
            "period": period,
            "start": PHASE_5A_START,
            "review_due": PHASE_5A_REVIEW,
            "locked": True,
            "note": phase_note,
        },
        "groups": groups,
        "notes": [
            "Visible on the home network; this inventory is read-only.",
            "Writes, when added, remain loopback-only through the existing mutation guard.",
            "No athlete records or database contents are included.",
        ],
    }
