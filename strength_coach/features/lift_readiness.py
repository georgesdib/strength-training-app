"""Per-lift readiness: a bounded, advisory extension of the global readiness score.

There is no validated per-lift readiness questionnaire. This score exists to make the
available signals explicit, not to claim validity:

* the global readiness score (subjective wellness) is the base and the largest weight;
* a recent e1RM trend (performance);
* the last session's mean RIR (effort);
* the last session's velocity versus the lift's VBT calibration, when one exists.

The engine may only use a *lower* per-lift score to reduce a load; it never raises one. That
asymmetry keeps an unvalidated composite from making training harder. Weights and bands are
assumptions (`ASSUMPTION-25`, `DEC-LIFT-READY-01`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from strength_coach.features import vbt_calibration
from strength_coach.utils import exercises

# Deliberately simple and documented rather than fitted. Neutral components (0.5) leave the
# subjective base unchanged; only deviations move the score.
WEIGHTS = {"e1rm": 0.20, "rir": 0.15, "vbt": 0.15}
RIR_REFERENCE = 2.0          # RIR 2 is neutral (the target is 2-3); higher = easier
E1RM_TOLERANCE = 0.10        # +/-10% maps to the full 0..1 range
VELOCITY_TOLERANCE = 0.10    # +/-10% vs the calibration median


@dataclass(frozen=True)
class LiftReadiness:
    exercise_id: str
    score: float
    status: str                 # ready | monitor | low
    components: Mapping[str, float]
    n_sets: int
    last_date: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "score": round(self.score, 3),
            "status": self.status,
            "components": {key: round(value, 3) for key, value in self.components.items()},
            "n_sets": self.n_sets,
            "last_date": self.last_date,
        }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _ratio_score(ratio: float, tolerance: float) -> float:
    return _clamp(0.5 + (ratio - 1.0) / (2.0 * tolerance))


def _status(score: float) -> str:
    if score >= 0.75:
        return "ready"
    if score >= 0.50:
        return "monitor"
    return "low"


def _canonical(exercise_id: str, entities: Mapping[str, Mapping[str, Any]]) -> str:
    return str(entities.get(exercise_id, {}).get("history_equivalent_of") or exercise_id)


def _vbt_component(
    last: pd.DataFrame,
    exercise_id: str,
    calibration: vbt_calibration.CalibrationResult | None,
) -> float | None:
    if calibration is None or last.empty:
        return None
    rows = last[
        last["velocity_present"].astype(bool)
        & last["velocity_mps"].notna()
        & last["reps"].notna()
    ]
    ratios: list[float] = []
    for row in rows.itertuples():
        target = calibration.lookup(exercise_id, int(row.reps))
        if target is None or not target.velocity_median:
            continue
        ratios.append(float(row.velocity_mps) / float(target.velocity_median))
    if not ratios:
        return None
    return _ratio_score(sum(ratios) / len(ratios), VELOCITY_TOLERANCE)


def compute(
    sets: pd.DataFrame,
    base_scores: Mapping[str, float],
    on_date: str,
    *,
    calibration: vbt_calibration.CalibrationResult | None = None,
) -> dict[str, LiftReadiness]:
    """One score per exercise id in `base_scores`; missing history falls back to the base."""
    day = pd.Timestamp(on_date)
    entities = exercises.taxonomy().entities
    out: dict[str, LiftReadiness] = {}

    if sets is None or sets.empty:
        for exercise_id, base in base_scores.items():
            out[exercise_id] = LiftReadiness(
                exercise_id, float(base), _status(float(base)), {"subjective": float(base)}, 0, None
            )
        return out

    frame = sets[sets["date"] <= day].copy()
    frame["canonical"] = [_canonical(str(value), entities) for value in frame["exercise_id"]]

    for exercise_id, base in base_scores.items():
        hist = frame[frame["canonical"] == exercise_id]
        hist = hist[hist["is_working_set"].astype(bool)]
        if hist.empty:
            out[exercise_id] = LiftReadiness(
                exercise_id, float(base), _status(float(base)), {"subjective": float(base)}, 0, None
            )
            continue

        last_date = hist["date"].max()
        last = hist[hist["date"] == last_date]
        components: dict[str, float] = {"subjective": float(base)}

        if "e1rm_kg" in hist:
            latest = last["e1rm_kg"].max()
            prior = hist[
                (hist["date"] < last_date)
                & (hist["date"] >= last_date - pd.Timedelta(days=28))
                & hist["e1rm_kg"].notna()
            ]
            if pd.notna(latest) and not prior.empty:
                baseline = float(prior["e1rm_kg"].median())
                if baseline > 0:
                    components["e1rm"] = _ratio_score(
                        float(latest) / baseline, E1RM_TOLERANCE
                    )

        rirs = last["rir"].dropna()
        if not rirs.empty:
            components["rir"] = _clamp(0.5 + (float(rirs.mean()) - RIR_REFERENCE) / 5.0)

        vbt = _vbt_component(last, exercise_id, calibration)
        if vbt is not None:
            components["vbt"] = vbt

        # Start from the subjective base and apply only deviations from a neutral 0.5. This
        # keeps a normal RIR-2 session from looking like fatigue.
        score = float(base)
        for name, value in components.items():
            if name in WEIGHTS:
                score += WEIGHTS[name] * (value - 0.5)
        out[exercise_id] = LiftReadiness(
            exercise_id=exercise_id,
            score=_clamp(score),
            status=_status(_clamp(score)),
            components=components,
            n_sets=int(len(last)),
            last_date=last_date.date().isoformat(),
        )
    return out


def as_dict(report: Mapping[str, LiftReadiness]) -> dict[str, dict[str, Any]]:
    return {key: value.as_dict() for key, value in report.items()}
