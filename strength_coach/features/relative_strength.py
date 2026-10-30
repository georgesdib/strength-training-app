"""Configured, date-stamped relative-strength ratios.

A ratio is descriptive arithmetic between two raw session-best e1RM estimates. It is not a
target, a weakness diagnosis, a population norm, or a confidence interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from strength_coach.features import strength_trend
from strength_coach.utils import paths

RELATIONSHIP_TYPES = {
    "variant_to_main", "accessory_to_main", "equipment_variant", "range_variant",
}


@dataclass(frozen=True)
class Relationship:
    id: str
    label: str
    numerator: str
    denominator: str
    relationship_type: str
    max_gap_days: int
    max_age_days: int
    min_observations: int
    notes: str


@dataclass(frozen=True)
class Ratio:
    relationship_id: str
    ratio_pct: float
    numerator_kg: float
    numerator_date: str
    denominator_kg: float
    denominator_date: str
    gap_days: int
    numerator_observations: int
    denominator_observations: int
    status: str
    label: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "label": self.label,
            "ratio_pct": round(self.ratio_pct, 1),
            "numerator_kg": round(self.numerator_kg, 1),
            "numerator_date": self.numerator_date,
            "denominator_kg": round(self.denominator_kg, 1),
            "denominator_date": self.denominator_date,
            "gap_days": self.gap_days,
            "numerator_observations": self.numerator_observations,
            "denominator_observations": self.denominator_observations,
            "status": self.status,
        }


def load_relationships(path: str | Path | None = None) -> list[Relationship]:
    source = Path(path or paths.config_dir("strength-relationships.v1.yaml"))
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) if source.is_file() else {}
    out = []
    for entry in (raw or {}).get("relationships") or []:
        out.append(Relationship(
            id=str(entry["id"]),
            label=str(entry["label"]),
            numerator=str(entry["numerator"]),
            denominator=str(entry["denominator"]),
            relationship_type=str(entry["relationship_type"]),
            max_gap_days=int(entry["max_gap_days"]),
            max_age_days=int(entry["max_age_days"]),
            min_observations=int(entry["min_observations"]),
            notes=str(entry["notes"]),
        ))
    return out


def validate_relationships(taxonomy: Any, relationships: list[Relationship]) -> list[str]:
    entities = getattr(taxonomy, "entities", taxonomy)
    issues = []
    seen = set()
    for relationship in relationships:
        if relationship.numerator not in entities:
            issues.append(f"{relationship.id}: unknown numerator {relationship.numerator}")
        if relationship.denominator not in entities:
            issues.append(f"{relationship.id}: unknown denominator {relationship.denominator}")
        if relationship.numerator == relationship.denominator:
            issues.append(f"{relationship.id}: numerator equals denominator")
        pair = (relationship.numerator, relationship.denominator)
        if pair in seen:
            issues.append(f"{relationship.id}: duplicate relationship pair")
        seen.add(pair)
        if relationship.relationship_type not in RELATIONSHIP_TYPES:
            issues.append(f"{relationship.id}: unknown relationship type")
        if relationship.max_gap_days <= 0:
            issues.append(f"{relationship.id}: max_gap_days must be positive")
        if relationship.max_age_days < relationship.max_gap_days:
            issues.append(f"{relationship.id}: max_age_days must be >= max_gap_days")
        if relationship.min_observations < 2:
            issues.append(f"{relationship.id}: min_observations must be at least 2")
        if not relationship.notes.strip():
            issues.append(f"{relationship.id}: notes are required")
    return issues


def _within_age(points, on_date: str, max_age_days: int):
    return [
        point for point in points
        if point.date <= on_date
        and (pd_timestamp(on_date) - pd_timestamp(point.date)).days <= max_age_days
    ]


def _latest_within(points, on_date: str, max_age_days: int):
    recent = _within_age(points, on_date, max_age_days)
    return recent[-1] if recent else None, len(recent)


def pd_timestamp(value: str):
    import pandas as pd

    return pd.Timestamp(value)


def current_ratio(conn, relationship: Relationship, on_date: str) -> Ratio | dict[str, Any]:
    numerator_points = strength_trend.observations(
        conn, relationship.numerator, "1900-01-01", on_date
    )
    denominator_points = strength_trend.observations(
        conn, relationship.denominator, "1900-01-01", on_date
    )
    numerator, numerator_count = _latest_within(
        numerator_points, on_date, relationship.max_age_days
    )
    denominator, denominator_count = _latest_within(
        denominator_points, on_date, relationship.max_age_days
    )
    base = {
        "relationship_id": relationship.id,
        "label": relationship.label,
        "numerator_observations": numerator_count,
        "denominator_observations": denominator_count,
    }
    if numerator is None or denominator is None:
        return {**base, "status": "unavailable", "reason": "one or both sides have no recent observation"}
    gap = abs((pd_timestamp(numerator.date) - pd_timestamp(denominator.date)).days)
    if numerator_count < relationship.min_observations or denominator_count < relationship.min_observations:
        return {**base, "status": "insufficient_history", "reason": "fewer than the configured observations"}
    if gap > relationship.max_gap_days:
        return {**base, "status": "stale_or_gap", "reason": "observation dates are too far apart"}
    ratio = 100.0 * numerator.estimate.kg / denominator.estimate.kg
    return Ratio(
        relationship_id=relationship.id,
        ratio_pct=ratio,
        numerator_kg=numerator.estimate.kg,
        numerator_date=numerator.date,
        denominator_kg=denominator.estimate.kg,
        denominator_date=denominator.date,
        gap_days=gap,
        numerator_observations=numerator_count,
        denominator_observations=denominator_count,
        status="available",
        label=relationship.label,
    )


def ratio_trend(conn, relationship: Relationship, from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Paired historical ratios with the same eligibility rules as the current ratio."""
    lookback_days = max(relationship.max_age_days, relationship.max_gap_days)
    history_from = (
        pd_timestamp(from_date) - pd.Timedelta(days=lookback_days)
    ).date().isoformat()
    numerator_points = strength_trend.observations(
        conn, relationship.numerator, history_from, to_date
    )
    denominator_points = strength_trend.observations(
        conn, relationship.denominator, history_from, to_date
    )
    out: list[dict[str, Any]] = []
    for point in numerator_points:
        if point.date < from_date:
            continue
        numerator_history = _within_age(
            numerator_points, point.date, relationship.max_age_days
        )
        denominator_history = _within_age(
            denominator_points, point.date, relationship.max_age_days
        )
        latest_denominator, _ = _latest_within(
            denominator_points, point.date, relationship.max_age_days
        )
        base = {
            "date": point.date,
            "numerator_date": point.date,
            "numerator_kg": round(point.estimate.kg, 1),
            "numerator_observations": len(numerator_history),
            "denominator_date": None if latest_denominator is None else latest_denominator.date,
            "denominator_kg": None if latest_denominator is None else round(latest_denominator.estimate.kg, 1),
            "denominator_observations": len(denominator_history),
            "gap_days": None if latest_denominator is None else abs(
                (pd_timestamp(point.date) - pd_timestamp(latest_denominator.date)).days
            ),
        }
        if latest_denominator is None:
            out.append({**base, "ratio_pct": None, "status": "unavailable",
                        "reason": "denominator has no observation on or before this date"})
            continue
        if (
            len(numerator_history) < relationship.min_observations
            or len(denominator_history) < relationship.min_observations
        ):
            out.append({**base, "ratio_pct": None, "status": "insufficient_history",
                        "reason": "fewer than the configured observations"})
            continue
        if abs((pd_timestamp(point.date) - pd_timestamp(latest_denominator.date)).days) > relationship.max_gap_days:
            out.append({**base, "ratio_pct": None, "status": "stale_or_gap",
                        "reason": "observation dates are too far apart"})
            continue
        out.append({
            **base,
            "ratio_pct": round(100.0 * point.estimate.kg / latest_denominator.estimate.kg, 1),
            "status": "available",
            "reason": "",
        })
    return out
