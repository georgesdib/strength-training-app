"""Pure monitoring definitions for session summaries and trend views.

These functions group and describe existing observations. They do not prescribe, score, or
change a load. They reuse the hard-set predicate, volume target key and demand catalogue, and
the spinal registry stays outside this module because features must not import rules.

Missing data is returned as Unavailable, never as a zero or a guessed value. Power and
high-intensity-linked sets are excluded from ordinary RIR and relative-intensity distributions
where the caller supplies the explicit link; the power pattern is read from the taxonomy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from strength_coach.domain import rir as rir_mod
from strength_coach.features import exposure as exposure_feature
from strength_coach.features import volume as volume_feature
from strength_coach.features.strength_observations import Unavailable
from strength_coach.utils import paths


@dataclass(frozen=True)
class MonitoringConfig:
    recent_observations: int = 3
    recent_max_age_days: int = 84
    relative_bands: Mapping[str, float] = field(
        default_factory=lambda: {
            "near_max": 0.90,
            "heavy": 0.80,
            "moderate": 0.70,
            "light": 0.60,
            "very_light": 0.0,
        }
    )
    near_failure_max_rir: int = 2
    power_pattern: str = "power_jump"
    late_feedback_days: int = 1
    long_session_multiplier: float = 1.5
    comparability_window_weeks: int = 8
    comparability_min_overlap: float = 0.50
    comparability_min_prior_sessions: int = 3
    precision_kg: int = 1
    precision_pct: int = 1
    features: Mapping[str, bool] = field(default_factory=dict)
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> MonitoringConfig:
        source = Path(path or paths.config_dir("monitoring.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) if source.is_file() else {}
        raw = raw or {}
        recent = raw.get("recent_reference") or {}
        bands = (raw.get("relative_intensity") or {}).get("bands") or {}
        hard = raw.get("hard_sets") or {}
        power = raw.get("power") or {}
        feedback = raw.get("session_load") or {}
        comparison = raw.get("comparability") or {}
        display = raw.get("display") or {}
        return cls(
            recent_observations=int(recent.get("observations", 3)),
            recent_max_age_days=int(recent.get("max_age_days", 84)),
            relative_bands={
                str(key): float(value) for key, value in bands.items()
            } or cls().relative_bands,
            near_failure_max_rir=int(hard.get("near_failure_max_rir", 2)),
            power_pattern=str(power.get("pattern", "power_jump")),
            late_feedback_days=int(feedback.get("late_feedback_days", 1)),
            long_session_multiplier=float(feedback.get("long_session_multiplier", 1.5)),
            comparability_window_weeks=int(comparison.get("window_weeks", 8)),
            comparability_min_overlap=float(comparison.get("min_exercise_overlap", 0.50)),
            comparability_min_prior_sessions=int(comparison.get("min_prior_sessions", 3)),
            precision_kg=int(display.get("precision_kg", 1)),
            precision_pct=int(display.get("precision_pct", 1)),
            features={str(key): bool(value) for key, value in (raw.get("features") or {}).items()},
            source_path=source,
        )


@dataclass(frozen=True)
class VelocityChange:
    exercise_id: str
    load_kg: float
    n: int
    first_mps: float
    last_mps: float
    change_mps: float
    change_pct: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "load_kg": round(self.load_kg, 3),
            "n": self.n,
            "first_mps": round(self.first_mps, 3),
            "last_mps": round(self.last_mps, 3),
            "change_mps": round(self.change_mps, 3),
            "change_pct": round(self.change_pct, 3),
        }


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result


def _working(frame: pd.DataFrame, session_id: str | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    work = frame
    if session_id is not None:
        work = work[work["session_id"].astype(str).eq(str(session_id))]
    if "is_working_set" in work.columns:
        work = work[work["is_working_set"].fillna(False).astype(bool)]
    return work


def _excluded(set_row: Mapping[str, Any], excluded_set_kinds: Mapping[int, str] | None) -> bool:
    if not excluded_set_kinds:
        return False
    try:
        set_id = int(set_row.get("set_id"))
    except (TypeError, ValueError):
        return False
    return set_id in excluded_set_kinds


def completed_working_sets(frame: pd.DataFrame, session_id: str) -> int:
    return int(len(_working(frame, session_id)))


def completed_reps(frame: pd.DataFrame, session_id: str) -> int | Unavailable:
    work = _working(frame, session_id)
    if work.empty:
        return 0
    rows = work[work["reps_unit"].astype(str).eq("reps")] if "reps_unit" in work else work
    if rows.empty:
        return 0
    values = pd.to_numeric(rows["reps"], errors="coerce")
    if values.isna().any():
        return Unavailable("reps are missing for at least one working set", "unavailable")
    return int(values.sum())


def exercise_tonnage(frame: pd.DataFrame, exercise_id: str) -> float | Unavailable:
    if frame is None or frame.empty:
        return 0.0
    work = _working(frame)
    work = work[work["exercise_id"].astype(str).eq(str(exercise_id))]
    if work.empty:
        return 0.0
    if "tonnage_kg" in work.columns:
        values = pd.to_numeric(work["tonnage_kg"], errors="coerce")
        if values.isna().any():
            return Unavailable("tonnage is missing for at least one working set", "unavailable")
        return float(values.sum())
    return Unavailable("tonnage is not available in the frame", "unavailable")


def hard_sets(
    frame: pd.DataFrame,
    config: exposure_feature.ExposureConfig | None = None,
) -> int:
    cfg = config or exposure_feature.ExposureConfig.load()
    return int(exposure_feature.hard_set_mask(frame, cfg).sum())


def near_failure_sets(
    frame: pd.DataFrame,
    config: MonitoringConfig | None = None,
) -> int:
    cfg = config or MonitoringConfig.load()
    if frame is None or frame.empty or "rir" not in frame.columns:
        return 0
    work = _working(frame)
    rir = pd.to_numeric(work["rir"], errors="coerce")
    return int((rir.notna() & (rir <= cfg.near_failure_max_rir)).sum())


def rir_distribution(frame: pd.DataFrame) -> dict[str, int]:
    counts: dict[str, int] = {str(value): 0 for value in range(6)}
    counts.update({"missing": 0, "warmup": 0, "other": 0})
    if frame is None or frame.empty or "rir" not in frame.columns:
        return counts
    for value in frame["rir"]:
        reading = rir_mod.classify(value)
        if reading.klass == "effort":
            counts[str(int(reading.value))] += 1
        elif reading.klass == "warmup":
            counts["warmup"] += 1
        elif reading.klass == "missing":
            counts["missing"] += 1
        else:
            counts["other"] += 1
    return counts


def _load_for_intensity(set_row: Mapping[str, Any]) -> float | Unavailable:
    load = _number(set_row.get("load_kg"))
    if load is None or load <= 0:
        return Unavailable("load is missing or non-positive", "unavailable")
    basis = str(set_row.get("load_basis") or "")
    if basis == "added":
        total = _number(set_row.get("total_load_kg"))
        if total is None or total <= load:
            return Unavailable("added-load total mass is unresolved", "unavailable")
        return total
    if basis not in {"external", "bodyweight_total"}:
        return Unavailable("load basis is unknown", "unavailable")
    return load


def relative_intensity(
    set_row: Mapping[str, Any],
    load_base: float | Any,
) -> float | Unavailable:
    load = _load_for_intensity(set_row)
    if isinstance(load, Unavailable):
        return load
    base = _number(getattr(load_base, "kg", load_base))
    if base is None or base <= 0:
        return Unavailable("load-base e1RM is unavailable", "unavailable")
    return load / base


def relative_intensity_distribution(
    sets: pd.DataFrame,
    load_base_by_exercise: Mapping[str, float | Any],
    config: MonitoringConfig | None = None,
    *,
    excluded_set_kinds: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    cfg = config or MonitoringConfig.load()
    counts: dict[str, int] = {band: 0 for band in cfg.relative_bands}
    counts["unknown"] = 0
    if sets is None or sets.empty:
        counts["n"] = 0
        return counts
    work = _working(sets)
    for row in work.to_dict("records"):
        if _excluded(row, excluded_set_kinds):
            continue
        exercise_id = str(row.get("exercise_id") or "")
        value = relative_intensity(row, load_base_by_exercise.get(exercise_id, 0.0))
        if isinstance(value, Unavailable):
            counts["unknown"] += 1
            continue
        for band, threshold in sorted(
            cfg.relative_bands.items(), key=lambda item: item[1], reverse=True
        ):
            if value >= threshold:
                counts[band] += 1
                break
    counts["n"] = int(work.shape[0])
    return counts


def session_load(feedback: Mapping[str, Any]) -> float | Unavailable:
    srpe = _number(feedback.get("srpe"))
    duration = _number(feedback.get("duration_min"))
    if srpe is None or duration is None:
        return Unavailable("sRPE and duration are both required", "unavailable")
    if srpe <= 0 or duration <= 0:
        return Unavailable("sRPE and duration must be positive", "invalid")
    return srpe * duration


def power_exposure(
    frame: pd.DataFrame,
    taxonomy: Mapping[str, Mapping[str, Any]],
    config: MonitoringConfig | None = None,
) -> dict[str, Any]:
    cfg = config or MonitoringConfig.load()
    if frame is None or frame.empty:
        return {"sets": 0, "reps": 0, "exercises": []}
    work = _working(frame)
    selected = []
    for row in work.to_dict("records"):
        props = taxonomy.get(str(row.get("exercise_id") or ""), {})
        if str(props.get("pattern") or "") == cfg.power_pattern:
            selected.append(row)
    reps = sum(int(_number(row.get("reps")) or 0) for row in selected)
    return {
        "sets": len(selected),
        "reps": reps,
        "exercises": sorted({str(row.get("exercise_id")) for row in selected}),
    }


def mean_velocity_change(
    frame: pd.DataFrame,
    exercise_id: str,
    load_kg: float,
) -> VelocityChange | Unavailable:
    if frame is None or frame.empty:
        return Unavailable("no sets", "unavailable")
    work = _working(frame)
    work = work[work["exercise_id"].astype(str).eq(str(exercise_id))]
    if "velocity_present" in work.columns:
        work = work[work["velocity_present"].fillna(False).astype(bool)]
    work = work.copy()
    work["_velocity"] = pd.to_numeric(work["velocity_mps"], errors="coerce")
    work["_load"] = pd.to_numeric(work["load_kg"], errors="coerce")
    work = work[
        work["_velocity"].notna()
        & (work["_velocity"] > 0)
        & (work["_load"] - float(load_kg)).abs().le(1e-6)
    ].sort_values(["date", "set_id"])
    if len(work) < 2:
        return Unavailable("fewer than two velocity sets at the same load", "unavailable")
    first = float(work["_velocity"].iloc[0])
    last = float(work["_velocity"].iloc[-1])
    change = last - first
    return VelocityChange(
        exercise_id=exercise_id,
        load_kg=float(load_kg),
        n=int(len(work)),
        first_mps=first,
        last_mps=last,
        change_mps=change,
        change_pct=(change / first * 100.0) if first else 0.0,
    )


def spinal_summary(
    precomputed_weekly_costs: Mapping[str, Any] | None,
    session_id: str,
) -> dict[str, Any]:
    """Pass through the registry's weekly costs; never recompute spinal load."""
    if not precomputed_weekly_costs:
        return {"session_id": session_id, "weeks": {}, "status": "unavailable"}
    return {
        "session_id": session_id,
        "weeks": precomputed_weekly_costs,
        "status": "observed",
    }


def pattern_distribution(
    frame: pd.DataFrame,
    taxonomy: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    """Working-set counts by the configured volume target key, never by a new grouping."""
    counts: dict[str, int] = {}
    if frame is None or frame.empty:
        return counts
    for row in _working(frame).to_dict("records"):
        props = taxonomy.get(str(row.get("exercise_id") or ""), {})
        key = volume_feature.volume_target_key(str(props.get("pattern") or "unknown"))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def axial_demand_counts(frame: pd.DataFrame, catalogue: Any) -> dict[str, int]:
    counts = {"high": 0, "moderate": 0, "low": 0, "unknown": 0}
    if frame is None or frame.empty:
        return counts
    for row in _working(frame).to_dict("records"):
        exercise_id = str(row.get("exercise_id") or "")
        if hasattr(catalogue, "profile"):
            level = catalogue.profile(exercise_id)["axial_spinal"]["level"]
        elif hasattr(catalogue, "level"):
            level = catalogue.level(exercise_id, "axial_spinal")
        else:
            level = "unknown"
        counts[str(level) if str(level) in counts else "unknown"] += 1
    return counts
