"""Minimal Phase-1 diagnostics for the strength fitness-fatigue shadow model.

No model change, no prediction log, no prospective protocol. The output is a chronological
comparison of simple baselines and the current fitness/fatigue structure, per lift.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from strength_coach.features import derived
from strength_coach.store import queries

PRIMARY_LIFTS = ("ssb_squat", "bench_press", "trap_bar_deadlift")


@dataclass(frozen=True)
class Forecast:
    model: str
    predicted: float
    actual: float
    error: float
    horizon_days: int
    date: str


def _days(a: str, b: str) -> int:
    return (dt.date.fromisoformat(str(b)[:10]) - dt.date.fromisoformat(str(a)[:10])).days


def _feature_map(loads: pd.DataFrame, dates: list[str], half_life: float) -> dict[str, float]:
    values = {}
    for when in dates:
        prior = loads[loads["date"] < pd.Timestamp(when)]
        if prior.empty:
            values[str(when)] = 0.0
            continue
        age = (pd.Timestamp(when) - prior["date"]).dt.days.astype(float)
        values[str(when)] = float((prior["hard_sets"] * np.power(0.5, age / half_life)).sum())
    return values


def _features(loads: pd.DataFrame, when: str, half_life: float,
              cache: dict[str, float] | None = None) -> float:
    if cache is not None:
        return float(cache.get(str(when), 0.0))
    prior = loads[loads["date"] < pd.Timestamp(when)]
    if prior.empty:
        return 0.0
    age = (pd.Timestamp(when) - prior["date"]).dt.days.astype(float)
    return float((prior["hard_sets"] * np.power(0.5, age / half_life)).sum())


def _fit_predict(obs: pd.DataFrame, loads: pd.DataFrame, target_date: str,
                 *, fatigue: bool, fit_cache: dict[str, float],
                 fatigue_cache: dict[str, float]) -> float | None:
    x = []
    y = []
    for _, row in obs.iterrows():
        fit = _features(loads, row["date"].isoformat(), 42.0, fit_cache)
        values = [1.0, fit]
        if fatigue:
            values.append(_features(loads, row["date"].isoformat(), 4.0,
                                    fatigue_cache))
        x.append(values)
        y.append(float(row["e1rm_kg"]))
    if len(y) < 4:
        return None
    fit_target = _features(loads, target_date, 42.0, fit_cache)
    vector = [1.0, fit_target]
    if fatigue:
        vector.append(_features(loads, target_date, 4.0, fatigue_cache))
    try:
        coeff, *_ = np.linalg.lstsq(np.asarray(x, dtype=float),
                                    np.asarray(y, dtype=float), rcond=None)
        return float(np.asarray(vector, dtype=float) @ coeff)
    except np.linalg.LinAlgError:
        return None


def _metrics(forecasts: list[Forecast]) -> dict:
    if not forecasts:
        return {"n": 0}
    errors = np.asarray([item.error for item in forecasts], dtype=float)
    absolute = np.abs(errors)
    return {
        "n": len(forecasts),
        "mae": round(float(absolute.mean()), 3),
        "rmse": round(float(np.sqrt(np.mean(errors ** 2))), 3),
        "bias": round(float(errors.mean()), 3),
        "median_ae": round(float(np.median(absolute)), 3),
        "q80": round(float(np.quantile(absolute, 0.8)), 3),
        "q90": round(float(np.quantile(absolute, 0.9)), 3),
        "horizon_median_days": int(np.median([item.horizon_days for item in forecasts])),
    }


def diagnose(conn, *, lifts: tuple[str, ...] = PRIMARY_LIFTS,
             min_history: int = 6, max_observations: int | None = None) -> dict:
    frame = derived.enrich(queries.clean_sets(conn))
    frame = frame[frame["is_working_set"] & frame["e1rm_kg"].notna()]
    hard = frame[frame["rir"].notna() & (frame["rir"] <= 4)]
    out = {}
    for lift in lifts:
        lift_frame = frame[frame["exercise_id"] == lift]
        if lift_frame.empty:
            out[lift] = {"status": "no observations"}
            continue
        observed = (lift_frame.sort_values(["date", "session_id"])
                    .groupby("session_id", as_index=False)
                    .agg(date=("date", "max"), e1rm_kg=("e1rm_kg", "max"),
                         sets=("e1rm_kg", "size")))
        observed = observed.sort_values(["date", "session_id"]).reset_index(drop=True)
        if max_observations:
            observed = observed.tail(int(max_observations)).reset_index(drop=True)
        loads = (hard[hard["exercise_id"] == lift]
                 .groupby("date", as_index=False).size()
                 .rename(columns={"size": "hard_sets"}))
        diffs = np.abs(np.diff(observed["e1rm_kg"].to_numpy(dtype=float)))
        pct_changes = (np.abs(np.diff(observed["e1rm_kg"].to_numpy(dtype=float)))
                       / observed["e1rm_kg"].to_numpy(dtype=float)[:-1] * 100)
        noise = {
            "median_abs_consecutive_change": (round(float(np.median(diffs)), 3)
                                               if len(diffs) else None),
            "q80_abs_consecutive_change": (round(float(np.quantile(diffs, 0.8)), 3)
                                            if len(diffs) else None),
            "large_jumps_over_10pct": int((pct_changes > 10).sum()),
        }
        all_dates = [str(value)[:10] for value in observed["date"]]
        fit_cache = _feature_map(loads, all_dates, 42.0)
        fatigue_cache = _feature_map(loads, all_dates, 4.0)
        forecasts = {name: [] for name in
                     ("persistence", "rolling_median", "trend", "fitness_only", "full")}
        rows = []
        for index in range(min_history, len(observed)):
            history = observed.iloc[:index]
            target = observed.iloc[index]
            prior = history.iloc[-1]
            horizon = _days(prior["date"].isoformat(), target["date"].isoformat())
            predictions = {
                "persistence": float(prior["e1rm_kg"]),
                "rolling_median": float(history["e1rm_kg"].tail(3).median()),
            }
            recent = history.tail(6)
            x = (recent["date"] - recent["date"].iloc[0]).dt.days.to_numpy(dtype=float)
            if len(recent) >= 3 and np.ptp(x) > 0:
                coeff = np.polyfit(x, recent["e1rm_kg"].to_numpy(dtype=float), 1)
                future = float((pd.Timestamp(target["date"]) - recent["date"].iloc[0]).days)
                predictions["trend"] = float(np.polyval(coeff, future))
            else:
                predictions["trend"] = None
            predictions["fitness_only"] = _fit_predict(
                history, loads, target["date"].isoformat(), fatigue=False,
                fit_cache=fit_cache, fatigue_cache=fatigue_cache)
            predictions["full"] = _fit_predict(
                history, loads, target["date"].isoformat(), fatigue=True,
                fit_cache=fit_cache, fatigue_cache=fatigue_cache)
            for model, predicted in predictions.items():
                if predicted is None:
                    continue
                item = Forecast(model=model, predicted=predicted,
                                actual=float(target["e1rm_kg"]),
                                error=float(target["e1rm_kg"]) - predicted,
                                horizon_days=horizon,
                                date=str(target["date"])[:10])
                forecasts[model].append(item)
                rows.append({"date": item.date, "model": model,
                             "predicted": round(predicted, 2),
                             "actual": round(item.actual, 2),
                             "error": round(item.error, 2),
                             "horizon_days": horizon})
        metrics = {name: _metrics(values) for name, values in forecasts.items()}
        scored = {name: value for name, value in metrics.items() if value.get("n")}
        best = min(scored, key=lambda name: scored[name]["mae"]) if scored else None
        out[lift] = {
            "observations": int(len(observed)),
            "span": [str(observed["date"].min())[:10], str(observed["date"].max())[:10]],
            "noise": noise,
            "metrics": metrics,
            "best_baseline": best,
            "rows": rows,
            "duplicates": int(observed["date"].duplicated().sum()),
            "large_jumps_over_10pct": int(noise["large_jumps_over_10pct"]),
        }
    return {"lifts": out, "min_history": int(min_history),
            "note": ("Chronological next-observation forecasts. No random split; "
                     "no prescription effect.")}


def format_report(report: dict) -> str:
    lines = ["fatigue diagnostics — chronological next-observation forecasts"]
    for lift, data in report["lifts"].items():
        lines.append(f"\n{lift}")
        if data.get("status"):
            lines.append(f"  {data['status']}")
            continue
        lines.append(f"  observations={data['observations']} span={data['span'][0]}..{data['span'][1]} "
                     f"duplicate_dates={data['duplicates']}")
        lines.append(f"  noise: median |Δe1RM|={data['noise']['median_abs_consecutive_change']} "
                     f"q80={data['noise']['q80_abs_consecutive_change']}")
        lines.append(f"  {'model':<16}{'n':>4}{'MAE':>8}{'RMSE':>8}{'bias':>8}{'q80':>8}{'q90':>8}")
        for name, value in data["metrics"].items():
            if not value.get("n"):
                continue
            lines.append(f"  {name:<16}{value['n']:>4}{value['mae']:>8.3f}"
                         f"{value['rmse']:>8.3f}{value['bias']:>8.3f}"
                         f"{value['q80']:>8.3f}{value['q90']:>8.3f}")
        lines.append(f"  best baseline: {data['best_baseline']}")
    lines.append("\n" + report["note"])
    return "\n".join(lines)
