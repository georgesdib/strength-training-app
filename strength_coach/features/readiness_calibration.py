"""Calibration report for the readiness score, against the old black-box labels.

This is a report, not an auto-tuner. It fits a small ridge model on a date split:
readiness fields first, then main-lift load features. The old squat/bench/deadlift values are
targets only. The output says whether the new score mimics the old app; it cannot validate it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from strength_coach.features import readiness_score
from strength_coach.store import queries
from strength_coach.utils import exercises

LABELS = {
    "squat_readiness": "squat",
    "bench_readiness": "horizontal_push",
    "deadlift_readiness": "hinge",
}
READINESS_FIELDS = ("sleep", "energy", "mood", "stress", "soreness")
LOAD_FEATURES = ("sets_7d", "tonnage_7d", "sets_28d", "tonnage_28d",
                 "days_since", "last_load")
FEATURES = tuple(f"readiness_{f}" for f in READINESS_FIELDS) + LOAD_FEATURES


@dataclass(frozen=True)
class CalibrationRow:
    on_date: str
    label: float
    features: tuple[float, ...]


@dataclass(frozen=True)
class LabelReport:
    label: str
    category: str
    n_train: int
    n_test: int
    mae_readiness: float
    mae_with_load: float
    baseline_mae: float
    rank_correlation: float


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(str(value)[:10])


def _load_sets(conn) -> list[dict]:
    taxonomy = exercises.taxonomy()
    rows = conn.execute(
        """
        SELECT occurred_on, exercise_id, load_kg, reps
          FROM clean_set
         WHERE is_working_set = 1
         ORDER BY occurred_on
        """
    ).fetchall()
    out = []
    for row in rows:
        entity = taxonomy.entities.get(str(row["exercise_id"]), {})
        category = readiness_score.category_for(str(row["exercise_id"]), entity)
        if category is None:
            continue
        reps = int(row["reps"] or 0)
        load = float(row["load_kg"] or 0)
        out.append({
            "date": str(row["occurred_on"])[:10],
            "category": category,
            "sets": 1,
            "tonnage": load * reps if load > 0 else 0.0,
            "load": load,
        })
    return out


def _features(day: str, category: str, readiness: dict, sets: Iterable[dict]) -> list[float]:
    d = _date(day)
    window7 = (d - dt.timedelta(days=7)).isoformat()
    window28 = (d - dt.timedelta(days=28)).isoformat()
    relevant = [s for s in sets if s["category"] == category and s["date"] < day]
    sets7 = [s for s in relevant if s["date"] >= window7]
    sets28 = [s for s in relevant if s["date"] >= window28]
    last = relevant[-1] if relevant else None
    days_since = (_date(day) - _date(last["date"])).days if last else 28.0
    values = []
    for field in READINESS_FIELDS:
        raw = readiness.get(field)
        values.append(float(raw) / 5.0 if raw is not None else 0.0)
    values.extend([
        float(len(sets7)),
        float(sum(s["tonnage"] for s in sets7)),
        float(len(sets28)),
        float(sum(s["tonnage"] for s in sets28)),
        float(min(days_since, 28)),
        float(last["load"] if last else 0.0),
    ])
    return values


def _ridge(x: np.ndarray, y: np.ndarray, penalty: float = 1.0) -> np.ndarray:
    x = np.column_stack([np.ones(len(x)), x])
    identity = np.eye(x.shape[1])
    identity[0, 0] = 0.0
    return np.linalg.solve(x.T @ x + penalty * identity, x.T @ y)


def _mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values)
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(len(values), dtype=float)
    return ranks


def report(conn, *, minimum: int = 20) -> str:
    rows = conn.execute(
        "SELECT * FROM readiness_day WHERE squat_readiness IS NOT NULL "
        "OR bench_readiness IS NOT NULL OR deadlift_readiness IS NOT NULL "
        "ORDER BY on_date"
    ).fetchall()
    if len(rows) < minimum:
        return (f"readiness calibration: {len(rows)} labelled days; "
                f"need at least {minimum} for a date-split report")
    sets = _load_sets(conn)
    lines = [
        f"readiness calibration — {len(rows)} labelled days, date split 70/30",
        "targets are the old black-box values; this measures mimicry, not validity",
        "",
        f"{'label':<20}{'n':>5}{'MAE ready':>11}{'MAE + load':>12}"
        f"{'baseline':>10}{'rank r':>8}",
    ]
    reports: list[LabelReport] = []
    for label, category in LABELS.items():
        data = []
        for row in rows:
            value = row[label]
            if value is None:
                continue
            data.append(CalibrationRow(
                on_date=str(row["on_date"]),
                label=float(value) / 5.0,
                features=tuple(_features(str(row["on_date"]), category, dict(row), sets)),
            ))
        if len(data) < minimum:
            continue
        split = max(1, int(len(data) * 0.7))
        train, test = data[:split], data[split:]
        if not test:
            continue
        x_train = np.array([r.features for r in train], dtype=float)
        y_train = np.array([r.label for r in train], dtype=float)
        x_test = np.array([r.features for r in test], dtype=float)
        y_test = np.array([r.label for r in test], dtype=float)

        readiness_cols = list(range(len(READINESS_FIELDS)))
        mean = x_train.mean(axis=0)
        std = x_train.std(axis=0)
        std[std == 0] = 1.0
        z_train = (x_train - mean) / std
        z_test = (x_test - mean) / std
        ready_train = z_train[:, readiness_cols]
        ready_test = z_test[:, readiness_cols]
        beta_ready = _ridge(ready_train, y_train)
        pred_ready = np.column_stack([np.ones(len(ready_test)), ready_test]) @ beta_ready
        beta_all = _ridge(z_train, y_train)
        pred_all = np.column_stack([np.ones(len(z_test)), z_test]) @ beta_all
        baseline = float(np.mean(y_train))

        rank_r = 0.0
        if len(y_test) > 2 and np.std(pred_all) > 0:
            rank_r = float(np.corrcoef(_rank(y_test), _rank(pred_all))[0, 1])
        reports.append(LabelReport(
            label=label, category=category, n_train=len(train), n_test=len(test),
            mae_readiness=_mae(y_test, pred_ready),
            mae_with_load=_mae(y_test, pred_all),
            baseline_mae=_mae(y_test, np.full(len(y_test), baseline)),
            rank_correlation=rank_r,
        ))
        lines.append(
            f"{label:<20}{len(train) + len(test):>5}{_mae(y_test, pred_ready):>11.3f}"
            f"{_mae(y_test, pred_all):>12.3f}{_mae(y_test, np.full(len(y_test), baseline)):>10.3f}"
            f"{rank_r:>8.2f}"
        )
    if not reports:
        lines.append("no label had enough rows for the date split")
    lines += ["", "the fitted weights are not applied automatically; this is a report only"]
    return "\n".join(lines)
