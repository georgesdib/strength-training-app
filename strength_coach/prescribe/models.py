"""Prescription value objects.

Frozen dataclasses, so a prescription that has been shown to the athlete cannot be edited in
place; a correction is a new prescription with a pointer back (AGENTS.md §3.7).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WarmupSet:
    """One ramp set, expressed as a percentage and its rounded load."""
    percent: float
    reps: int
    load_kg: float


@dataclass(frozen=True)
class SetGroup:
    """One planned set group inside an item.

    Straight sets use an empty tuple on the item. A top-set structure carries one top_set
    group and one back_off group, so persistence and workout logging never split the exercise
    into duplicate item rows.
    """

    role: str
    sets: int
    load_kg: float | None
    reps_low: int
    reps_high: int
    rir_target: int | None
    percent_of_top: float | None = None


SET_GROUP_ROLES = ("top_set", "back_off")


def _plan_int(value: Any, field: str, *, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{where}: {field} must be an integer from {low} to {high}")
    return value


def validate_plan_set_groups(item: Mapping[str, Any], *, where: str = "plan item") -> None:
    """Validate a persisted/started plan item's optional set groups.

    The plan is the execution contract: group totals must equal item.sets, roles must be
    unique and known, and every group must carry a usable load. This prevents the
    preview/workout boundary from accepting a structure the engine would never emit.
    """
    groups = item.get("set_groups") or ()
    if not groups:
        return
    if not isinstance(groups, (list, tuple)):
        raise ValueError(f"{where}: set_groups must be a list")
    total = 0
    roles: set[str] = set()
    for index, group in enumerate(groups):
        group_where = f"{where}.set_groups[{index}]"
        if not isinstance(group, Mapping):
            raise ValueError(f"{group_where} must be an object")
        role = group.get("role")
        if role not in SET_GROUP_ROLES:
            raise ValueError(f"{group_where}: role must be top_set or back_off")
        if role in roles:
            raise ValueError(f"{group_where}: duplicate set-group role {role!r}")
        roles.add(role)
        sets = _plan_int(group.get("sets"), "sets", where=group_where, low=1, high=50)
        total += sets
        _plan_int(group.get("reps_low"), "reps_low", where=group_where, low=1, high=100)
        _plan_int(group.get("reps_high"), "reps_high", where=group_where, low=1, high=100)
        if int(group["reps_low"]) > int(group["reps_high"]):
            raise ValueError(f"{group_where}: reps_low must not exceed reps_high")
        load = group.get("load_kg")
        if isinstance(load, bool) or not isinstance(load, (int, float)):
            raise ValueError(f"{group_where}: load_kg must be a number")
        rir = group.get("rir_target")
        if rir is not None:
            _plan_int(rir, "rir_target", where=group_where, low=0, high=10)
    expected = _plan_int(item.get("sets"), "sets", where=where, low=0, high=50)
    if total != expected:
        raise ValueError(
            f"{where}: set_groups total {total} must equal item.sets {expected}"
        )


def validate_plan_items(items: Any, *, where: str = "plan") -> None:
    if not isinstance(items, (list, tuple)):
        raise ValueError(f"{where}.items must be a list")
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ValueError(f"{where}.items[{index}] must be an object")
        validate_plan_set_groups(item, where=f"{where}.items[{index}]")


def resize_plan_item_set_groups(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep plan groups consistent after a planned-set edit.

    Mirrors the engine resize: one set keeps the protected top set; two or more sets keep
    one top set and put the remainder in back-off. A plan without groups is unchanged.
    """
    groups = list(item.get("set_groups") or ())
    if not groups:
        return dict(item)
    top = next((group for group in groups if group.get("role") == "top_set"), None)
    backoff = next((group for group in groups if group.get("role") == "back_off"), None)
    if top is None or backoff is None:
        return dict(item)
    sets = int(item.get("sets") or 0)
    if sets < 2:
        return {
            **dict(item),
            "set_groups": [top],
            "load_kg": top.get("load_kg"),
            "rir_target": top.get("rir_target"),
        }
    return {
        **dict(item),
        "set_groups": [top, {**backoff, "sets": sets - 1}],
    }


@dataclass(frozen=True)
class VbtTarget:
    """Structured provenance for one issued velocity target.

    The target is conditional on a rep count and an RIR band. The calibration id links to the
    append-only vbt_calibration row, so a historical prescription can explain the exact target
    it was issued with even after later recalibration. Values are never reconstructed from a
    current calibration.
    """

    target_mps: float
    low_mps: float | None
    high_mps: float | None
    rep_count: int
    rir_low: int
    rir_high: int
    scope: str
    family: str | None
    n_sets: int
    n_sessions: int
    method_version: str
    calibration_id: str | None = None
    source: str = "computed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_mps": self.target_mps,
            "low_mps": self.low_mps,
            "high_mps": self.high_mps,
            "rep_count": self.rep_count,
            "rir_low": self.rir_low,
            "rir_high": self.rir_high,
            "scope": self.scope,
            "family": self.family,
            "n_sets": self.n_sets,
            "n_sessions": self.n_sessions,
            "method_version": self.method_version,
            "calibration_id": self.calibration_id,
            "source": self.source,
        }


