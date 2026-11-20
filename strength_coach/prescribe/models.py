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

    Straight sets use an empty tuple on the item. A structured item carries an ordered tuple
    of groups, so persistence and workout logging never split the exercise into duplicate item
    rows. Order is the only identity on the wire and in persistence: `role` is an engine
    build-time tag used by the top-set arithmetic and is never serialized or read by analysis
    (DEC-RESOLVER-18).
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


def group_payload(group: SetGroup, group_index: int) -> dict[str, Any]:
    """Serialize one planned group for the API, persistence and the frozen plan.

    The index is the caller's list position, so the wire states the same order that is read.
    The build-time role and the back-off ratio are deliberately omitted: order is the only
    identity a client, a stored row or an analysis layer sees (DEC-RESOLVER-18).
    """
    return {
        "group_index": group_index,
        "sets": group.sets,
        "load_kg": group.load_kg,
        "reps_low": group.reps_low,
        "reps_high": group.reps_high,
        "rir_target": group.rir_target,
    }


def validate_plan_set_groups(item: Mapping[str, Any], *, where: str = "plan item") -> None:
    """Validate a persisted/started plan item's optional set groups.

    Groups are identified by list order. `group_index` is optional on read, because a legacy
    plan predates it; when present it must restate the list position, so a plan cannot claim
    an order it does not have. No role is stored or required, and a legacy one is ignored
    (DEC-RESOLVER-18). The plan is the execution contract, so group totals must equal
    item.sets and every group must carry a usable load.
    """
    groups = item.get("set_groups") or ()
    if not groups:
        return
    if not isinstance(groups, (list, tuple)):
        raise ValueError(f"{where}: set_groups must be a list")
    total = 0
    for index, group in enumerate(groups):
        group_where = f"{where}.set_groups[{index}]"
        if not isinstance(group, Mapping):
            raise ValueError(f"{group_where} must be an object")
        group_index = group.get("group_index")
        if group_index is not None and (
            isinstance(group_index, bool)
            or not isinstance(group_index, int)
            or group_index != index
        ):
            raise ValueError(
                f"{group_where}: group_index must be {index}; groups are read by list order"
            )
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

    Groups are merged by the order they are read: each group keeps its own sets until the new
    total is reached, the last surviving group absorbs the remainder, and groups that no
    longer fit are dropped. A one-set item keeps the first group and its summary load, which
    is the structured set rather than the back-off summary. A plan without groups is
    unchanged. Plan editing is removed by the frozen-plan package; this rule exists only for
    the edit path that is still live.
    """
    groups = [dict(group) for group in (item.get("set_groups") or ())]
    if not groups:
        return dict(item)
    sets = int(item.get("sets") or 0)
    if sets < 1:
        return dict(item)
    kept: list[dict[str, Any]] = []
    remaining = sets
    for group in groups:
        if remaining < 1:
            break
        take = min(int(group.get("sets") or 0), remaining)
        kept.append({**group, "sets": take})
        remaining -= take
    if remaining:
        kept[-1]["sets"] = int(kept[-1]["sets"]) + remaining
    if len(kept) == 1:
        return {
            **dict(item),
            "set_groups": kept,
            "load_kg": kept[0].get("load_kg"),
            "rir_target": kept[0].get("rir_target"),
        }
    return {**dict(item), "set_groups": kept}


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
    reps_unit: str = "reps"
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
                            group_payload(group, index)
                            for index, group in enumerate(item.set_groups)
                        ]
                    }
                    if item.set_groups
                    else {}
                ),
            }
            for item in self.items
        ]
