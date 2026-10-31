"""Configured, date-stamped relative-strength ratios.

A ratio is descriptive arithmetic between two raw session-best e1RM estimates. It is not a
target, a weakness diagnosis, a population norm, or a confidence interval.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from strength_coach.features import derived, strength_trend
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


LOCAL_RELATIONSHIPS_NAME = "strength-relationships.local.yaml"


def _relationship_from_entry(entry: dict) -> Relationship:
    return Relationship(
        id=str(entry["id"]),
        label=str(entry["label"]),
        numerator=str(entry["numerator"]),
        denominator=str(entry["denominator"]),
        relationship_type=str(entry["relationship_type"]),
        max_gap_days=int(entry["max_gap_days"]),
        max_age_days=int(entry["max_age_days"]),
        min_observations=int(entry["min_observations"]),
        notes=str(entry["notes"]),
    )


def _relationship_dict(relationship: Relationship) -> dict[str, Any]:
    return {
        "id": relationship.id,
        "label": relationship.label,
        "numerator": relationship.numerator,
        "denominator": relationship.denominator,
        "relationship_type": relationship.relationship_type,
        "max_gap_days": relationship.max_gap_days,
        "max_age_days": relationship.max_age_days,
        "min_observations": relationship.min_observations,
        "notes": relationship.notes,
    }


def _canonical_path(path: str | Path | None = None) -> Path:
    return Path(path or paths.config_dir("strength-relationships.v1.yaml"))


def _local_path(path: str | Path | None = None) -> Path:
    return _canonical_path(path).with_name(LOCAL_RELATIONSHIPS_NAME)


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must contain a mapping")
    return raw


def _load_overlay(path: str | Path | None = None) -> dict[str, Any]:
    raw = _load_yaml(_local_path(path))
    relationships = []
    seen = set()
    for entry in raw.get("relationships") or []:
        relationship = _relationship_from_entry(entry)
        if relationship.id in seen:
            raise ValueError(f"duplicate local relationship id: {relationship.id}")
        seen.add(relationship.id)
        relationships.append(relationship)
    deleted = [str(item) for item in (raw.get("deleted") or [])]
    return {
        "schema_version": str(raw.get("schema_version", "1.0.0")),
        "relationships": relationships,
        "deleted": deleted,
    }


def _write_overlay(
    overlay: dict[str, Any], path: str | Path | None = None,
) -> None:
    target = _local_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "relationships": [_relationship_dict(item) for item in overlay["relationships"]],
        "deleted": sorted(set(overlay["deleted"])),
    }
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def load_relationships_with_sources(
    path: str | Path | None = None,
) -> list[tuple[Relationship, str, str]]:
    canonical_path = _canonical_path(path)
    canonical = [
        _relationship_from_entry(entry)
        for entry in (_load_yaml(canonical_path).get("relationships") or [])
    ]
    overlay = _load_overlay(path)
    local_by_id = {item.id: item for item in overlay["relationships"]}
    deleted = set(overlay["deleted"])
    canonical_ids = {item.id for item in canonical}
    out: list[tuple[Relationship, str, str]] = []
    for item in canonical:
        if item.id in deleted:
            continue
        if item.id in local_by_id:
            out.append((
                local_by_id[item.id],
                "local override: config/strength-relationships.local.yaml",
                "local_override",
            ))
        else:
            out.append((
                item,
                "canonical config: config/strength-relationships.v1.yaml",
                "canonical_config",
            ))
    for item in overlay["relationships"]:
        if item.id in canonical_ids or item.id in deleted:
            continue
        out.append((
            item,
            "local override: config/strength-relationships.local.yaml",
            "local_override",
        ))
    return out


def load_relationships(path: str | Path | None = None) -> list[Relationship]:
    return [item for item, _source, _kind in load_relationships_with_sources(path)]


def relationship_config_source(path: str | Path | None = None) -> tuple[str, str]:
    overlay = _load_overlay(path)
    if overlay["relationships"] or overlay["deleted"]:
        return (
            "merged config: config/strength-relationships.v1.yaml + "
            "config/strength-relationships.local.yaml",
            "local_override",
        )
    return (
        "canonical config: config/strength-relationships.v1.yaml",
        "canonical_config",
    )


def relationship_config_revision(path: str | Path | None = None) -> str:
    digest = hashlib.sha256()
    for candidate in (_canonical_path(path), _local_path(path)):
        if candidate.is_file():
            digest.update(candidate.name.encode("utf-8"))
            digest.update(candidate.read_bytes())
    return digest.hexdigest()


def validate_relationships(taxonomy: Any, relationships: list[Relationship]) -> list[str]:
    entities = getattr(taxonomy, "entities", taxonomy)
    issues = []
    seen = set()
    seen_ids = set()
    for relationship in relationships:
        if relationship.id in seen_ids:
            issues.append(f"{relationship.id}: duplicate relationship id")
        seen_ids.add(relationship.id)
        if relationship.numerator not in entities:
            issues.append(f"{relationship.id}: unknown numerator {relationship.numerator}")
        if relationship.denominator not in entities:
            issues.append(f"{relationship.id}: unknown denominator {relationship.denominator}")
        for side in (relationship.numerator, relationship.denominator):
            props = dict(entities.get(str(side), {}))
            if side in entities and not derived.e1rm_applicable(props):
                issues.append(f"{relationship.id}: {side} does not support an e1RM")
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


def current_ratio(
    conn, relationship: Relationship, on_date: str, *, points=None,
) -> Ratio | dict[str, Any]:
    numerator_points = (
        points.get(relationship.numerator)
        if points and relationship.numerator in points
        else strength_trend.observations(
            conn, relationship.numerator, "1900-01-01", on_date
        )
    )
    denominator_points = (
        points.get(relationship.denominator)
        if points and relationship.denominator in points
        else strength_trend.observations(
            conn, relationship.denominator, "1900-01-01", on_date
        )
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


def ratio_trend(
    conn, relationship: Relationship, from_date: str, to_date: str, *, points=None,
) -> list[dict[str, Any]]:
    """Paired historical ratios with the same eligibility rules as the current ratio."""
    lookback_days = max(relationship.max_age_days, relationship.max_gap_days)
    history_from = (
        pd_timestamp(from_date) - pd.Timedelta(days=lookback_days)
    ).date().isoformat()
    numerator_points = (
        points.get(relationship.numerator)
        if points and relationship.numerator in points
        else strength_trend.observations(
            conn, relationship.numerator, history_from, to_date
        )
    )
    denominator_points = (
        points.get(relationship.denominator)
        if points and relationship.denominator in points
        else strength_trend.observations(
            conn, relationship.denominator, history_from, to_date
        )
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


RELATIONSHIP_TYPES_ORDER = (
    "variant_to_main",
    "accessory_to_main",
    "equipment_variant",
    "range_variant",
)


def relationship_types() -> tuple[str, ...]:
    return RELATIONSHIP_TYPES_ORDER


def _validate_merged(relationships: list[Relationship]) -> None:
    from strength_coach.utils import exercises

    issues = validate_relationships(exercises.taxonomy(), relationships)
    if issues:
        raise ValueError("; ".join(issues))


def append_relationship(relationship: Relationship, path: str | Path | None = None) -> list[Relationship]:
    """Append a validated relationship to the local overlay, never canonical YAML."""
    current = load_relationships(path)
    _validate_merged([*current, relationship])
    overlay = _load_overlay(path)
    overlay["relationships"].append(relationship)
    overlay["deleted"] = [item for item in overlay["deleted"] if item != relationship.id]
    _write_overlay(overlay, path)
    return load_relationships(path)


def update_relationship(relationship: Relationship, path: str | Path | None = None) -> list[Relationship]:
    """Replace a relationship in the local overlay; membership is immutable."""
    current = load_relationships(path)
    existing = next((item for item in current if item.id == relationship.id), None)
    if existing is None:
        raise ValueError(f"unknown relationship: {relationship.id}")
    if (existing.numerator, existing.denominator) != (
        relationship.numerator, relationship.denominator
    ):
        raise ValueError("relationship membership cannot be changed; delete and add a new pair")
    updated = [relationship if item.id == relationship.id else item for item in current]
    _validate_merged(updated)
    overlay = _load_overlay(path)
    overlay["relationships"] = [
        item for item in overlay["relationships"] if item.id != relationship.id
    ]
    overlay["relationships"].append(relationship)
    overlay["deleted"] = [item for item in overlay["deleted"] if item != relationship.id]
    _write_overlay(overlay, path)
    return load_relationships(path)


def delete_relationship(relationship_id: str, path: str | Path | None = None) -> list[Relationship]:
    current = load_relationships(path)
    if not any(item.id == relationship_id for item in current):
        raise ValueError(f"unknown relationship: {relationship_id}")
    canonical_ids = {
        entry.id for entry in (
            _relationship_from_entry(item)
            for item in (_load_yaml(_canonical_path(path)).get("relationships") or [])
        )
    }
    overlay = _load_overlay(path)
    overlay["relationships"] = [
        item for item in overlay["relationships"] if item.id != relationship_id
    ]
    if relationship_id in canonical_ids:
        overlay["deleted"] = sorted(set([*overlay["deleted"], relationship_id]))
    else:
        overlay["deleted"] = [item for item in overlay["deleted"] if item != relationship_id]
    _write_overlay(overlay, path)
    return load_relationships(path)


def reset_relationship(relationship_id: str, path: str | Path | None = None) -> list[Relationship]:
    overlay = _load_overlay(path)
    overlay["relationships"] = [
        item for item in overlay["relationships"] if item.id != relationship_id
    ]
    overlay["deleted"] = [item for item in overlay["deleted"] if item != relationship_id]
    _write_overlay(overlay, path)
    return load_relationships(path)
