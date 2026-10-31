"""Read-only inventory of monitoring and related methodology parameters.

The inventory is intentionally curated. It exposes effective values, their relative source
and whether the UI may edit them; it never exposes database contents or athlete records.
"""

from __future__ import annotations

import datetime
import hashlib
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
    relative_strength,
)
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
    reason: str = "",
    doc: str = "docs/MONITORING-ANALYSIS.md",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "source": source,
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


def _revised_files() -> list[Path]:
    names = [
        "monitoring.v1.yaml",
        "exposure.v1.yaml",
        "e1rm-calibration.v1.yaml",
        "strength-relationships.v1.yaml",
        "thresholds.v1.yaml",
        "volume.v1.yaml",
        "readiness.v1.yaml",
    ]
    files = [paths.config_dir(name) for name in names]
    files.extend(paths.config_dir(name.replace(".v1.yaml", ".local.yaml")) for name in names)
    return [path for path in files if path.is_file()]


def revision() -> str:
    digest = hashlib.sha256()
    for path in _revised_files():
        digest.update(_relative(path).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _monitoring_group() -> dict[str, Any]:
    cfg = monitoring.MonitoringConfig.load()
    raw = _load(paths.config_dir("monitoring.v1.yaml"))
    rows = []

    def add(key, label, value, dotted, unit=None, edit="phase5a_locked"):
        raw_value, configured = _mapping(raw, dotted)
        rows.append(_parameter(
            key, label, value, source=_relative(paths.config_dir("monitoring.v1.yaml")),
            unit=unit, configured=configured, editable=False, editability=edit,
            reason="Monitoring definition; frozen during Phase 5A.",
        ))

    add("monitoring.recent_reference.observations", "Recent reference observations", cfg.recent_observations, "recent_reference.observations", "observations")
    add("monitoring.recent_reference.max_age_days", "Recent reference maximum age", cfg.recent_max_age_days, "recent_reference.max_age_days", "days")
    for key, value in cfg.relative_bands.items():
        add(f"monitoring.relative_intensity.bands.{key}", f"Relative-intensity band: {key}", value, f"relative_intensity.bands.{key}", "ratio")
    add("monitoring.ratios.max_gap_days", "Configured ratio maximum gap", cfg.ratio_max_gap_days, "ratios.max_gap_days", "days")
    add("monitoring.ratios.max_age_days", "Configured ratio maximum age", cfg.ratio_max_age_days, "ratios.max_age_days", "days")
    add("monitoring.ratios.min_observations", "Configured ratio minimum observations", cfg.ratio_min_observations, "ratios.min_observations", "observations")
    add("monitoring.hard_sets.near_failure_max_rir", "Near-failure display cut", cfg.near_failure_max_rir, "hard_sets.near_failure_max_rir", "RIR")
    add("monitoring.power.pattern", "Power pattern", cfg.power_pattern, "power.pattern")
    add("monitoring.session_load.late_feedback_days", "Late-feedback threshold", cfg.late_feedback_days, "session_load.late_feedback_days", "days")
    add("monitoring.session_load.long_session_multiplier", "Long-session display multiplier", cfg.long_session_multiplier, "session_load.long_session_multiplier", "multiplier")
    add("monitoring.comparability.window_weeks", "Comparable-session window", cfg.comparability_window_weeks, "comparability.window_weeks", "weeks")
    add("monitoring.comparability.min_exercise_overlap", "Comparable-session minimum overlap", cfg.comparability_min_overlap, "comparability.min_exercise_overlap", "share")
    add("monitoring.comparability.min_prior_sessions", "Comparable-session minimum priors", cfg.comparability_min_prior_sessions, "comparability.min_prior_sessions", "sessions")
    add("monitoring.display.precision_kg", "Display kg precision", cfg.precision_kg, "display.precision_kg", "decimals")
    add("monitoring.display.precision_pct", "Display percent precision", cfg.precision_pct, "display.precision_pct", "decimals")
    for key, value in cfg.features.items():
        add(f"monitoring.features.{key}", f"Optional feature: {key}", bool(value), f"features.{key}")
    return {"key": "monitoring", "label": "Monitoring definitions", "parameters": rows}


def _exposure_group() -> dict[str, Any]:
    cfg = exposure.ExposureConfig.load()
    raw = _load(paths.exposure_yaml())
    rows = []

    def add(key, label, value, dotted, unit=None):
        _, configured = _mapping(raw, dotted)
        rows.append(_parameter(
            key, label, value, source=_relative(paths.exposure_yaml()), unit=unit,
            configured=configured, editability="phase5a_locked",
            reason="Exposure definition; frozen during Phase 5A.",
        ))

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
    add("exposure.trim.max_sets_per_session", "Exposure trim maximum per session", cfg.trim_max_sets_per_session, "trim.max_sets_per_session", "sets")
    add("exposure.trim.max_sets_per_item", "Exposure trim maximum per item", cfg.trim_max_sets_per_item, "trim.max_sets_per_item", "sets")
    add("exposure.trim.floor_sets", "Exposure trim floor", cfg.trim_floor_sets, "trim.floor_sets", "sets")
    return {"key": "exposure", "label": "Exposure and dose", "parameters": rows}


def _calibration_group() -> dict[str, Any]:
    cfg = e1rm_calibration.E1RMCalibrationConfig.load()
    path = paths.e1rm_calibration_yaml()
    raw = _load(path)
    rows = []

    def add(key, label, value, dotted, unit=None, editability="read_only"):
        _, configured = _mapping(raw, dotted) if dotted else (True, True)
        rows.append(_parameter(
            key, label, value,
            source=_relative(path) if dotted else "code: strength_coach/features/e1rm_calibration.py",
            unit=unit, configured=configured, editability=editability,
            reason="Calibration algorithm input; changing it requires a separate decision.",
            doc="docs/FATIGUE-FITNESS.md",
        ))

    add("calibration.window_days", "Calibration lookback window", e1rm_calibration.DEFAULT_WINDOW_DAYS, None, "days", "fixed")
    add("calibration.apply", "Apply calibration correction", cfg.apply, "apply")
    add("calibration.min_tests", "Minimum measured tests", cfg.min_tests, "min_tests", "tests")
    add("calibration.confidence", "CI confidence", cfg.confidence, "confidence", "share")
    add("calibration.max_correction", "Maximum correction", cfg.max_correction, "max_correction", "share")
    add("calibration.bootstrap_samples", "Bootstrap samples", cfg.bootstrap_samples, "bootstrap_samples", "samples")
    add("calibration.seed", "Bootstrap seed", cfg.seed, "seed")
    add("e1rm.method_version", "e1RM method version", E1RM_METHOD_VERSION, None, None, "fixed")
    return {"key": "calibration", "label": "Calibration context", "parameters": rows}


def _relationship_group() -> dict[str, Any]:
    relationships = relative_strength.load_relationships()
    rows = [_parameter(
        "relationships.count", "Configured relationship count", len(relationships),
        source="config/strength-relationships.v1.yaml", unit="pairs", editability="read_only",
        reason="Pair CRUD is planned separately; this inventory is read-only.",
        doc="docs/MONITORING-ANALYSIS.md",
    )]
    for item in relationships:
        for field, label, unit in [
            ("max_gap_days", "maximum gap", "days"),
            ("max_age_days", "maximum age", "days"),
            ("min_observations", "minimum observations", "observations"),
        ]:
            rows.append(_parameter(
                f"relationships.{item.id}.{field}",
                f"{item.label}: {label}",
                getattr(item, field),
                source="config/strength-relationships.v1.yaml",
                unit=unit,
                editability="read_only",
                reason="Pair configuration; CRUD is a separate workstream.",
                doc="docs/MONITORING-ANALYSIS.md",
            ))
    return {"key": "relationships", "label": "Relative-strength pairs", "parameters": rows}


def _readiness_group() -> dict[str, Any]:
    path = paths.config_dir("readiness.v1.yaml")
    raw = _load(path)
    rows = []

    def add(key, label, value, dotted, unit=None):
        _, configured = _mapping(raw, dotted)
        rows.append(_parameter(
            key, label, value, source=_relative(path), unit=unit,
            configured=configured, editability="read_only",
            reason="Readiness policy is not editable from the monitoring inventory.",
            doc="docs/READINESS.md",
        ))

    add("readiness.merge.strategy", "Readiness merge strategy", _mapping(raw, "merge.strategy", "most_complete")[0], "merge.strategy")
    add("readiness.merge.tie_break", "Readiness tie-break", _mapping(raw, "merge.tie_break", "latest")[0], "merge.tie_break")
    add("readiness.modifier.at_or_below", "Readiness modifier threshold", _mapping(raw, "modifier.at_or_below", 2)[0], "modifier.at_or_below", "score")
    add("readiness.set_reduction.enabled", "Readiness set reduction", _mapping(raw, "set_reduction.enabled", True)[0], "set_reduction.enabled")
    add("readiness.set_reduction.score_below", "Readiness set-reduction threshold", _mapping(raw, "set_reduction.score_below", 0.5)[0], "set_reduction.score_below", "score")
    add("readiness.set_reduction.sets", "Readiness set-reduction sets", _mapping(raw, "set_reduction.sets", 1)[0], "set_reduction.sets", "sets")
    add("readiness.score.baseline_days", "Readiness baseline window", _mapping(raw, "score.baseline_days", 28)[0], "score.baseline_days", "days")
    add("readiness.score.baseline_min_readings", "Readiness baseline minimum readings", _mapping(raw, "score.baseline_min_readings", 7)[0], "score.baseline_min_readings", "readings")
    return {"key": "readiness", "label": "Readiness parameters", "parameters": rows}


def _prescription_group() -> dict[str, Any]:
    threshold_path = paths.config_dir("thresholds.v1.yaml")
    volume_path = paths.config_dir("volume.v1.yaml")
    thresholds = _load(threshold_path)
    volume = _load(volume_path)
    rows = []

    def add(path_key, key, label, default, unit=None, source=threshold_path):
        raw = thresholds if source == threshold_path else volume
        value, configured = _mapping(raw, path_key, default)
        rows.append(_parameter(
            key, label, value, source=_relative(source), unit=unit,
            configured=configured, editability="read_only",
            reason="Prescription/volume policy; editing is not part of this workstream.",
            doc="docs/WEB-UI.md",
        ))

    add("load.increment_kg", "prescription.load.increment_kg", "Load increment", 0.5, "kg")
    add("load.rounding", "prescription.load.rounding", "Load rounding", "down")
    add("load.e1rm_window_days", "prescription.load.e1rm_window_days", "e1RM load window", 84, "days")
    add("load.e1rm_source", "prescription.load.e1rm_source", "e1RM load source", "median")
    add("load.e1rm_robust_window_days", "prescription.load.e1rm_robust_window_days", "Robust e1RM window", 28, "days")
    add("prescription.session_time_cap_s", "prescription.session_time_cap_s", "Session-time target", 4800, "seconds")
    add("testing.min_interval_days", "prescription.testing.min_interval_days", "Minimum test interval", 28, "days")
    add("testing.max_single_min_interval_days", "prescription.testing.max_single_min_interval_days", "Maximum-single interval", 56, "days")
    add("window_weeks", "volume.window_weeks", "Volume window", 4, "weeks", volume_path)
    add("ledger.coverage", "volume.ledger.coverage", "Volume ledger coverage", "unknown", None, volume_path)
    add("ledger.set_accounting", "volume.ledger.set_accounting", "Volume set accounting", "hard", None, volume_path)
    add("apply_mrv_cap", "volume.apply_mrv_cap", "Apply MRV cap", True, None, volume_path)
    add("under_mev.enabled", "volume.under_mev.enabled", "Under-MEV top-up", True, None, volume_path)
    add("budget.weekly_total", "volume.budget.weekly_total", "Weekly volume target", 63, "sets", volume_path)
    add("budget.weekly_total_effective", "volume.budget.weekly_total_effective", "Effective weekly target", 74.25, "sets", volume_path)
    return {"key": "prescription", "label": "Prescription and volume", "parameters": rows}


def _analysis_group() -> dict[str, Any]:
    module = "code: strength_coach/features/monitoring_analysis.py"
    return {
        "key": "analysis",
        "label": "Analysis constants",
        "parameters": [
            _parameter("analysis.version", "Monitoring analysis version", monitoring_analysis.ANALYSIS_VERSION, source=module, editability="fixed", reason="Code constant.", doc="docs/MONITORING-ANALYSIS.md"),
            _parameter("analysis.seed", "Monitoring analysis seed", monitoring_analysis.SEED, source=module, editability="fixed", reason="Reproducibility constant.", doc="docs/MONITORING-ANALYSIS.md"),
            _parameter("analysis.correlation_min_pairs", "Minimum pairs for a correlation", monitoring_analysis.MIN_CORRELATION_PAIRS, source=module, unit="pairs", editability="fixed", reason="Insufficient-data rule; not a user setting.", doc="docs/MONITORING-ANALYSIS.md"),
        ],
    }


def build_inventory(today: str | None = None) -> dict[str, Any]:
    on_date = today or datetime.date.today().isoformat()
    reviewing = on_date <= PHASE_5A_REVIEW
    phase_note = (
        "Phase 5A is active; monitoring and exposure values are locked."
        if reviewing else
        "Phase 5A review is due; monitoring values remain read-only until the outcome is recorded."
    )
    return {
        "application_version": __version__,
        "revision": revision(),
        "read_only": True,
        "phase": {
            "name": "Phase 5A",
            "start": PHASE_5A_START,
            "review_due": PHASE_5A_REVIEW,
            "locked": True,
            "note": phase_note,
        },
        "groups": [
            _monitoring_group(),
            _exposure_group(),
            _calibration_group(),
            _relationship_group(),
            _readiness_group(),
            _prescription_group(),
            _analysis_group(),
        ],
        "notes": [
            "Visible on the home network; this inventory is read-only.",
            "Writes, when added, remain loopback-only through the existing mutation guard.",
            "No athlete records or database contents are included.",
        ],
    }
