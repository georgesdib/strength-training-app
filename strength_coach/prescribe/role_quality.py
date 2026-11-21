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
from strength_coach.prescribe import selection_tax, templates
from strength_coach.prescribe.models import Prescription
from strength_coach.store import queries
from strength_coach.utils import exercises, paths, yaml_files

CONFIG_NAME = "resolver-role-quality.v1.yaml"
VERSION = "role-quality-v3"

# Surfaced in the response snapshot. The stimulus rating is an ordinal assumption seeded from
# the evidence-graded local-muscular demand profile; it is not a measured magnitude.
STIMULUS_PROVISIONAL = "stimulus_to_fatigue_uses_provisional_ordinal_stimulus"
STIMULUS_MISSING = "stimulus_to_fatigue_missing_rating"


def config_digest() -> str:
    """Digest of the role-quality class config, so a class change moves the fingerprint."""
    return hashlib.sha256(
        paths.config_dir(CONFIG_NAME).read_bytes()
    ).hexdigest()


@dataclass(frozen=True)
class ClassScale:
    """One ordinal class family and its neutral value.

    `tolerance` is only meaningful for the volume scales; it uses the same 15% margin as the
    previous usefulness band and never replaces the weekly volume-band gate.
    """

    classes: Mapping[str, int]
    neutral: int = 2
    tolerance: float = 0.0

    def value(self, name: str) -> int:
        return int(self.classes.get(name, self.neutral))


def _scale(raw: Mapping[str, Any], key: str, *, tolerance: float = 0.0) -> ClassScale:
    block = raw.get(key) or {}
    classes = block.get("classes") or {}
    neutral = block.get("missing", block.get("neutral", 2))
    try:
        neutral_value = int(neutral)
    except (TypeError, ValueError):
        neutral_value = 2
    try:
        configured_tolerance = float(block.get("tolerance", tolerance))
    except (TypeError, ValueError):
        configured_tolerance = tolerance
    return ClassScale(
        classes={str(name): int(value) for name, value in classes.items()},
        neutral=neutral_value,
        tolerance=configured_tolerance,
    )


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
    complementarity: ClassScale
    volume_usefulness: ClassScale
    redundancy: ClassScale
    coverage: ClassScale
    productive_volume: ClassScale
    tax: ClassScale
    tax_mandatory_axes: Mapping[str, tuple[str, ...]]
    stimulus_ratings: Mapping[str, int]
    stimulus_to_fatigue: ClassScale

    @classmethod
    def load(cls) -> RoleQualityConfig:
        raw = yaml_files.load_yaml_file(paths.config_dir(CONFIG_NAME)) or {}
        specificity = raw.get("specificity") or {}
        classes = specificity.get("classes") or {}
        exposure = raw.get("exposure") or {}
        age = exposure.get("e1rm_age_days") or {}
        suitability = raw.get("suitability") or {}
        tax_axes = (raw.get("tax") or {}).get("mandatory_axes") or {}
        stimulus_ratings = (raw.get("stimulus") or {}).get("ratings") or {}
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
            complementarity=_scale(raw, "complementarity"),
            volume_usefulness=_scale(raw, "volume_usefulness"),
            redundancy=_scale(raw, "redundancy"),
            coverage=_scale(raw, "coverage"),
            productive_volume=_scale(raw, "productive_volume"),
            tax=_scale(raw, "tax"),
            tax_mandatory_axes={
                str(role): tuple(str(axis) for axis in (axes or ()))
                for role, axes in tax_axes.items()
            },
            stimulus_ratings={
                str(exercise_id): int(value)
                for exercise_id, value in stimulus_ratings.items()
            },
            stimulus_to_fatigue=_scale(raw, "stimulus_to_fatigue"),
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


def _pattern(exercise_id: str | None, taxonomy: Mapping[str, Mapping[str, Any]]) -> str | None:
    if not exercise_id:
        return None
    value = taxonomy.get(str(exercise_id), {}).get("pattern")
    return str(value) if value else None


def _family(exercise_id: str | None) -> str | None:
    if not exercise_id:
        return None
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


