"""Deterministic role-quality hierarchy for resolver finalists.

This module implements WP6's level-3 comparison. It is deliberately not a composite: every
criterion becomes a small ordinal class, and finalists are compared lexicographically in role
priority order (main, secondary, accessory). Missing data is neutral, never a guess. The
pre-build dwell layer owns repetition and variation; nothing here reads dwell counts or last
used as a quality signal.

The snapshot is response/diagnostic data. It is not a training target and never rewrites a
prescription.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from strength_coach.features import volume as volume_feature
from strength_coach.prescribe import templates
from strength_coach.prescribe.models import Prescription
from strength_coach.store import queries
from strength_coach.utils import exercises, paths, yaml_files

CONFIG_NAME = "resolver-role-quality.v1.yaml"
VERSION = "role-quality-v1"


def config_digest() -> str:
    """Digest of the role-quality class config, so a class change moves the fingerprint."""
    return hashlib.sha256(
        paths.config_dir(CONFIG_NAME).read_bytes()
    ).hexdigest()


@dataclass(frozen=True)
class RoleQualityConfig:
    role_priority: tuple[str, ...]
    criteria: Mapping[str, tuple[str, ...]]
    specificity: Mapping[str, int]
    heavy_band: float
    e1rm_full_days: int
    e1rm_partial_days: int
    suitability_positive: int
    suitability_unrated: int
    suitability_caution: int

    @classmethod
    def load(cls) -> RoleQualityConfig:
        raw = yaml_files.load_yaml_file(paths.config_dir(CONFIG_NAME)) or {}
        specificity = raw.get("specificity") or {}
        classes = specificity.get("classes") or {}
        exposure = raw.get("exposure") or {}
        age = exposure.get("e1rm_age_days") or {}
        suitability = raw.get("suitability") or {}
        return cls(
            role_priority=tuple(raw.get("role_priority") or ("main", "secondary", "accessory")),
            criteria={
                role: tuple(values or ())
                for role, values in (raw.get("criteria") or {}).items()
            },
            specificity={
                str(key): int(value) for key, value in classes.items()
            },
            heavy_band=float(exposure.get("heavy_band") or 0.80),
            e1rm_full_days=int(age.get("full") or 14),
            e1rm_partial_days=int(age.get("partial") or 45),
            suitability_positive=int(suitability.get("explicit_positive") or 3),
            suitability_unrated=int(suitability.get("unrated") or 2),
            suitability_caution=int(suitability.get("eligible_with_caution") or 1),
        )


def _slot_role(slot: templates.Slot, main_slot: templates.Slot | None) -> str:
    if slot.power:
        return "power"
    if main_slot is not None and slot.id == main_slot.id:
        return "main"
    if slot.essential:
        return "secondary"
    return "accessory"


def _main_slot(base: templates.SessionTemplate) -> templates.Slot | None:
    for slot in base.slots:
        if base.primary_exercise is not None and base.primary_exercise in slot.exercises:
            return slot
    for slot in base.slots:
        if slot.essential and not slot.power:
            return slot
    return None


def _previous_choices(conn, *, session_type: str, before_date: str) -> dict[int, str]:
    row = conn.execute(
        """
        SELECT plan_json FROM workout_session
         WHERE session_type = ? AND for_date < ? AND status = 'completed'
         ORDER BY for_date DESC, started_at DESC LIMIT 1
        """,
        (session_type, before_date),
    ).fetchone()
    if row is None:
        return {}
    import json

    try:
        plan = json.loads(row["plan_json"])
    except (TypeError, ValueError):
        return {}
    items = plan.get("items") if isinstance(plan, Mapping) else None
    if not isinstance(items, list):
        return {}
    choices: dict[int, str] = {}
    for position, item in enumerate(items):
        if not isinstance(item, Mapping) or not item.get("exercise_id"):
            continue
        try:
            identity = int(item.get("order_index", position))
        except (TypeError, ValueError):
            identity = position
        choices[identity] = str(item["exercise_id"])
    return choices


def _family(exercise_id: str) -> str | None:
    from strength_coach.prescribe import summary

    for label, members in summary.LIFT_GROUPS:
        if exercise_id in members:
            return label
    return None


def _specificity_class(
    exercise_id: str,
    previous: str | None,
    taxonomy: Mapping[str, Mapping[str, Any]],
    config: RoleQualityConfig,
) -> int:
    if previous is None:
        return config.suitability_unrated
    if exercise_id == previous:
        return config.specificity.get("same_lift", 3)
    if _family(exercise_id) is not None and _family(exercise_id) == _family(previous):
        return config.specificity.get("same_lift_group", 2)
    if taxonomy.get(exercise_id, {}).get("pattern") == taxonomy.get(previous, {}).get("pattern"):
        return config.specificity.get("same_pattern", 1)
    return config.specificity.get("other_permitted_pattern", 0)


def _exposure_class(item: Any, config: RoleQualityConfig) -> int:
    intensity = getattr(item, "intensity", None)
    quality = getattr(item, "e1rm_quality", None)
    age = getattr(item, "e1rm_age_days", None)
    if intensity is None or quality is None:
        return 1
    if float(intensity) < config.heavy_band:
        return 0
    if quality == "ok" and age is not None and int(age) <= config.e1rm_full_days:
        return 2
    if age is not None and int(age) <= config.e1rm_partial_days:
        return 1
    return 0


def _suitability_class(exercise_id: str, suitability: Mapping[str, Mapping[str, Any]], config: RoleQualityConfig) -> int:
    rating = suitability.get(exercise_id)
    if rating is None:
        return config.suitability_unrated
    if int(rating.get("can_do", 1)) and not int(rating.get("feels_bad", 0)) and int(rating.get("will_do", 1)):
        return config.suitability_positive
    return config.suitability_caution


def _group_after(panel: Mapping[str, Any], pattern: str | None) -> tuple[float, float]:
    if not pattern:
        return 0.0, 0.0
    groups = panel.get("groups") or {}
    key = volume_feature.volume_target_key(pattern)
    group = groups.get(key) or {}
    return float(group.get("after") or 0.0), float(group.get("target") or 0.0)


def _complementarity_class(item: Any, main_pattern: str | None, taxonomy: Mapping[str, Mapping[str, Any]], config: RoleQualityConfig) -> int:
    pattern = taxonomy.get(str(item.exercise_id), {}).get("pattern")
    if main_pattern is None:
        return config.suitability_unrated
    if pattern == main_pattern:
        return 1
    if _family(str(item.exercise_id)) is not None:
        return 2
    return 3


def _volume_usefulness_class(after: float, target: float) -> int:
    if target <= 0:
        return 2
    if after < target:
        return 3
    if after <= target * 1.15:
        return 2
    return 1


def _coverage_class(
    item: Any,
    covered_patterns: set[str],
    taxonomy: Mapping[str, Mapping[str, Any]],
    config: RoleQualityConfig,
) -> int:
    pattern = taxonomy.get(str(item.exercise_id), {}).get("pattern")
    if pattern is None:
        return config.suitability_unrated
    return 3 if pattern not in covered_patterns else 1


@dataclass(frozen=True)
class RoleQualitySnapshot:
    roles: Mapping[str, tuple[dict[str, Any], ...]]
    vector: tuple[Any, ...]
    limitations: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "roles": {role: [dict(entry) for entry in entries] for role, entries in self.roles.items()},
            "vector": list(self.vector),
            "limitations": list(self.limitations),
        }


def snapshot(
    *,
    conn,
    for_date: str,
    base: templates.SessionTemplate,
    assignment: Mapping[str, str],
    prescription: Prescription,
    band_penalty: int,
    intent_penalty: int,
) -> RoleQualitySnapshot:
    """Build the role-quality vector for one complete finalist."""
    config = RoleQualityConfig.load()
    taxonomy = exercises.taxonomy().entities
    suitability = queries.exercise_suitability(conn)
    panel = prescription.notes.get("volume_panel") or {}
    previous = _previous_choices(conn, session_type=base.session_type, before_date=for_date)
    main_slot = _main_slot(base)
    items = {item.order_index: item for item in prescription.items}
    slots_by_item = {
        slot.id: assignment.get(slot.id) for slot in base.slots
    }
    main_exercise = slots_by_item.get(main_slot.id) if main_slot is not None else None
    main_pattern = taxonomy.get(str(main_exercise), {}).get("pattern") if main_exercise else None
    covered_patterns = {
        str(taxonomy.get(str(exercise_id), {}).get("pattern"))
        for slot_id, exercise_id in slots_by_item.items()
        if exercise_id and slot_id != (main_slot.id if main_slot else None)
    }
    roles: dict[str, list[dict[str, Any]]] = {
        "main": [], "secondary": [], "accessory": []
    }
    limitations: set[str] = set()
    for position, slot in enumerate(base.slots):
        role = _slot_role(slot, main_slot)
        if role == "power":
            continue
        exercise_id = assignment.get(slot.id)
        if exercise_id is None:
            continue
        item = items.get(position)
        if item is None:
            limitations.add("missing_item")
            continue
        previous_id = previous.get(position)
        if role == "main":
            classes = {
                "specificity": _specificity_class(exercise_id, previous_id, taxonomy, config),
                "exposure": _exposure_class(item, config),
                "suitability": _suitability_class(exercise_id, suitability, config),
            }
        elif role == "secondary":
            after, target = _group_after(panel, taxonomy.get(exercise_id, {}).get("pattern"))
            classes = {
                "complementarity": _complementarity_class(item, main_pattern, taxonomy, config),
                "volume_usefulness": _volume_usefulness_class(after, target),
                "redundancy": 2 if int(getattr(item, "sets", 0) or 0) > 0 else 1,
            }
        else:
            classes = {
                "coverage": _coverage_class(item, covered_patterns, taxonomy, config),
                "productive_volume": 2 if int(getattr(item, "sets", 0) or 0) > 0 else 1,
                "stimulus_to_fatigue": 2,
            }
        roles[role].append({
            "slot_id": slot.id,
            "exercise_id": exercise_id,
            "classes": classes,
        })
    # Flatten in role priority order. Each role's entries are already in slot order, so the
    # comparison is deterministic and never depends on a floating-point composite.
    vector: list[Any] = [int(band_penalty), int(intent_penalty)]
    for role in config.role_priority:
        entries = roles.get(role, [])
        if not entries:
            vector.extend((0, 0, 0))
            continue
        for entry in entries:
            vector.extend(-int(value) for value in entry["classes"].values())
    return RoleQualitySnapshot(
        roles={role: tuple(values) for role, values in roles.items()},
        vector=tuple(vector),
        limitations=tuple(sorted(limitations)),
    )

