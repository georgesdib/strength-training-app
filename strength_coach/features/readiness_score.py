"""Global and per-category readiness scores, with manual overrides.

This is the shadow-first implementation of docs/READINESS-SCORE.md:

* subjective fields drive the score (sleep, energy, mood, stress, soreness);
* HRV and RHR enter only with a 28-day baseline and half the weight of a subjective field;
* an optional device-computed wearable score is a 10% blend, never a replacement;
* legacy squat/bench/deadlift readiness are labels, never inputs;
* grip is capacity, never a daily score input;
* a score needs at least three core fields and sleep or energy;
* category overrides win over global overrides, which win over the computed score;
* an explicit override is still used when no numeric score can be formed, while the status
  stays insufficient/unknown;
* the injury signal is a ceiling, not an average.

The load factor is deliberately small and explicit. Nothing here writes a prescription.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, replace
from typing import Any, Mapping

from strength_coach.features import injury_signal
from strength_coach.features import readiness as readiness_config
from strength_coach.store import queries
from strength_coach.utils import exercises
from strength_coach.utils import readiness as readiness_utils

CORE_FIELDS = readiness_utils.CORE_SCORE_FIELDS
MIN_CORE_FIELDS = 3
FACTOR_BANDS = ((0.80, 1.00, 0), (0.60, 0.95, 1), (0.40, 0.90, 1), (0.00, 0.85, 2))

# Movement/muscle categories. The category is the training unit; the region is evidence.
# The vocabulary lives in utils because the store validates override scopes with it and may
# not import features (layering); re-exported here so the score keeps one public name.
CATEGORY_PATTERNS: Mapping[str, tuple[str, ...]] = readiness_utils.CATEGORY_PATTERNS
PATTERN_TO_CATEGORY = readiness_utils.PATTERN_TO_CATEGORY


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
    context_flags: tuple[str, ...] = ()
    device_suppressed: bool = False

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
            "context_flags": list(self.context_flags),
            "device_suppressed": self.device_suppressed,
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


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _device_components(conn, data: Mapping[str, Any], on_date: str,
                       config: readiness_config.ReadinessConfig,
                       context_flags: tuple[str, ...] = ()):
    """Baseline-relative HRV/RHR components, with an explicit missing-baseline note."""
    if any(flag in config.device_suppression_flags for flag in context_flags):
        return [], ["HRV/RHR suppressed by readiness context flag"]
    history = queries.readiness_history(conn, on_date, config.baseline_days)
    components: list[Component] = []
    notes: list[str] = []
    for field, direction, label in (
        ("hrv_ms", "higher", "HRV"),
        ("rhr_bpm", "lower", "RHR"),
    ):
        try:
            value = float(data.get(field))
        except (TypeError, ValueError):
            continue
        values = []
        for row in history:
            try:
                number = float(row.get(field))
            except (TypeError, ValueError):
                continue
            if number > 0:
                values.append(number)
        if len(values) < config.baseline_min_readings:
            notes.append(f"{label} present, baseline {len(values)}/{config.baseline_min_readings} readings")
            continue
        baseline = statistics.median(values)
        ratio = value / baseline
        # 0.5 is baseline; a 50% deviation maps to 0 or 1. The slope is a heuristic, not a
        # validated clinical cutoff; its low weight is what keeps that honest.
        slope = config.hrv_slope if field == "hrv_ms" else config.rhr_slope
        delta = ratio - 1.0 if direction == "higher" else 1.0 - ratio
        normalised = 0.5 + delta / (2.0 * slope)
        weight = config.hrv_weight if field == "hrv_ms" else config.rhr_weight
        components.append(Component(field, value, _clamp(normalised), weight))
    return components, notes


def _wearable(data: Mapping[str, Any], weight: float):
    value = data.get("wearable_score")
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 <= number <= 100:
        return None
    return Component("wearable_score", number, number / 100.0, weight)


def _basis(data: Mapping[str, Any], components: tuple[Component, ...],
           notes: list[str], config: readiness_config.ReadinessConfig) -> str:
    parts = ["weighted subjective core (1.0 each)"]
    if config.setting_source == "athlete":
        parts.append("athlete score setting")
    if any(c.field in {"hrv_ms", "rhr_bpm"} for c in components):
        parts.append("HRV/RHR baseline-relative (0.5 each)")
    parts.extend(notes)
    if any(c.field == "wearable_score" for c in components):
        parts.append(f"optional wearable blended at {config.wearable_weight:.0%}")
    return "; ".join(parts)


def effective_settings(conn, on_date: str,
                       config: readiness_config.ReadinessConfig | None = None
                       ) -> readiness_config.ReadinessConfig:
    """Config, overlaid by the latest athlete setting effective on or before the date."""
    base = config or readiness_config.ReadinessConfig.load()
    row = queries.readiness_setting(conn, on_date)
    if row is None:
        return base
    return replace(
        base,
        baseline_days=int(row["baseline_days"]),
        baseline_min_readings=int(row["baseline_min_readings"]),
        hrv_slope=float(row["hrv_slope"]),
        rhr_slope=float(row["rhr_slope"]),
        hrv_weight=float(row["hrv_weight"]),
        rhr_weight=float(row["rhr_weight"]),
        wearable_weight=float(row["wearable_weight"]),
        setting_source="athlete",
    )


def _partial_basis(reason: str, overrides: Mapping[str, dict]) -> str:
    """Say that an override is the only readiness statement when no score can be formed."""
    if not overrides:
        return reason
    return f"{reason}; manual readiness override (no numeric score)"


def _override_categories(
    overrides: Mapping[str, dict],
) -> tuple[dict[str, float], dict[str, tuple[float, int]]]:
    """Category values for a day that cannot form a numeric score.

    Only an explicit override can produce a value here, so the assessment status stays
    `insufficient` or `unknown`: the override is a dated athlete statement, not a computed
    score. Category wins over global, exactly as it does when a score exists.
    """
    scores: dict[str, float] = {}
    factors: dict[str, tuple[float, int]] = {}
    global_override = overrides.get("global")
    for category in CATEGORY_PATTERNS:
        row = overrides.get(f"category:{category}") or global_override
        if row is None:
            continue
        value = float(row["value"])
        scores[category] = value
        factors[category] = factor_for(value)
    return scores, factors


def compute(conn, on_date: str, config: readiness_config.ReadinessConfig | None = None) -> ReadinessAssessment:
    config = effective_settings(conn, on_date, config)
    data = queries.readiness_day(conn, on_date)
    context_flags = tuple(queries.readiness_context(conn, on_date))
    components = _core_values(data)
    overrides = queries.readiness_overrides(conn, on_date)
    present = {c.field for c in components}
    # A day without a numeric score still honours an explicit override (READINESS-SCORE §2.2a):
    # the athlete's dated statement is not a fabrication, and the status says no score formed.
    override_scores, override_factors = _override_categories(overrides)
    if data is None:
        return ReadinessAssessment(
            on_date, "unknown", None, (), _partial_basis("no readiness entry", overrides),
            overrides, override_scores, override_factors,
            context_flags=context_flags,
        )
    if len(components) < MIN_CORE_FIELDS or not ({"sleep", "energy"} & present):
        return ReadinessAssessment(
            on_date, "insufficient", None, tuple(components),
            _partial_basis(
                f"{len(components)} core field(s); need {MIN_CORE_FIELDS} and sleep or energy",
                overrides,
            ),
            overrides, override_scores, override_factors, context_flags=context_flags,
        )

    device_components, device_notes = _device_components(
        conn, data, on_date, config, context_flags
    )
    suppressed = any(flag in config.device_suppression_flags for flag in context_flags)
    components.extend(device_components)
    wearable = _wearable(data, config.wearable_weight)
    if wearable is not None:
        components.append(wearable)

    total_weight = sum(c.weight for c in components if c.field not in {"wearable_score"})
    score = sum(c.normalised * c.weight for c in components
                if c.field not in {"wearable_score"}) / total_weight
    if wearable is not None:
        score = score * (1.0 - config.wearable_weight) + wearable.normalised * config.wearable_weight
    score = _clamp(score)

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
        basis=_basis(data, components, device_notes, config),
        overrides=overrides,
        category_scores=categories,
        category_factors=factors,
        context_flags=context_flags,
        device_suppressed=suppressed,
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
    if base is None:
        # No computed score today: only an explicit global override can supply a base, so an
        # unclassified exercise is not left without the athlete's own statement.
        global_override = assessment.overrides.get("global")
        if global_override is not None:
            base = float(global_override["value"])
    ceiling = injury_ceiling(conn, assessment.on_date, exercise_id, entity,
                             signal=signal, config=config)
    score = min(base if base is not None else 1.0, ceiling)
    factor, rir = factor_for(score)
    return score, factor, rir, ceiling