def _group_after(
    panel: Mapping[str, Any], pattern: str | None
) -> tuple[float, float] | None:
    """Return (after, target) for the pattern's ledger group, or None when unusable.

    `None` is the neutral state: a missing pattern, a missing panel group or a group without
    a positive target is not evidence of either a deficit or a surplus.
    """
    if not pattern:
        return None
    groups = panel.get("groups") or {}
    group = groups.get(volume_feature.volume_target_key(pattern))
    if not isinstance(group, Mapping):
        return None
    try:
        target = float(group.get("target") or 0.0)
        after = float(group.get("after") or 0.0)
    except (TypeError, ValueError):
        return None
    if target <= 0.0:
        return None
    return after, target


def _volume_contribution_class(
    after: float,
    target: float,
    contribution: int,
    scale: ClassScale,
) -> int:
    """Classify a candidate's marginal volume against its own pattern target.

    The weekly band remains a gate outside this module. Here the candidate's prescribed sets
    are removed from the post-session group volume, so "fills a deficit" means the group was
    below target before this candidate, not merely that the pattern exists. A candidate that
    pushes the group materially past target is not rewarded as a deficit filler.
    """
    if target <= 0.0 or after <= 0.0 or contribution <= 0:
        return scale.neutral
    tolerance = max(0.0, scale.tolerance)
    before = max(0.0, after - float(contribution))
    if before >= target:
        return scale.value("redundant")
    if after <= target * (1.0 + tolerance):
        return scale.value("fills_deficit")
    return scale.value("within_target")


def _complementarity_class(
    exercise_id: str,
    main_exercise_id: str | None,
    main_pattern: str | None,
    taxonomy: Mapping[str, Mapping[str, Any]],
    config: RoleQualityConfig,
) -> int:
    """Compare the candidate's pattern/family with the main lift actually selected.

    Family membership is only useful relative to the main lift. The materialised volume key
    (features.volume.volume_target_key) is the existing evidence that two named patterns train
    the same ledger family; it keeps, for example, a split squat from counting as a complement
    to a bilateral squat. Missing taxonomy is neutral.
    """
    scale = config.complementarity
    pattern = _pattern(exercise_id, taxonomy)
    if main_pattern is None or pattern is None:
        return scale.neutral
    if pattern == main_pattern:
        return scale.value("same_pattern")
    if volume_feature.volume_target_key(pattern) == volume_feature.volume_target_key(main_pattern):
        return scale.value("same_pattern")
    candidate_family = _family(exercise_id)
    main_family = _family(main_exercise_id)
    if candidate_family is not None and candidate_family == main_family:
        return scale.value("same_family")
    return scale.value("complementary")


def _redundancy_class(
    exercise_id: str,
    other_exercises: tuple[str, ...],
    taxonomy: Mapping[str, Mapping[str, Any]],
    config: RoleQualityConfig,
) -> int:
    """Compare the candidate with the main and the other selected exercises.

    The class is not a prescribed-set check: positive sets are not evidence of redundancy.
    A duplicate pattern, materialised pattern key or lift family is redundant; sharing a
    primary muscle without duplicating a pattern is a partial overlap; otherwise the
    candidate contributes a complementary stimulus. Missing classification data is neutral.
    """
    scale = config.redundancy
    pattern = _pattern(exercise_id, taxonomy)
    family = _family(exercise_id)
    if pattern is None and family is None:
        return scale.neutral
    candidate_muscles = {
        str(muscle)
        for muscle in (taxonomy.get(exercise_id, {}).get("primary_muscles") or ())
    }
    comparable = False
    partial = False
    duplicate = False
    for other in other_exercises:
        if other == exercise_id:
            comparable = True
            duplicate = True
            break
        other_pattern = _pattern(other, taxonomy)
        other_family = _family(other)
        if pattern is not None and other_pattern is not None:
            comparable = True
            if (
                pattern == other_pattern
                or volume_feature.volume_target_key(pattern)
                == volume_feature.volume_target_key(other_pattern)
            ):
                duplicate = True
                break
        if family is not None and other_family is not None:
            comparable = True
            if family == other_family:
                duplicate = True
                break
        other_muscles = {
            str(muscle)
            for muscle in (taxonomy.get(other, {}).get("primary_muscles") or ())
        }
        if candidate_muscles and other_muscles:
            comparable = True
            if candidate_muscles & other_muscles:
                partial = True
    if duplicate:
        return scale.value("duplicate")
    if not comparable:
        return scale.neutral
    if partial:
        return scale.value("partial_overlap")
    return scale.value("complementary")


