"""Global and per-category readiness scores, with manual overrides.

This is the shadow-first implementation of docs/READINESS-SCORE.md:

* subjective fields only for the score (sleep, energy, mood, stress, soreness);
* legacy squat/bench/deadlift readiness are labels, never inputs;
* grip is capacity, never a daily score input;
* a score needs at least three core fields and sleep or energy;
* category overrides win over global overrides, which win over the computed score;
* the injury signal is a ceiling, not an average.

The load factor is deliberately small and explicit. Nothing here writes a prescription.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Mapping

from strength_coach.features import injury_signal
from strength_coach.store import queries
from strength_coach.utils import exercises
from strength_coach.utils import readiness as readiness_utils

CORE_FIELDS = readiness_utils.CORE_SCORE_FIELDS
MIN_CORE_FIELDS = 3
FACTOR_BANDS = ((0.80, 1.00, 0), (0.60, 0.95, 1), (0.40, 0.90, 1), (0.00, 0.85, 2))

# Movement/muscle categories. The category is the training unit; the region is evidence.
CATEGORY_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "hinge": ("hinge", "hinge_unilateral", "hinge_ballistic"),
    "squat": ("squat", "squat_unilateral"),
    "horizontal_push": ("horizontal_push", "horizontal_push_bw"),
    "vertical_push": ("vertical_push",),
    "horizontal_pull": ("horizontal_pull",),
    "vertical_pull": ("vertical_pull",),
    "elbow_flexion": ("elbow_flexion",),
    "knee_extension": ("knee_extension",),
    "knee_flexion": ("knee_flexion", "hamstring_eccentric"),
    "spinal_extension": ("erector_extension",),
    "core_carry": ("core_flexion", "core_anti_extension", "core_isometric",
                   "core_stability", "carry"),
}
PATTERN_TO_CATEGORY = {
    pattern: category for category, patterns in CATEGORY_PATTERNS.items() for pattern in patterns
}


@dataclass(frozen=True)
class Component:
    field: str
    value: float
    normalised: float
    weight: float


@dataclass(frozen=True)
class ReadinessAssessment:
    on_date: str
    status: str                 # ready | insufficient | unknown
    score: float | None
    components: tuple[Component, ...]
    basis: str
    overrides: Mapping[str, dict]
    category_scores: Mapping[str, float]
    category_factors: Mapping[str, tuple[float, int]]

    def as_dict(self) -> dict:
        return {
            "on_date": self.on_date,
            "status": self.status,
            "score": self.score,
            "basis": self.basis,
            "components": [
                {"field": c.field, "value": c.value, "normalised": c.normalised,
                 "weight": c.weight}
                for c in self.components
            ],
            "overrides": {k: dict(v) for k, v in self.overrides.items()},
            "category_scores": dict(self.category_scores),
            "category_factors": {k: {"factor": v[0], "rir_bump": v[1]}
                                 for k, v in self.category_factors.items()},
        }


def factor_for(score: float | None) -> tuple[float, int]:
    if score is None:
        return 1.0, 0
    for low, factor, rir in FACTOR_BANDS:
        if score >= low:
            return factor, rir
    return 0.85, 2


def category_for(exercise_id: str, entity: Mapping[str, Any] | None = None) -> str | None:
    props = entity or {}
    pattern = props.get("pattern")
    if pattern:
        pattern = str(pattern)
        if pattern.startswith("pattern:"):
            pattern = pattern.split(":", 1)[1]
        return PATTERN_TO_CATEGORY.get(pattern)
    return None


def _core_values(readiness: Mapping[str, Any] | None) -> list[Component]:
    if not readiness:
        return []
    out = []
    for field in CORE_FIELDS:
        value = readiness.get(field)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 5:
            out.append(Component(field, number, number / 5.0, 1.0))
    return out


def compute(conn, on_date: str) -> ReadinessAssessment:
    data = queries.readiness_day(conn, on_date)
    components = _core_values(data)
    overrides = queries.readiness_overrides(conn, on_date)
    present = {c.field for c in components}
    if data is None:
        return ReadinessAssessment(
            on_date, "unknown", None, (), "no readiness entry", overrides, {}, {}
        )
    if len(components) < MIN_CORE_FIELDS or not ({"sleep", "energy"} & present):
        return ReadinessAssessment(
            on_date, "insufficient", None, tuple(components),
            f"{len(components)} core field(s); need {MIN_CORE_FIELDS} and sleep or energy",
            overrides, {}, {},
        )

    score = sum(c.normalised for c in components) / len(components)
    global_override = overrides.get("global")
    if global_override is not None:
        score = float(global_override["value"])

    categories: dict[str, float] = {}
    factors: dict[str, tuple[float, int]] = {}
    for category in CATEGORY_PATTERNS:
        value = score
        override = overrides.get(f"category:{category}")
        if override is not None:
            value = float(override["value"])
        categories[category] = value
        factors[category] = factor_for(value)

    return ReadinessAssessment(
        on_date=on_date,
        status="ready",
        score=score,
        components=tuple(components),
        basis="equal weights over core subjective fields; HRV/RHR context not yet scored",
        overrides=overrides,
        category_scores=categories,
        category_factors=factors,
    )


def _ceiling(status: str, weight: int) -> float:
    if status == injury_signal.STATUS_ACTIVE:
        return 0.50 if weight >= injury_signal.WEIGHT_DIRECT else 0.60
    if status == injury_signal.STATUS_MONITORING:
        return 0.80 if weight >= injury_signal.WEIGHT_DIRECT else 0.85
    return 1.0


def injury_ceiling(conn, on_date: str, exercise_id: str,
                   entity: Mapping[str, Any] | None = None,
                   *, signal: injury_signal.InjurySignal | None = None,
                   config: injury_signal.InjuryConfig | None = None) -> float:
    """Lowest ceiling among regions that load this exercise; 1.0 when none apply."""
    cfg = config or injury_signal.InjuryConfig.load()
    sig = signal or injury_signal.compute(conn, on_date)
    props = entity or {}
    ceiling = 1.0
    for rule in cfg.regions.values():
        weight = rule.weight(exercise_id, props)
        if not weight:
            continue
        region = sig.region(rule.region)
        if region is None:
            continue
        ceiling = min(ceiling, _ceiling(region.status, weight))
    return ceiling


def effective(assessment: ReadinessAssessment, conn, exercise_id: str,
              entity: Mapping[str, Any] | None = None,
              *, signal: injury_signal.InjurySignal | None = None,
              config: injury_signal.InjuryConfig | None = None):
    """Return (score, factor, rir_bump, ceiling) for one exercise."""
    category = category_for(exercise_id, entity)
    base = assessment.score if category is None else assessment.category_scores.get(
        category, assessment.score
    )
    ceiling = injury_ceiling(conn, assessment.on_date, exercise_id, entity,
                             signal=signal, config=config)
    score = min(base if base is not None else 1.0, ceiling)
    factor, rir = factor_for(score)
    return score, factor, rir, ceiling
