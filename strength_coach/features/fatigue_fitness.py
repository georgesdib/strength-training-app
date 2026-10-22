"""Strength-only fitness-fatigue shadow model (roadmap §4.16).

Per canonical lift, and overall across lifts, hard-set load feeds a slow fitness term and a
fast fatigue term; a linear model is fitted to the athlete's own e1RM observations. It is a
diagnostic: nothing here changes a load. Half-lives are fixed rather than fitted, because four
free parameters are not identifiable from ~3 sessions/week (docs/FATIGUE-FITNESS.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from strength_coach.features import derived
from strength_coach.store import queries
from strength_coach.utils import exercises, paths


@dataclass(frozen=True)
class ModelConfig:
    enabled: bool
    fitness_half_life_days: float
    fatigue_half_life_days: float
    min_observations: int
    min_span_days: int
    min_r2: float
    max_condition: float
    pooling_k: float
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "ModelConfig":
        source = Path(path or paths.fatigue_fitness_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            fitness_half_life_days=float(raw.get("fitness_half_life_days", 42)),
            fatigue_half_life_days=float(raw.get("fatigue_half_life_days", 4)),
            min_observations=int(raw.get("min_observations", 8)),
            min_span_days=int(raw.get("min_span_days", 28)),
            min_r2=float(raw.get("min_r2", 0.30)),
            max_condition=float(raw.get("max_condition", 1e8)),
            pooling_k=float(raw.get("pooling_k", 10)),
            source_path=source,
        )


@dataclass(frozen=True)
class LiftModel:
    exercise_id: str
    family: str | None
    status: str                 # ok | weak fit | insufficient | unstable
    n_observations: int
    span_days: int
    condition: float | None
    r2: float | None
    latest_e1rm: float | None
    latest_on: str | None
    predicted_e1rm: float | None
    fitness_kg: float | None
    fatigue_kg: float | None
    state_kg: float | None
    params: dict[str, float] | None
    unit: str = "kg"
    fitness_ci_low: float | None = None
    fitness_ci_high: float | None = None
    fatigue_ci_low: float | None = None
    fatigue_ci_high: float | None = None
    state_ci_low: float | None = None
    state_ci_high: float | None = None
    backtest_mae: float | None = None
    backtest_naive_mae: float | None = None
    backtest_n: int = 0
    scale_kg: float | None = None

    def as_dict(self) -> dict[str, Any]:
        def r(value):
            return None if value is None else round(float(value), 2)
        return {
            "exercise_id": self.exercise_id,
            "family": self.family,
            "status": self.status,
            "unit": self.unit,
            "n_observations": self.n_observations,
            "span_days": self.span_days,
            "condition": None if self.condition is None else round(self.condition, 2),
            "r2": None if self.r2 is None else round(self.r2, 3),
            "latest_e1rm": r(self.latest_e1rm),
            "latest_on": self.latest_on,
            "predicted_e1rm": r(self.predicted_e1rm),
            "fitness_kg": r(self.fitness_kg),
            "fatigue_kg": r(self.fatigue_kg),
            "state_kg": r(self.state_kg),
            "fitness_ci": [r(self.fitness_ci_low), r(self.fitness_ci_high)],
            "fatigue_ci": [r(self.fatigue_ci_low), r(self.fatigue_ci_high)],
            "state_ci": [r(self.state_ci_low), r(self.state_ci_high)],
            "backtest_mae": r(self.backtest_mae),
            "backtest_naive_mae": r(self.backtest_naive_mae),
            "backtest_n": self.backtest_n,
            "scale_kg": r(self.scale_kg),
            "params": self.params,
        }


def _canonical(exercise_id: str, entities) -> str:
    return str(entities.get(exercise_id, {}).get("history_equivalent_of") or exercise_id)


def _arrays(loads: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return (
        loads["date"].to_numpy(dtype="datetime64[ns]"),
        loads["load"].to_numpy(dtype=float),
    )


def _decay_arrays(dates: np.ndarray, values: np.ndarray, at: pd.Timestamp,
                  half_life: float) -> float:
    if len(dates) == 0:
        return 0.0
    ages = (np.datetime64(at) - dates) / np.timedelta64(1, "D")
    mask = ages >= 0
    if not mask.any():
        return 0.0
    return float((values[mask] * (0.5 ** (ages[mask] / half_life))).sum())


def _decay(loads: pd.DataFrame, on_date: pd.Timestamp, half_life: float) -> float:
    dates, values = _arrays(loads)
    return _decay_arrays(dates, values, on_date, half_life)


def _fit_model(
    exercise_id: str,
    family: str | None,
    loads: pd.DataFrame,
    observations: pd.DataFrame,
    cfg: ModelConfig,
    day: pd.Timestamp,
    *,
    unit: str,
    scale: float = 1.0,
    latest_e1rm: float | None = None,
    latest_on: str | None = None,
    shrink: tuple[float, float] | None = None,
    shrink_weight: float = 0.0,
) -> LiftModel:
    """Fit one lift, family or the overall index; refuse rather than fabricate."""
    n = int(len(observations))
    span = (
        int((observations["date"].max() - observations["date"].min()).days)
        if n > 1 else 0
    )
    if n < cfg.min_observations or span < cfg.min_span_days:
        return LiftModel(
            exercise_id, family, "insufficient", n, span, None, None,
            latest_e1rm, latest_on, None, None, None, None, None, unit=unit,
        )

    load_dates, load_values = _arrays(loads)
    rows = []
    for row in observations.itertuples():
        at = row.date
        f = _decay_arrays(load_dates, load_values, at, cfg.fitness_half_life_days)
        t = _decay_arrays(load_dates, load_values, at, cfg.fatigue_half_life_days)
        rows.append((1.0, f, t, float(row.value)))
    design = np.asarray([row[:3] for row in rows], dtype=float)
    target = np.asarray([row[3] for row in rows], dtype=float)
    condition = float(np.linalg.cond(design))
    if np.linalg.matrix_rank(design) < 3 or condition > cfg.max_condition:
        return LiftModel(
            exercise_id, family, "unstable", n, span, condition, None,
            latest_e1rm, latest_on, None, None, None, None, None, unit=unit,
        )
    coeff, *_ = np.linalg.lstsq(design, target, rcond=None)
    fitted = design @ coeff
    ss_res = float(((target - fitted) ** 2).sum())
    ss_tot = float(((target - target.mean()) ** 2).sum())
    r2 = None if ss_tot == 0 else 1.0 - ss_res / ss_tot

    raw_k = (float(coeff[1]), float(coeff[2]))
    if shrink is not None:
        w = max(0.0, min(1.0, shrink_weight))
        coeff[1] = w * coeff[1] + (1.0 - w) * shrink[0]
        coeff[2] = w * coeff[2] + (1.0 - w) * shrink[1]

    dof = n - 3
    sigma2 = ss_res / dof if dof > 0 else 0.0
    try:
        cov = sigma2 * np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError:
        cov = None
    f_now = _decay_arrays(load_dates, load_values, day, cfg.fitness_half_life_days)
    t_now = _decay_arrays(load_dates, load_values, day, cfg.fatigue_half_life_days)
    fitness = float(coeff[1] * f_now * scale)
    fatigue = float(-coeff[2] * t_now * scale)
    state = float((coeff[0] + coeff[1] * f_now + coeff[2] * t_now) * scale)
    fitness_ci = (None, None)
    fatigue_ci = (None, None)
    state_ci = (None, None)
    if cov is not None and np.all(np.isfinite(cov)):
        z = 1.96
        fit_se = float(np.sqrt(max(0.0, cov[1, 1]))) * f_now * scale
        fat_se = float(np.sqrt(max(0.0, cov[2, 2]))) * t_now * scale
        x = np.array([1.0, f_now, t_now])
        state_se = float(np.sqrt(max(0.0, x @ cov @ x))) * scale
        fitness_ci = (fitness - z * fit_se, fitness + z * fit_se)
        fatigue_ci = (fatigue - z * fat_se, fatigue + z * fat_se)
        state_ci = (state - z * state_se, state + z * state_se)

    # Chronological holdout: fit the first 80%, predict the last 20%. The naive baseline is
    # the training mean; a model that cannot beat it is not useful even as a diagnostic.
    backtest_mae = None
    backtest_naive_mae = None
    backtest_n = 0
    if n >= 6:
        cut = max(3, int(n * 0.8))
        train_x, test_x = design[:cut], design[cut:]
        train_y, test_y = target[:cut], target[cut:]
        if len(test_y) >= 2:
            bcoeff, *_ = np.linalg.lstsq(train_x, train_y, rcond=None)
            pred = test_x @ bcoeff
            backtest_mae = float(np.abs(pred - test_y).mean() * scale)
            backtest_naive_mae = float(np.abs(test_y - train_y.mean()).mean() * scale)
            backtest_n = int(len(test_y))

    status = "ok" if r2 is not None and r2 >= cfg.min_r2 else "weak fit"
    return LiftModel(
        exercise_id=exercise_id,
        family=family,
        status=status,
        n_observations=n,
        span_days=span,
        condition=condition,
        r2=r2,
        latest_e1rm=latest_e1rm,
        latest_on=latest_on,
        predicted_e1rm=state,
        fitness_kg=fitness,
        fatigue_kg=fatigue,
        state_kg=state,
        params={
            "intercept": float(coeff[0]),
            "fitness_k": float(coeff[1]),
            "fatigue_k": float(coeff[2]),
            "fitness_k_raw": raw_k[0],
            "fatigue_k_raw": raw_k[1],
            "pooling_weight": round(float(shrink_weight), 3) if shrink else 0.0,
            "fitness_half_life_days": cfg.fitness_half_life_days,
            "fatigue_half_life_days": cfg.fatigue_half_life_days,
        },
        unit=unit,
        fitness_ci_low=fitness_ci[0],
        fitness_ci_high=fitness_ci[1],
        fatigue_ci_low=fatigue_ci[0],
        fatigue_ci_high=fatigue_ci[1],
        state_ci_low=state_ci[0],
        state_ci_high=state_ci[1],
        backtest_mae=backtest_mae,
        backtest_naive_mae=backtest_naive_mae,
        backtest_n=backtest_n,
        scale_kg=scale,
    )


def compute(conn, on_date: str, config: ModelConfig | None = None) -> list[LiftModel]:
    cfg = config or ModelConfig.load()
    if not cfg.enabled:
        return []
    raw = queries.clean_sets(conn)
    if raw.empty:
        return []
    sets = derived.enrich(raw)
    day = pd.Timestamp(on_date)
    entities = exercises.taxonomy().entities
    sets = sets[sets["date"] <= day].copy()
    if sets.empty:
        return []
    sets["canonical"] = [_canonical(str(value), entities) for value in sets["exercise_id"]]

    working = sets[sets["is_working_set"].astype(bool)].copy()
    working = working[working["rir"].isna() | (working["rir"] <= 4)]
    working["load"] = 1.0
    loads = working.groupby(["canonical", "date"], as_index=False)["load"].sum()
    observed = sets[sets["e1rm_kg"].notna()].copy()
    obs = observed.groupby(["canonical", "date"], as_index=False)["e1rm_kg"].max()

    lifts: dict[str, dict] = {}
    for exercise_id in sorted(set(obs["canonical"])):
        if exercise_id.startswith("pattern:"):
            continue
        lift_obs = obs[obs["canonical"] == exercise_id].sort_values("date")
        n = int(len(lift_obs))
        props = entities.get(exercise_id, {})
        primary = bool(props.get("primary_compound") or props.get("main_lift"))
        if n == 0:
            continue
        if n < cfg.min_observations and not primary:
            continue
        lifts[exercise_id] = {
            "obs": lift_obs,
            "loads": loads[loads["canonical"] == exercise_id],
            "family": str(props.get("pattern") or "") or None,
            "primary": primary,
            "median": float(lift_obs["e1rm_kg"].median()),
            "latest": float(lift_obs["e1rm_kg"].iloc[-1]),
            "latest_on": lift_obs["date"].iloc[-1].date().isoformat(),
        }

    # Family common slopes on the relative scale; per-lift slopes are shrunk toward them.
    family_slopes: dict[str, tuple[float, float]] = {}
    groups: dict[str, list[str]] = {}
    for exercise_id, item in lifts.items():
        if item["family"] and len(item["obs"]) >= cfg.min_observations:
            groups.setdefault(item["family"], []).append(exercise_id)
    for family, members in groups.items():
        if len(members) < 2:
            continue
        rows = []
        for exercise_id in members:
            item = lifts[exercise_id]
            median = item["median"]
            dates, values = _arrays(item["loads"])
            for row in item["obs"].itertuples():
                at = row.date
                f = _decay_arrays(dates, values, at, cfg.fitness_half_life_days)
                t = _decay_arrays(dates, values, at, cfg.fatigue_half_life_days)
                rows.append((1.0, f, t, float(row.e1rm_kg) / median))
        design = np.asarray([row[:3] for row in rows], dtype=float)
        target = np.asarray([row[3] for row in rows], dtype=float)
        if len(target) < cfg.min_observations or np.linalg.matrix_rank(design) < 3:
            continue
        if float(np.linalg.cond(design)) > cfg.max_condition:
            continue
        coeff, *_ = np.linalg.lstsq(design, target, rcond=None)
        family_slopes[family] = (float(coeff[1]), float(coeff[2]))

    out: list[LiftModel] = []

    for exercise_id, item in lifts.items():
        n = int(len(item["obs"]))
        if n < cfg.min_observations:
            out.append(LiftModel(
                exercise_id, item["family"], "insufficient", n, 0, None, None,
                item["latest"], item["latest_on"], None, None, None, None, None,
            ))
            continue
        rel_obs = item["obs"].copy()
        rel_obs["value"] = rel_obs["e1rm_kg"] / item["median"]
        family = item["family"]
        shrink = family_slopes.get(family) if family else None
        weight = n / (n + cfg.pooling_k) if shrink else 0.0
        out.append(_fit_model(
            exercise_id, family, item["loads"], rel_obs.rename(columns={"value": "value"}),
            cfg, day, unit="kg", scale=item["median"],
            latest_e1rm=item["latest"], latest_on=item["latest_on"],
            shrink=shrink, shrink_weight=weight,
        ))

    if lifts:
        relative = pd.concat([
            item["obs"].assign(value=lambda d, m=item["median"]: d["e1rm_kg"] / m)
            for item in lifts.values()
        ], ignore_index=True)
        overall_obs = relative.groupby("date", as_index=False)["value"].mean()
        overall_loads = loads.groupby("date", as_index=False)["load"].sum()
        out.insert(0, _fit_model(
            "overall", "overall", overall_loads, overall_obs, cfg, day, unit="ratio",
        ))
    return out


_CACHE: dict[tuple, list[LiftModel]] = {}
_CACHE_LIMIT = 16


def _cache_key(conn, on_date: str, cfg: ModelConfig) -> tuple | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    path = row[2] if row else ""
    if not path or not os.path.exists(path):
        return None
    stat = os.stat(path)
    return (
        path, stat.st_mtime_ns, stat.st_size, on_date,
        (cfg.fitness_half_life_days, cfg.fatigue_half_life_days,
         cfg.min_observations, cfg.min_span_days, cfg.min_r2,
         cfg.max_condition, cfg.pooling_k),
    )


def compute_cached(conn, on_date: str, config: ModelConfig | None = None) -> list[LiftModel]:
    """Cache the fitted model per database version and date.

    The model is expensive (~2 s on the real log) and is read-only; a fresh connection can
    reuse it until the SQLite file changes (mtime/size key). In-memory stores skip the cache.
    """
    cfg = config or ModelConfig.load()
    key = _cache_key(conn, on_date, cfg)
    if key is None:
        return compute(conn, on_date, cfg)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    report = compute(conn, on_date, cfg)
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = report
    return report


def as_dict(report: list[LiftModel]) -> list[dict[str, Any]]:
    return [row.as_dict() for row in report]