def _coverage_class(
    exercise_id: str,
    other_exercises: tuple[str, ...],
    taxonomy: Mapping[str, Mapping[str, Any]],
    config: RoleQualityConfig,
) -> int:
    """Classify whether the accessory's pattern is covered by the other selected work.

    The candidate's own slot is already excluded by the caller, so an accessory cannot cover
    itself. Missing taxonomy on the candidate is neutral, and missing taxonomy on every other
    exercise cannot establish a new uncovered pattern.
    """
    scale = config.coverage
    pattern = _pattern(exercise_id, taxonomy)
    if pattern is None:
        return scale.neutral
    family = _family(exercise_id)
    comparable = False
    for other in other_exercises:
        other_pattern = _pattern(other, taxonomy)
        other_family = _family(other)
        if other_pattern is not None or other_family is not None:
            comparable = True
        if other_pattern is not None and other_pattern == pattern:
            return scale.value("covered")
        if family is not None and other_family == family:
            return scale.value("covered")
    if not comparable:
        return scale.neutral
    return scale.value("uncovered")


_STIMULUS_LABELS = {3: "high", 2: "moderate", 1: "low"}
_FATIGUE_LABELS = {3: "low", 2: "moderate", 1: "high"}


def _stimulus_inputs(
    exercise_id: str,
    essential: bool,
    tax_config: selection_tax.TaxConfig,
    config: RoleQualityConfig,
) -> tuple[int | None, int | None]:
    """Return (stimulus rating, worst mandatory tax axis), or None when unavailable."""
    stimulus = config.stimulus_ratings.get(exercise_id)
    if stimulus not in _STIMULUS_LABELS:
        stimulus = None
    tax = tax_config.for_exercise(exercise_id)
    if tax is None:
        return stimulus, None
    axes = config.tax_mandatory_axes.get(
        "essential" if essential else "accessory", ()
    )
    if not axes:
        return stimulus, None
    values = [getattr(tax, axis, None) for axis in axes]
    if any(value is None for value in values):
        return stimulus, None
    return stimulus, max(int(value) for value in values)


def _stimulus_to_fatigue_from_inputs(
    stimulus: int | None,
    fatigue: int | None,
    config: RoleQualityConfig,
) -> int:
    """Map the two ordinals through the configured matrix.

    Higher stimulus and lower mandatory-axis cost are better. The matrix deliberately leaves
    the incomparable corners (high stimulus/high cost, moderate/moderate, low/low) at the same
    neutral class instead of inventing a ratio. Missing either input is neutral.
    """
    scale = config.stimulus_to_fatigue
    if stimulus is None or fatigue is None:
        return scale.neutral
    stimulus_label = _STIMULUS_LABELS.get(stimulus)
    if stimulus_label is None:
        return scale.neutral
    if fatigue <= 1:
        fatigue_class = config.tax.value("low")
    elif fatigue == 2:
        fatigue_class = config.tax.value("moderate")
    else:
        fatigue_class = config.tax.value("high")
    fatigue_label = _FATIGUE_LABELS.get(fatigue_class)
    if fatigue_label is None:
        return scale.neutral
    return scale.value(f"{stimulus_label}_{fatigue_label}")