@dataclass(frozen=True)
class PrescriptionItem:
    order_index: int
    exercise_id: str
    sets: int
    reps_low: int
    reps_high: int
    load_kg: float | None
    load_basis: str
    rounding_increment_kg: float
    rir_target: int | None
    rest_s: int | None
    essential: bool
    rationale_refs: tuple[str, ...] = ()
    substitution_for: str | None = None
    time_cap_s: int | None = None
    # Set when the engine refused to invent a load. The prescription is then not executable.
    unknown_load_reason: str | None = None
    # VBT target from the per-lift calibration, when one is trustworthy enough to cite.
    # None means "no target", never a guessed velocity (docs/VBT-CALIBRATION.md).
    velocity_target: float | None = None
    vbt_basis: str | None = None
    # Structured target provenance; additive to velocity_target/vbt_basis and frozen into
    # plan_json. None means no trustworthy target was issued, never "reconstruct later".
    vbt: VbtTarget | None = None
    # Number of usable sets behind a formula e1RM; None for overrides/fallbacks/accessories.
    e1rm_source_sets: int | None = None
    # Plan-snapshot provenance. These are serialised into plan_json, never prescription_item.
    e1rm_kg: float | None = None
    e1rm_ref: str | None = None
    e1rm_quality: str | None = None
    e1rm_age_days: int | None = None
    # Mean working-set intensity as a fraction of e1RM; None when it cannot be estimated.
    intensity: float | None = None
    # Cumulative load multiplier from e1RM decay, readiness, continuity and deload. Display
    # provenance only; the stored prescription remains the source for the actual load.
    load_factor: float = 1.0
    # Resolved flare policy: hold, reviewed, dose or none. Generation-time only; the stored
    # prescription is the outcome, not this policy (DEC-SPINE-07).
    flare: str = "none"
    # Power work is quality-limited: no RIR target, a stored stop rule (DEC-POWER-02).
    effort_model: str = "rir"
    quality_stop: str | None = None
    # Main-lift ramp sets; empty for accessories and unknown loads.
    warmup: tuple[WarmupSet, ...] = ()
    # Optional top-set/back-off structure. Empty means straight sets.
    set_groups: tuple[SetGroup, ...] = ()


@dataclass(frozen=True)
class Prescription:
    for_date: str
    session_type: str
    fallback_level: str
    rule_document_version: str
    items: tuple[PrescriptionItem, ...]
    time_cap_s: int | None = None
    warnings: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    calibration_ids: tuple[str, ...] = ()
    notes: Mapping[str, Any] = field(default_factory=dict)

    @property
    def executable(self) -> bool:
        """V0-SCOPE §4.4: every load is real, rounded, and inside its RIR window."""
        return not self.issues and all(
            item.load_kg is not None and item.unknown_load_reason is None for item in self.items
        )

    def item(self, order_index: int) -> PrescriptionItem:
        return self.items[order_index]

    def as_rows(self) -> list[dict]:
        """Flat rows, shaped for the prescription_item table."""
        return [
            {
                "order_index": item.order_index,
                "exercise_id": item.exercise_id,
                "sets": item.sets,
                "reps_low": item.reps_low,
                "reps_high": item.reps_high,
                "load_kg": item.load_kg,
                "load_basis": item.load_basis,
                "rounding_increment": item.rounding_increment_kg,
                "rir_target": item.rir_target,
                "effort_model": item.effort_model,
                "quality_stop": item.quality_stop,
                "rest_s": item.rest_s,
                "time_cap_s": item.time_cap_s,
                "essential": item.essential,
                "rationale_refs": list(item.rationale_refs),
                "substitution_for": item.substitution_for,
                "velocity_target": item.velocity_target,
                "vbt_basis": item.vbt_basis,
                "e1rm_source_sets": item.e1rm_source_sets,
                "warmup": [
                    {"percent": w.percent, "reps": w.reps, "load_kg": w.load_kg}
                    for w in item.warmup
                ],
                **(
                    {
                        "set_groups": [
                            {
                                "role": group.role,
                                "sets": group.sets,
                                "load_kg": group.load_kg,
                                "reps_low": group.reps_low,
                                "reps_high": group.reps_high,
                                "rir_target": group.rir_target,
                                "percent_of_top": group.percent_of_top,
                            }
                            for group in item.set_groups
                        ]
                    }
                    if item.set_groups
                    else {}
                ),
            }
            for item in self.items
        ]
