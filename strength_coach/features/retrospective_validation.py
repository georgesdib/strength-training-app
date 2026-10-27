"""Retrospective walk-forward checks for continuity and strength fatigue.

This is deliberately not prospective validation. Every prediction for a date is built from
data strictly before that date; the report labels the method and never changes a prescription.

Volume is reported as descriptive only: there is no predictive volume model to validate.
Selection is excluded because the counterfactual is unobserved.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from strength_coach.features import continuity_calibration, derived, fatigue_fitness
from strength_coach.prescribe import config as prescribe_config
from strength_coach.store import queries
from strength_coach.utils import exercises


def _canonical(exercise_id: str, entities) -> str:
    return str(entities.get(exercise_id, {}).get("history_equivalent_of") or exercise_id)


def _prepare(conn):
    raw = queries.clean_sets(conn)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()
    sets = derived.enrich(raw)
    entities = exercises.taxonomy().entities
    sets["canonical"] = [_canonical(str(v), entities) for v in sets["exercise_id"]]
    working = sets[sets["is_working_set"].astype(bool)].copy()
    working = working[working["rir"].isna() | (working["rir"] <= 4)]
    working["load"] = 1.0
    loads = working.groupby(["canonical", "date"], as_index=False)["load"].sum()
    observed = sets[sets["e1rm_kg"].notna()]
    obs = observed.groupby(["canonical", "date"], as_index=False)["e1rm_kg"].max()
    return loads, obs


def _decay(loads: pd.DataFrame, canonical: str, at: pd.Timestamp, half_life: float) -> float:
    frame = loads[(loads["canonical"] == canonical) & (loads["date"] <= at)]
    if frame.empty:
        return 0.0
    ages = (at - frame["date"]).dt.days.to_numpy(dtype=float)
    return float((frame["load"].to_numpy(dtype=float) * (0.5 ** (ages / half_life))).sum())


def _evaluation_dates(obs: pd.DataFrame, max_dates: int) -> list[pd.Timestamp]:
    dates = sorted(pd.Timestamp(v) for v in obs["date"].unique())
    if len(dates) <= max_dates:
        return dates
    # Even spacing avoids evaluating only the most recent, easiest-to-fit sessions.
    picks = np.linspace(0, len(dates) - 1, max_dates).round().astype(int)
    return [dates[i] for i in sorted(set(picks.tolist()))]


def _fatigue_rows(conn, loads, obs, dates, config):
    rows = []
    for at in dates:
        cutoff = (at - pd.Timedelta(days=1)).date().isoformat()
        try:
            models = fatigue_fitness.compute(conn, cutoff, config)
        except Exception:
            continue
        for model in models:
            if model.exercise_id == "overall" or not model.params or not model.scale_kg:
                continue
            hit = obs[(obs["canonical"] == model.exercise_id) & (obs["date"] == at)]
            if hit.empty:
                continue
            prior = obs[(obs["canonical"] == model.exercise_id) & (obs["date"] < at)]
            if prior.empty:
                continue
            actual = float(hit["e1rm_kg"].iloc[0])
            baseline = float(prior["e1rm_kg"].iloc[-1])
            params = model.params
            f = _decay(loads, model.exercise_id, at,
                       float(params["fitness_half_life_days"]))
            t = _decay(loads, model.exercise_id, at,
                       float(params["fatigue_half_life_days"]))
            predicted = float(model.scale_kg) * (
                float(params["intercept"]) + float(params["fitness_k"]) * f
                + float(params["fatigue_k"]) * t
            )
            rows.append((model.exercise_id, at.date().isoformat(),
                         abs(predicted - actual) / actual,
                         abs(baseline - actual) / actual))
    return rows


def _continuity_rows(sets, dates, thresholds):
    if sets.empty or "e1rm_kg" not in sets.columns:
        return []
    sessions = sets[sets["e1rm_kg"].notna()].copy()
    sessions = sessions.sort_values(["exercise_id", "date"])
    returns = []
    for exercise_id, group in sessions.groupby("exercise_id", sort=False):
        prior = None
        for row in group.itertuples(index=False):
            if prior is not None:
                gap = int((pd.Timestamp(row.date) - pd.Timestamp(prior.date)).days)
                if thresholds.continuity_short_days <= gap <= 365:
                    ratio = float(row.e1rm_kg) / float(prior.e1rm_kg)
                    if 0.5 <= ratio <= 1.5:
                        returns.append((pd.Timestamp(row.date), exercise_id, gap, ratio))
            prior = row
    returns = [r for r in returns if r[0] in set(dates)][-12:]
    cfg = replace(continuity_calibration.CalibrationConfig.load(), bootstrap_samples=200)
    rows = []
    for at, _exercise_id, gap, actual_ratio in returns:
        prefix = sessions[sessions["date"] < at]
        if prefix.empty:
            continue
        try:
            cal = continuity_calibration.compute(
                prefix,
                short_days=thresholds.continuity_short_days,
                medium_days=thresholds.continuity_medium_days,
                long_days=thresholds.continuity_long_days,
                medium_multiplier=thresholds.continuity_medium_multiplier,
                long_multiplier=thresholds.continuity_long_multiplier,
                config=cfg,
            )
        except Exception:
            continue
        band = ("long" if gap >= thresholds.continuity_long_days
                else "medium" if gap >= thresholds.continuity_medium_days else "short")
        estimate = cal.bands.get(band)
        if estimate is None or estimate.median is None:
            continue
        rows.append((at.date().isoformat(), band,
                     abs(float(estimate.factor) - actual_ratio),
                     abs(float(estimate.fixed) - actual_ratio)))
    return rows


def report(conn, max_dates: int = 12) -> str:
    loads, obs = _prepare(conn)
    if loads.empty or obs.empty:
        return "RETROSPECTIVE WALK-FORWARD — no usable sets"
    dates = _evaluation_dates(obs, max_dates)
    thresholds = prescribe_config.Thresholds.load()
    fatigue = _fatigue_rows(conn, loads, obs, dates, fatigue_fitness.ModelConfig.load())
    continuity = _continuity_rows(
        derived.enrich(queries.clean_sets(conn)), dates, thresholds
    )
    lines = [
        "RETROSPECTIVE WALK-FORWARD — not prospective",
        f"evaluation dates: {len(dates)}; predictions use only data before each date",
        "No prescription, load or parameter is changed by this report.",
        "",
    ]
    if fatigue:
        mae = float(np.mean([row[2] for row in fatigue]))
        naive = float(np.mean([row[3] for row in fatigue]))
        lines.append(
            f"FATIGUE: {len(fatigue)} lift-session predictions; relative MAE {mae:.3f}; "
            f"persistence baseline {naive:.3f}; "
            f"skill {'+' if naive > mae else ''}{(1 - mae / naive) * 100:.1f}%"
        )
    else:
        lines.append("FATIGUE: no eligible walk-forward predictions")
    if continuity:
        mae = float(np.mean([row[2] for row in continuity]))
        fixed = float(np.mean([row[3] for row in continuity]))
        lines.append(
            f"CONTINUITY: {len(continuity)} returns; ratio MAE {mae:.3f}; "
            f"fixed-rule MAE {fixed:.3f}; "
            f"skill {'+' if fixed > mae else ''}{(1 - mae / fixed) * 100:.1f}%"
        )
    else:
        lines.append("CONTINUITY: no eligible returns")
    lines.append(
        "VOLUME: no predictive volume model; only descriptive/causal limits apply. "
        "Selection: no counterfactual, so not validated here."
    )
    lines.append("Interpretation: small, single-athlete, retrospective; do not adopt a model "
                 "on this alone.")
    return "\n".join(lines)
