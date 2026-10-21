"""Measured-test calibration of the formula e1RM.

The estimate is an approximation (Epley+RIR), so measured tests are compared with the
formula value the app would have used before each test. A correction is applied only when
the evidence is consistent: at least `min_tests`, a bootstrap CI of the median ratio that
excludes 1.0, and a median bias within `max_correction`. The correction is clamped to that
bound. Measured overrides are never adjusted.

Why not fit a curve: three to ten tests cannot identify a per-rep or per-load correction;
a single robust ratio is the smallest defensible adjustment (`ASSUMPTION-26`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

import numpy as np
import pandas as pd
import yaml

from strength_coach.features import derived
from strength_coach.features import e1rm_decay
from strength_coach.store import queries
from strength_coach.utils import exercises, paths

DEFAULT_WINDOW_DAYS = 84


@dataclass(frozen=True)
class E1RMCalibrationConfig:
    apply: bool
    min_tests: int
    confidence: float
    max_correction: float
    bootstrap_samples: int
    seed: int
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "E1RMCalibrationConfig":
        source = Path(path or paths.e1rm_calibration_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        return cls(
            apply=bool(raw.get("apply", True)),
            min_tests=int(raw.get("min_tests", 3)),
            confidence=float(raw.get("confidence", 0.95)),
            max_correction=float(raw.get("max_correction", 0.10)),
            bootstrap_samples=int(raw.get("bootstrap_samples", 2000)),
            seed=int(raw.get("seed", 20261020)),
            source_path=source,
        )


@dataclass(frozen=True)
class CalibrationPoint:
    exercise_id: str
    measured_on: str
    measured_kg: float
    predicted_kg: float
    ratio: float
    error_kg: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "measured_on": self.measured_on,
            "measured_kg": round(self.measured_kg, 2),
            "predicted_kg": round(self.predicted_kg, 2),
            "ratio": round(self.ratio, 3),
            "error_kg": round(self.error_kg, 2),
        }


@dataclass(frozen=True)
class LiftCalibration:
    exercise_id: str
    points: tuple[CalibrationPoint, ...]
    ci_low: float | None = None
    ci_high: float | None = None
    correction_factor: float = 1.0
    correction_applied: bool = False
    correction_reason: str = ""
    # Current formula e1RM context, shown even when there is no measured test to calibrate
    # against. This is the useful part of the report before the first test.
    latest_e1rm: float | None = None
    latest_on: str | None = None
    set_count: int = 0
    # Both sources are always displayed, even when only one is used.
    formula_raw: float | None = None
    formula_effective: float | None = None
    override_raw: float | None = None
    override_effective: float | None = None
    active_source: str | None = None       # formula | override
    active_e1rm: float | None = None

    @property
    def n(self) -> int:
        return len(self.points)

    @property
    def median_ratio(self) -> float | None:
        return median(p.ratio for p in self.points) if self.points else None

    @property
    def mean_bias_kg(self) -> float | None:
        return mean(p.error_kg for p in self.points) if self.points else None

    @property
    def mae_kg(self) -> float | None:
        return mean(abs(p.error_kg) for p in self.points) if self.points else None

    @property
    def status(self) -> str:
        if not self.points:
            return "no measured test; formula only"
        if self.correction_applied:
            return f"applied x{self.correction_factor:.3f}"
        return self.correction_reason or "report only"

    def as_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "n": self.n,
            "median_ratio": None if self.median_ratio is None else round(self.median_ratio, 3),
            "mean_bias_kg": None if self.mean_bias_kg is None else round(self.mean_bias_kg, 2),
            "mae_kg": None if self.mae_kg is None else round(self.mae_kg, 2),
            "ci_low": None if self.ci_low is None else round(self.ci_low, 3),
            "ci_high": None if self.ci_high is None else round(self.ci_high, 3),
            "correction_factor": round(self.correction_factor, 3),
            "correction_applied": self.correction_applied,
            "latest_e1rm": None if self.latest_e1rm is None else round(self.latest_e1rm, 2),
            "latest_on": self.latest_on,
            "set_count": self.set_count,
            "formula_raw": None if self.formula_raw is None else round(self.formula_raw, 2),
            "formula_effective": None if self.formula_effective is None else round(self.formula_effective, 2),
            "override_raw": None if self.override_raw is None else round(self.override_raw, 2),
            "override_effective": None if self.override_effective is None else round(self.override_effective, 2),
            "active_source": self.active_source,
            "active_e1rm": None if self.active_e1rm is None else round(self.active_e1rm, 2),
            "status": self.status,
            "points": [point.as_dict() for point in self.points],
        }


def _canonical(exercise_id: str, entities) -> str:
    return str(entities.get(exercise_id, {}).get("history_equivalent_of") or exercise_id)


def _bootstrap_median_ci(
    values: list[float], *, confidence: float, samples: int, seed: int
) -> tuple[float, float]:
    """Deterministic percentile CI for the median (n is small, so bootstrap)."""
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    draws = rng.choice(array, size=(samples, array.size), replace=True)
    medians = np.median(draws, axis=1)
    alpha = (1.0 - confidence) / 2.0
    return float(np.quantile(medians, alpha)), float(np.quantile(medians, 1.0 - alpha))


def _correction(
    ratios: list[float], cfg: E1RMCalibrationConfig
) -> tuple[float, float, float, bool, str]:
    if len(ratios) < cfg.min_tests:
        return 1.0, None, None, False, f"{len(ratios)} test(s); need {cfg.min_tests}"
    low, high = _bootstrap_median_ci(
        ratios, confidence=cfg.confidence, samples=cfg.bootstrap_samples, seed=cfg.seed
    )
    med = float(median(ratios))
    if low <= 1.0 <= high:
        return 1.0, low, high, False, "no correction: CI includes 1.0"
    if abs(med - 1.0) > cfg.max_correction:
        return 1.0, low, high, False, "no correction: bias exceeds the configured bound"
    if not cfg.apply:
        return 1.0, low, high, False, "no correction: disabled in config"
    factor = max(1.0 - cfg.max_correction, min(1.0 + cfg.max_correction, med))
    return factor, low, high, True, f"applied x{factor:.3f}"


def build(
    conn,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    as_of: str | None = None,
    config: E1RMCalibrationConfig | None = None,
) -> list[LiftCalibration]:
    """Per-lift formula e1RM context plus any measured-test calibration.

    Rows are not limited to lifts with a measured test: before the first test the current
    formula e1RM and last set are still useful context, and the status says "formula only".
    """
    cfg = config or E1RMCalibrationConfig.load()
    overrides = [
        row for row in queries.e1rm_overrides(conn)
        if row.get("source") == "measured"
        and (as_of is None or str(row["effective_from"]) <= as_of)
    ]
    entities = exercises.taxonomy().entities
    raw_sets = queries.clean_sets(conn)
    sets = derived.enrich(raw_sets) if not raw_sets.empty else raw_sets
    day = pd.Timestamp(as_of) if as_of else pd.Timestamp.today().normalize()
    cutoff = day - pd.Timedelta(days=window_days)

    points: dict[str, list[CalibrationPoint]] = {}
    if not sets.empty:
        for override in overrides:
            exercise_id = _canonical(str(override["exercise_id"]), entities)
            measured_on = str(override["effective_from"])
            prior = sets[
                sets["exercise_id"].map(
                    lambda value: _canonical(str(value), entities) == exercise_id
                )
                & sets["e1rm_kg"].notna()
                & (sets["date"] < pd.Timestamp(measured_on))
                & (sets["date"] >= pd.Timestamp(measured_on) - pd.Timedelta(days=window_days))
            ]
            if prior.empty:
                continue
            predicted = float(prior["e1rm_kg"].max())
            measured = float(override["e1rm_kg"])
            points.setdefault(exercise_id, []).append(CalibrationPoint(
                exercise_id=exercise_id,
                measured_on=measured_on,
                measured_kg=measured,
                predicted_kg=predicted,
                ratio=measured / predicted if predicted else 0.0,
                error_kg=measured - predicted,
            ))

    summaries: dict[str, dict[str, Any]] = {}
    all_summaries: dict[str, dict[str, Any]] = {}
    if not sets.empty:
        working = sets[
            sets["is_working_set"].astype(bool)
            & sets["e1rm_kg"].notna()
            & (sets["date"] <= day)
        ].copy()
        if not working.empty:
            working["canonical"] = [
                _canonical(str(value), entities) for value in working["exercise_id"]
            ]
            for key, group in working.groupby("canonical", sort=True):
                all_summaries[str(key)] = {
                    "latest_e1rm": float(group["e1rm_kg"].max()),
                    "latest_on": group["date"].max().date().isoformat(),
                    "set_count": int(len(group)),
                }
        current = working[working["date"] >= cutoff]
        if not current.empty:
            for key, group in current.groupby("canonical", sort=True):
                summaries[str(key)] = {
                    "latest_e1rm": float(group["e1rm_kg"].max()),
                    "latest_on": group["date"].max().date().isoformat(),
                    "set_count": int(len(group)),
                }

    # Applicable overrides on the as-of date, keyed by canonical lift. Both sources are
    # reported; the override wins the load basis exactly as it does in the engine.
    active_overrides: dict[str, dict[str, Any]] = {}
    for override in overrides:
        key = _canonical(str(override["exercise_id"]), entities)
        if str(override["effective_from"]) > day.date().isoformat():
            continue
        if override.get("expires_on") and str(override["expires_on"]) < day.date().isoformat():
            continue
        previous = active_overrides.get(key)
        if previous is None or (
            str(override["effective_from"]), int(override["override_id"])
        ) >= (str(previous["effective_from"]), int(previous["override_id"])):
            active_overrides[key] = override

    cfg_decay = e1rm_decay.DecayConfig.load()
    out: list[LiftCalibration] = []
    for key in sorted(set(points) | set(summaries)):
        ordered = tuple(sorted(points.get(key, []), key=lambda p: p.measured_on))
        factor, low, high, applied, reason = _correction(
            [point.ratio for point in ordered], cfg
        )
        summary = summaries.get(key) or all_summaries.get(key, {})
        formula_raw = summary.get("latest_e1rm")
        formula_on = summary.get("latest_on")
        formula_effective = None
        if formula_raw is not None and formula_on:
            age = (day.date() - pd.Timestamp(formula_on).date()).days
            formula_effective = float(formula_raw) * factor * e1rm_decay.factor(age, cfg_decay)
        override = active_overrides.get(key)
        override_raw = None if override is None else float(override["e1rm_kg"])
        override_effective = None
        if override is not None:
            age = (day.date() - pd.Timestamp(str(override["effective_from"])).date()).days
            override_effective = override_raw * e1rm_decay.factor(age, cfg_decay)
        source = "override" if override_effective is not None else (
            "formula" if formula_effective is not None else None
        )
        active = override_effective if override_effective is not None else formula_effective
        out.append(LiftCalibration(
            exercise_id=key,
            points=ordered,
            ci_low=low,
            ci_high=high,
            correction_factor=factor,
            correction_applied=applied,
            correction_reason=reason,
            latest_e1rm=formula_raw,
            latest_on=formula_on,
            set_count=int(summary.get("set_count", 0)),
            formula_raw=formula_raw,
            formula_effective=formula_effective,
            override_raw=override_raw,
            override_effective=override_effective,
            active_source=source,
            active_e1rm=active,
        ))
    return out


def factors(
    conn,
    on_date: str,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    config: E1RMCalibrationConfig | None = None,
) -> dict[str, LiftCalibration]:
    """Per-lift corrections in force on `on_date`; only applied rows have factor != 1."""
    report = build(conn, window_days=window_days, as_of=on_date, config=config)
    return {row.exercise_id: row for row in report if row.correction_applied}


def as_dict(report: list[LiftCalibration]) -> list[dict[str, Any]]:
    return [row.as_dict() for row in report]
