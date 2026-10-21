"""Calibrate return-to-training retention from the athlete's own gaps.

The fixed continuity bands are the default. This module only proposes a band-specific load
factor when there are enough observed returns and the bootstrap interval is tight; otherwise
the engine keeps the fixed rule. It is a descriptive retention estimate, not a fatigue model.

A "return" is the first session for one lift after a gap of at least `short_days`. The ratio is
the first return session's best working e1RM divided by the last pre-gap session's best working
e1RM. That normalises reps/RIR as far as the e1RM formula allows, while still comparing the
same lift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import os
import re
import tempfile

import numpy as np
import pandas as pd
import yaml

from strength_coach.utils import paths


@dataclass(frozen=True)
class CalibrationConfig:
    enabled: bool = True
    apply: bool = True
    min_returns_per_band: int = 5
    min_total_returns: int = 12
    max_gap_days: int = 365
    min_ratio: float = 0.50
    max_ratio: float = 1.50
    bootstrap_samples: int = 1000
    confidence: float = 0.95
    max_ci_width: float = 0.15
    factor_floor: float = 0.85
    allow_relax_fixed: bool = False
    seed: int = 20261020
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "CalibrationConfig":
        source = Path(path or paths.continuity_calibration_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            apply=bool(raw.get("apply", True)),
            min_returns_per_band=int(raw.get("min_returns_per_band", 5)),
            min_total_returns=int(raw.get("min_total_returns", 12)),
            max_gap_days=int(raw.get("max_gap_days", 365)),
            min_ratio=float(raw.get("min_ratio", 0.50)),
            max_ratio=float(raw.get("max_ratio", 1.50)),
            bootstrap_samples=int(raw.get("bootstrap_samples", 1000)),
            confidence=float(raw.get("confidence", 0.95)),
            max_ci_width=float(raw.get("max_ci_width", 0.15)),
            factor_floor=float(raw.get("factor_floor", 0.85)),
            allow_relax_fixed=bool(raw.get("allow_relax_fixed", False)),
            seed=int(raw.get("seed", 20261020)),
            source_path=source,
        )


def save_allow_relax_fixed(value: bool, path: str | Path | None = None) -> CalibrationConfig:
    """Toggle whether a well-observed band may relax the fixed reduction.

    Line-based update keeps the explanatory comments in the checked-in config.
    """
    source = Path(path or paths.continuity_calibration_yaml())
    text = source.read_text(encoding="utf-8")
    replacement = f"allow_relax_fixed: {'true' if value else 'false'}"
    pattern = re.compile(r"^allow_relax_fixed:\s*(?:true|false)\s*(?:#.*)?$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(replacement, text, count=1)
    else:
        text = text.rstrip() + "\n" + replacement + "\n"
    fd, tmp = tempfile.mkstemp(prefix=source.name + ".", dir=str(source.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, source)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return CalibrationConfig.load(source)


@dataclass(frozen=True)
class BandEstimate:
    band: str
    n: int
    median: float | None
    low: float | None
    high: float | None
    fixed: float
    factor: float
    status: str
    applied: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "n": self.n,
            "median": None if self.median is None else round(self.median, 4),
            "ci_low": None if self.low is None else round(self.low, 4),
            "ci_high": None if self.high is None else round(self.high, 4),
            "fixed": self.fixed,
            "factor": self.factor,
            "status": self.status,
            "applied": self.applied,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Calibration:
    bands: Mapping[str, BandEstimate]
    n_total: int
    applied: bool
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_total": self.n_total,
            "applied": self.applied,
            "note": self.note,
            "bands": {key: value.as_dict() for key, value in self.bands.items()},
        }


def _band(days: int, short_days: int, medium_days: int, long_days: int) -> str | None:
    if days < short_days:
        return None
    if days >= long_days:
        return "long"
    if days >= medium_days:
        return "medium"
    return "short"


def _fixed(band: str, medium_multiplier: float, long_multiplier: float) -> float:
    return {"short": 1.0, "medium": medium_multiplier, "long": long_multiplier}[band]


def _sessions(sets: pd.DataFrame) -> pd.DataFrame:
    if sets.empty or not {"date", "exercise_id", "e1rm_kg"}.issubset(sets.columns):
        return pd.DataFrame(columns=["date", "exercise_id", "e1rm_kg"])
    frame = sets
    if "is_working_set" in frame.columns:
        frame = frame[frame["is_working_set"].astype(bool)]
    frame = frame[["date", "exercise_id", "e1rm_kg"]].dropna()
    if frame.empty:
        return pd.DataFrame(columns=["date", "exercise_id", "e1rm_kg"])
    # One observation per lift/day: the best working-set e1RM that day.
    return (
        frame.groupby(["exercise_id", "date"], as_index=False)["e1rm_kg"].max()
        .sort_values(["exercise_id", "date"])
    )


def _returns(
    sessions: pd.DataFrame,
    *,
    short_days: int,
    medium_days: int,
    long_days: int,
    cfg: CalibrationConfig,
) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {"short": [], "medium": [], "long": []}
    for _exercise_id, group in sessions.groupby("exercise_id", sort=False):
        rows = list(group.itertuples(index=False))
        for previous, current in zip(rows, rows[1:]):
            gap = int((pd.Timestamp(current.date) - pd.Timestamp(previous.date)).days)
            if gap < short_days or gap > cfg.max_gap_days:
                continue
            band = _band(gap, short_days, medium_days, long_days)
            if band is None:
                continue
            before = float(previous.e1rm_kg)
            after = float(current.e1rm_kg)
            if before <= 0:
                continue
            ratio = after / before
            if cfg.min_ratio <= ratio <= cfg.max_ratio:
                out[band].append(ratio)
    return out


def compute(
    sets: pd.DataFrame,
    *,
    short_days: int,
    medium_days: int,
    long_days: int,
    medium_multiplier: float,
    long_multiplier: float,
    config: CalibrationConfig | None = None,
) -> Calibration:
    """Fit band retention; return fixed factors whenever a band is under-powered."""
    cfg = config or CalibrationConfig.load()
    returns = _returns(
        _sessions(sets), short_days=short_days, medium_days=medium_days,
        long_days=long_days, cfg=cfg,
    )
    n_total = sum(len(values) for values in returns.values())
    rng = np.random.default_rng(cfg.seed)
    bands: dict[str, BandEstimate] = {}
    for band in ("short", "medium", "long"):
        fixed = _fixed(band, medium_multiplier, long_multiplier)
        values = np.asarray(returns[band], dtype=float)
        n = len(values)
        median = float(np.median(values)) if n else None
        low = high = None
        if n and cfg.bootstrap_samples > 0:
            draws = rng.choice(values, size=(cfg.bootstrap_samples, n), replace=True)
            estimates = np.median(draws, axis=1)
            alpha = (1.0 - cfg.confidence) / 2.0
            low, high = (float(v) for v in np.quantile(estimates, [alpha, 1.0 - alpha]))
        status = "ok"
        reason = ""
        if n < cfg.min_returns_per_band or n_total < cfg.min_total_returns:
            status = "insufficient"
            reason = (
                f"{n} return(s) in this band, {n_total} total; "
                f"need {cfg.min_returns_per_band}/{cfg.min_total_returns}; fixed rule kept"
            )
        elif low is None or high is None or (high - low) > cfg.max_ci_width:
            status = "uncertain"
            reason = "bootstrap interval is too wide; fixed rule kept"
        elif not cfg.enabled:
            status = "disabled"
            reason = "calibration disabled; fixed rule kept"
        elif not cfg.apply:
            status = "report_only"
            reason = "calibration report only; fixed rule kept"

        factor = fixed
        applied = False
        if status == "ok":
            candidate = min(fixed, median) if not cfg.allow_relax_fixed else median
            factor = max(cfg.factor_floor, min(1.0, float(candidate)))
            if not cfg.allow_relax_fixed and median > fixed:
                factor = fixed
                reason = "model suggests less reduction than the fixed rule; fixed rule kept"
            elif abs(factor - fixed) < 1e-9:
                reason = "calibrated factor equals the fixed rule"
            else:
                reason = f"calibrated from {n} return(s); CI {low:.3f}-{high:.3f}"
                applied = True
        bands[band] = BandEstimate(
            band=band, n=n, median=median, low=low, high=high,
            fixed=fixed, factor=round(float(factor), 4), status=status,
            applied=applied, reason=reason,
        )
    return Calibration(
        bands=bands,
        n_total=n_total,
        applied=any(estimate.applied for estimate in bands.values()),
        note=(
            "Fixed continuity remains the fallback; a calibrated factor is used only when "
            "the band has enough returns and a tight bootstrap interval."
        ),
    )