def _stimulus_to_fatigue_class(
    exercise_id: str,
    essential: bool,
    tax_config: selection_tax.TaxConfig,
    config: RoleQualityConfig,
) -> int:
    """Rank productive stimulus against the role-specific mandatory tax axes.

    The stimulus rating is the ordinal `stimulus.ratings` block, seeded from the
    evidence-graded local-muscular demand profile and the taxonomy's primary-compound flag;
    it is provisional, not a measured magnitude. The fatigue side reuses the mandatory tax
    axes (accessory: axial and skill; essential: axial, systemic and skill). Missing either
    input is neutral.
    """
    stimulus, fatigue = _stimulus_inputs(exercise_id, essential, tax_config, config)
    return _stimulus_to_fatigue_from_inputs(stimulus, fatigue, config)


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
    tax_config = selection_tax.TaxConfig.load()
    panel = prescription.notes.get("volume_panel") or {}
    previous = _previous_choices(conn, session_type=base.session_type, before_date=for_date)
    main_slot = _main_slot(base)
    items = {item.order_index: item for item in prescription.items}
    selected_by_slot = {slot.id: assignment.get(slot.id) for slot in base.slots}
    roles_by_slot = {slot.id: _slot_role(slot, main_slot) for slot in base.slots}
    main_exercise = selected_by_slot.get(main_slot.id) if main_slot is not None else None
    main_pattern = _pattern(main_exercise, taxonomy)
    roles: dict[str, list[dict[str, Any]]] = {
        "main": [], "secondary": [], "accessory": []
    }
    limitations: set[str] = set()
    for position, slot in enumerate(base.slots):
        role = roles_by_slot[slot.id]
        if role == "power":
            continue
        exercise_id = selected_by_slot.get(slot.id)
        if exercise_id is None:
            continue
        item = items.get(position)
        if item is None:
            limitations.add("missing_item")
            continue
        previous_id = previous.get(position)
        # The candidate's own slot is excluded, so an accessory cannot cover itself and a
        # secondary is never compared with itself. Power work is fixed by its quality stop and
        # is not part of the quality hierarchy.
        other_exercises = tuple(
            other_id
            for other in base.slots
            if other.id != slot.id
            and roles_by_slot[other.id] != "power"
            and (other_id := selected_by_slot.get(other.id)) is not None
        )
        if role == "main":
            classes = {
                "specificity": _specificity_class(exercise_id, previous_id, taxonomy, config),
                "exposure": _exposure_class(item, config),
                "suitability": _suitability_class(exercise_id, suitability, config),
            }
        elif role == "secondary":
            pattern = _pattern(exercise_id, taxonomy)
            group = _group_after(panel, pattern)
            after, target = group if group is not None else (0.0, 0.0)
            volume_class = (
                _volume_contribution_class(
                    after, target, int(getattr(item, "sets", 0) or 0),
                    config.volume_usefulness,
                )
                if group is not None
                else config.volume_usefulness.neutral
            )
            classes = {
                "complementarity": _complementarity_class(
                    exercise_id, main_exercise, main_pattern, taxonomy, config
                ),
                "volume_usefulness": volume_class,
                "redundancy": _redundancy_class(
                    exercise_id, other_exercises, taxonomy, config
                ),
            }
        else:
            pattern = _pattern(exercise_id, taxonomy)
            group = _group_after(panel, pattern)
            after, target = group if group is not None else (0.0, 0.0)
            volume_class = (
                _volume_contribution_class(
                    after, target, int(getattr(item, "sets", 0) or 0),
                    config.productive_volume,
                )
                if group is not None
                else config.productive_volume.neutral
            )
            stimulus, fatigue = _stimulus_inputs(
                exercise_id, slot.essential, tax_config, config
            )
            classes = {
                "coverage": _coverage_class(
                    exercise_id, other_exercises, taxonomy, config
                ),
                "productive_volume": volume_class,
                "stimulus_to_fatigue": _stimulus_to_fatigue_from_inputs(
                    stimulus, fatigue, config
                ),
            }
            limitations.add(STIMULUS_PROVISIONAL)
            if stimulus is None or fatigue is None:
                limitations.add(STIMULUS_MISSING)
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
        criteria = config.criteria.get(role, ())
        if not entries:
            vector.extend(0 for _ in criteria)
            continue
        for entry in entries:
            ordered = criteria or tuple(entry["classes"])
            vector.extend(-int(entry["classes"].get(name, 0)) for name in ordered)
    return RoleQualitySnapshot(
        roles={role: tuple(values) for role, values in roles.items()},
        vector=tuple(vector),
        limitations=tuple(sorted(limitations)),
    )
