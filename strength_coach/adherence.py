"""Prescription adherence analysis for a completed workout.

The engine compares actual working sets with two immutable snapshots:

* the original prescription (workout_session.plan_json), and
* the final in-workout prescription (plan_modified_json, or the original when unmodified).

It is deliberately observational. Nothing here writes, persists or backfills data, and a
metric that cannot be computed is returned as unavailable with a reason rather than a zero.

Definitions
-----------
Set completion
    Prescribed slots that a performed working set fills. A performed set beyond the planned
    count still belongs to the item but is extra work; it does not raise completion above
    100%. Completion is not target attainment: a set can fill a slot and miss its reps,
    load or RIR target.

Working sets
    The existing authoritative classification is clean_set.is_working_set: RIR 6 is the
    logged warm-up sentinel (DEC-RIR-01), everything else is a working set. A row whose role
    and RIR contradict each other (RIR 6 tagged top_set/back_off) is ambiguous and is excluded
    from both counts. A row without RIR is treated as working, matching materialisation, but
    its RIR target comparison is unavailable.

RIR deviation
    actual RIR minus target RIR. Positive means the athlete stopped further from failure than
    prescribed; negative means closer to failure than prescribed.

Load comparison
    Prescribed and actual load are compared as external load. A bodyweight prescription of
    0 kg is external 0 kg; an added-load prescription is the plate. A device-captured total
    mass on a bodyweight movement cannot reveal the added plate, so it is left unavailable
    instead of being treated as 0 kg. Time-based movements are not load-scored. Percentage
    warm-up ramps are planning data, not actual-set targets, and are not compared here.

Attribution
    Sets join through the stable plan-item identity (order_index) and the exercise stored on
    the set. Display names are never the join key. Unmatched, ambiguous and mismatched sets
    stay visible in the payload.

Ratios always carry numerator and denominator. A zero denominator produces ratio None.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from strength_coach.domain import load as load_mod
from strength_coach.domain.plan_identity import item_identity, row_plan_identity
from strength_coach.utils import exercises

VERSION = 1
# One RIR step is the resolution of the logged scale, so +/-1 keeps a set inside its target
# window without pretending the difference between RIR 2 and RIR 3 is a different stimulus.
RIR_TOLERANCE = 1
WARM_UP_RIR = 6
SET_ROLES = ("top_set", "back_off")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": int(numerator),
        "denominator": int(denominator),
        "ratio": round(numerator / denominator, 4) if denominator else None,
    }


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _items(view: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in (view.get("items") or []) if isinstance(item, Mapping)]


def _items_by_identity(items: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    return {item_identity(item, position): item for position, item in enumerate(items)}


def _infer_load_basis(item: Mapping[str, Any], *, is_bodyweight: bool) -> str:
    """Read load_basis, or infer the engine's documented default for legacy plan JSON."""
    basis = item.get("load_basis")
    if basis in {"external", "bodyweight_total", "unknown"}:
        return str(basis)
    load = _number(item.get("load_kg"))
    if is_bodyweight and (load is None or load == 0):
        return "bodyweight_total"
    return "external" if load is not None else "unknown"


def _classify_set(row: Mapping[str, Any]) -> str:
    """Classify one actual set as working, warm-up or ambiguous.

    A materialised clean_set row carries is_working_set, which is the authoritative
    classification used by volume and reports. Live workout rows do not, so they fall back to
    the same RIR 6 sentinel that materialisation uses.
    """
    role = row.get("set_role")
    if role is not None and role not in SET_ROLES:
        return "ambiguous"
    stored = row.get("is_working_set")
    if stored is not None:
        try:
            working = int(stored)
        except (TypeError, ValueError):
            return "ambiguous"
        if working not in (0, 1):
            return "ambiguous"
        if working == 0:
            # A top-set/back-off role on a warm-up row contradicts the stored classification.
            return "ambiguous" if role in SET_ROLES else "warm_up"
        return "working"
    if _integer(row.get("rir")) == WARM_UP_RIR:
        # RIR 6 alone is the documented warm-up sentinel, but a top-set/back-off role on the
        # same row contradicts it: keep the record visible instead of guessing which wins.
        return "ambiguous" if role in SET_ROLES else "warm_up"
    return "working"


def _group_for_set(
    item: Mapping[str, Any], row: Mapping[str, Any]
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Resolve the set-group target for a top-set/back-off item.

    The item-level load of such an item is the back-off load, so comparing a top set with it
    would be wrong. Without a role the target is usable only when every group is identical.
    """
    groups = [group for group in (item.get("set_groups") or []) if isinstance(group, Mapping)]
    if not groups:
        return None, None
    role = row.get("set_role")
    if role is not None:
        for group in groups:
            if group.get("role") == role:
                return group, None
        return None, "unknown_set_role"
    if len(groups) == 1:
        return groups[0], None
    keys = ("load_kg", "rir_target", "reps_low", "reps_high")
    first = groups[0]
    if all(all(group.get(key) == first.get(key) for key in keys) for group in groups[1:]):
        return first, None
    return None, "ambiguous_set_role"


def _reps_target(
    item: Mapping[str, Any], row: Mapping[str, Any], group: Mapping[str, Any] | None
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Resolve a repetition target; groups normally share the item range."""
    groups = [value for value in (item.get("set_groups") or []) if isinstance(value, Mapping)]
    if group is not None:
        return group, None
    if groups:
        ranges = {(value.get("reps_low"), value.get("reps_high")) for value in groups}
        if len(ranges) == 1:
            low, high = next(iter(ranges))
            return {"reps_low": low, "reps_high": high}, None
        return None, "ambiguous_set_role"
    return item, None


def _actual_external_load(
    row: Mapping[str, Any],
    *,
    bodyweight_kg: float | None,
    is_bodyweight: bool,
    is_time_based: bool,
) -> tuple[float | None, str | None, str | None]:
    """Return actual external load, its basis, and a limitation code when unavailable.

    A materialised clean_set row already stores the resolved load_basis and external_load_kg,
    computed when the set was written. Prefer that record over re-resolving the raw number,
    which can differ after a bodyweight change or a history correction.
    """
    raw = _number(row.get("load_kg"))
    if raw is None:
        return None, None, "missing_actual_load"
    if is_time_based:
        return None, None, "time_based_load"
    stored_basis = row.get("load_basis")
    if stored_basis in {"external", "added", "bodyweight_total", "unknown"}:
        if stored_basis == "unknown":
            return None, stored_basis, "unknown_actual_load_basis"
        stored_external = _number(row.get("external_load_kg"))
        if stored_external is None and stored_basis in {"external", "added"}:
            stored_external = raw
        if stored_external is None and stored_basis == "bodyweight_total":
            stored_external = 0.0
        return stored_external, stored_basis, None
    resolved = load_mod.resolve_load_basis(
        raw,
        bodyweight_kg=bodyweight_kg,
        is_bodyweight_type=is_bodyweight,
        is_time_based=False,
    )
    if resolved.basis == "unknown":
        return None, resolved.basis, "unknown_actual_load_basis"
    return resolved.external_load_kg, resolved.basis, None


def _prescribed_external_load(
    item: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    is_bodyweight: bool,
    is_time_based: bool,
) -> tuple[float | None, str | None, str | None]:
    """Return prescribed external load, its basis, and a limitation code when unavailable."""
    basis = _infer_load_basis(item, is_bodyweight=is_bodyweight)
    load = _number(target.get("load_kg"))
    if is_time_based:
        return None, basis, "time_based_load"
    if basis == "unknown" or load is None:
        return None, basis, "missing_prescribed_load"
    if basis == "bodyweight_total":
        if load != 0:
            # A total-mass prescription is not generated by the engine; refuse to guess
            # whether it means bodyweight alone or bodyweight plus a plate.
            return None, basis, "unsupported_bodyweight_total_target"
        return 0.0, basis, None
    return load, basis, None


def _load_tolerance(item: Mapping[str, Any], prescribed: float) -> float:
    increment = _number(item.get("rounding_increment"))
    if increment is not None and increment > 0:
        return increment
    return load_mod.default_increment_kg(prescribed)


def _set_metrics(
    row: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    bodyweight_kg: float | None,
    is_bodyweight: bool,
    is_time_based: bool,
    included: bool,
    matched: bool,
) -> dict[str, Any]:
    """Evaluate one attributed set against its item (and set-group) target."""
    group, group_limitation = _group_for_set(item, row)
    limitations: list[str] = []
    if group_limitation:
        limitations.append(group_limitation)

    reps_target, reps_limitation = _reps_target(item, row, group)
    if reps_limitation and reps_limitation not in limitations:
        limitations.append(reps_limitation)
    reps_low = None if reps_target is None else _integer(reps_target.get("reps_low"))
    reps_high = None if reps_target is None else _integer(reps_target.get("reps_high"))
    actual_reps = _integer(row.get("reps"))
    reps_status = "unavailable"
    if reps_low is None or reps_high is None or reps_low < 1 or reps_high < reps_low:
        if "missing_prescribed_reps" not in limitations:
            limitations.append("missing_prescribed_reps")
    elif actual_reps is None or actual_reps < 1:
        if "missing_actual_reps" not in limitations:
            limitations.append("missing_actual_reps")
    else:
        if actual_reps < reps_low:
            reps_status = "below"
        elif actual_reps > reps_high:
            reps_status = "above"
        else:
            reps_status = "within"

    prescribed_load = None
    load_status = "unavailable"
    load_tolerance = None
    load_deviation = None
    load_pct = None
    actual_external = None
    if group_limitation:
        pass
    else:
        prescribed_load, prescribed_basis, load_limitation = _prescribed_external_load(
            item,
            group if group is not None else item,
            is_bodyweight=is_bodyweight,
            is_time_based=is_time_based,
        )
        if load_limitation:
            if load_limitation not in limitations:
                limitations.append(load_limitation)
        else:
            actual_external, actual_basis, actual_limitation = _actual_external_load(
                row,
                bodyweight_kg=bodyweight_kg,
                is_bodyweight=is_bodyweight,
                is_time_based=is_time_based,
            )
            if actual_limitation:
                if actual_limitation not in limitations:
                    limitations.append(actual_limitation)
            elif prescribed_load is not None and actual_external is not None:
                if (
                    is_bodyweight
                    and prescribed_basis == "external"
                    and actual_basis == "bodyweight_total"
                ):
                    # A captured total mass cannot reveal the plate that was added, so it is
                    # not comparable with an added-load prescription.
                    limitations.append("actual_load_includes_bodyweight")
                else:
                    load_tolerance = _load_tolerance(item, prescribed_load)
                    load_deviation = round(actual_external - prescribed_load, 2)
                    if prescribed_load > 0:
                        load_pct = round(load_deviation / prescribed_load * 100, 2)
                    if abs(load_deviation) <= load_tolerance:
                        load_status = "at_target"
                    elif load_deviation > 0:
                        load_status = "above"
                    else:
                        load_status = "below"

    rir_target = None
    rir_actual = _integer(row.get("rir"))
    rir_deviation = None
    rir_status = "unavailable"
    effort_model = item.get("effort_model")
    if effort_model not in (None, "rir"):
        if "non_rir_effort_model" not in limitations:
            limitations.append("non_rir_effort_model")
    elif group_limitation:
        pass
    else:
        rir_target = _integer((group if group is not None else item).get("rir_target"))
        if rir_target is None:
            if "missing_prescribed_rir" not in limitations:
                limitations.append("missing_prescribed_rir")
        elif rir_actual is None:
            if "missing_actual_rir" not in limitations:
                limitations.append("missing_actual_rir")
        else:
            rir_deviation = rir_actual - rir_target
            if abs(rir_deviation) <= RIR_TOLERANCE:
                rir_status = "at_target"
            elif rir_deviation > 0:
                rir_status = "above"
            else:
                rir_status = "below"

    return {
        "set_id": row.get("set_id"),
        "set_index": row.get("set_index"),
        "exercise_id": row.get("exercise_id"),
        "set_role": row.get("set_role"),
        "matched": matched,
        "extra": not matched,
        "included_in_attainment": included,
        "reps_actual": actual_reps,
        "reps_target_low": reps_low,
        "reps_target_high": reps_high,
        "reps_status": reps_status,
        "reps_unit": "seconds" if is_time_based else "reps",
        "load_actual_kg": _number(row.get("load_kg")),
        "load_actual_external_kg": (
            None if actual_external is None else round(actual_external, 2)
        ),
        "load_target_kg": None if prescribed_load is None else round(prescribed_load, 2),
        "load_tolerance_kg": load_tolerance,
        "load_deviation_kg": load_deviation,
        "load_deviation_pct": load_pct,
        "load_status": load_status,
        "rir_actual": rir_actual,
        "rir_target": rir_target,
        "rir_deviation": rir_deviation,
        "rir_status": rir_status,
        "limitations": sorted(limitations),
    }


def _reps_summary(details: Sequence[Mapping[str, Any]], matched_count: int) -> dict[str, Any]:
    evaluated = [
        row for row in details
        if row["included_in_attainment"] and row["reps_status"] != "unavailable"
    ]
    within = sum(1 for row in evaluated if row["reps_status"] == "within")
    targets = {(row["reps_target_low"], row["reps_target_high"]) for row in evaluated}
    common = next(iter(targets)) if len(targets) == 1 else (None, None)
    return {
        "evaluated_sets": len(evaluated),
        "within_target": within,
        "below_target": sum(1 for row in evaluated if row["reps_status"] == "below"),
        "above_target": sum(1 for row in evaluated if row["reps_status"] == "above"),
        "unavailable_sets": matched_count - len(evaluated),
        "attainment": _ratio(within, len(evaluated)),
        "mean_actual_reps": _mean(
            [float(row["reps_actual"]) for row in evaluated if row["reps_actual"] is not None]
        ),
        "common_target_low": common[0],
        "common_target_high": common[1],
        "unit": evaluated[0]["reps_unit"] if evaluated else None,
    }


def _load_summary(details: Sequence[Mapping[str, Any]], matched_count: int) -> dict[str, Any]:
    evaluated = [
        row for row in details
        if row["included_in_attainment"] and row["load_status"] != "unavailable"
    ]
    at_target = sum(1 for row in evaluated if row["load_status"] == "at_target")
    deviations = [
        abs(float(row["load_deviation_kg"])) for row in evaluated
        if row["load_deviation_kg"] is not None
    ]
    percentages = [
        float(row["load_deviation_pct"]) for row in evaluated
        if row["load_deviation_pct"] is not None
    ]
    targets = {row["load_target_kg"] for row in evaluated}
    return {
        "evaluated_sets": len(evaluated),
        "at_target": at_target,
        "above_target": sum(1 for row in evaluated if row["load_status"] == "above"),
        "below_target": sum(1 for row in evaluated if row["load_status"] == "below"),
        "unavailable_sets": matched_count - len(evaluated),
        "attainment": _ratio(at_target, len(evaluated)),
        "mean_absolute_deviation_kg": _mean(deviations),
        "max_absolute_deviation_kg": round(max(deviations), 2) if deviations else None,
        "mean_relative_deviation_pct": _mean(percentages),
        "common_target_kg": next(iter(targets)) if len(targets) == 1 else None,
        "unit": "kg",
    }


def _rir_summary(details: Sequence[Mapping[str, Any]], matched_count: int) -> dict[str, Any]:
    evaluated = [
        row for row in details
        if row["included_in_attainment"] and row["rir_status"] != "unavailable"
    ]
    at_target = sum(1 for row in evaluated if row["rir_status"] == "at_target")
    return {
        "evaluated_sets": len(evaluated),
        "at_target": at_target,
        "above_target": sum(1 for row in evaluated if row["rir_status"] == "above"),
        "below_target": sum(1 for row in evaluated if row["rir_status"] == "below"),
        "unavailable_sets": matched_count - len(evaluated),
        "attainment": _ratio(at_target, len(evaluated)),
        "mean_deviation": _mean(
            [float(row["rir_deviation"]) for row in evaluated
             if row["rir_deviation"] is not None]
        ),
        "tolerance": RIR_TOLERANCE,
        "sign": "positive = actual RIR above target (further from failure)",
    }


def _unmatched_reason(
    row: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    other_items: Sequence[Mapping[str, Any]],
    *,
    original_view: bool,
) -> str:
    value = row.get("prescription_item_index")
    if value is None:
        exercise = str(row.get("exercise_id"))
        count = sum(1 for item in items if str(item.get("exercise_id")) == exercise)
        return "ambiguous_attribution" if count > 1 else "unattributed"
    try:
        identity = int(value)
    except (TypeError, ValueError):
        return "invalid_identity"
    for position, item in enumerate(items):
        if item_identity(item, position) == identity:
            if str(item.get("exercise_id")) != str(row.get("exercise_id")):
                return "mismatched_exercise"
            return "unresolved_identity"
    for position, item in enumerate(other_items):
        if item_identity(item, position) == identity:
            return "added_in_final_plan" if original_view else "removed_from_final_plan"
    return "stale_identity"


def _unmatched_entry(row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "set_id": row.get("set_id"),
        "set_index": row.get("set_index"),
        "exercise_id": row.get("exercise_id"),
        "set_role": row.get("set_role"),
        "reps": row.get("reps"),
        "load_kg": row.get("load_kg"),
        "rir": row.get("rir"),
        "reason": reason,
    }


def _is_swap(
    original_item: Mapping[str, Any], final_item: Mapping[str, Any]
) -> bool:
    """Distinguish a real swap from a legacy removed-identity reuse.

    swap_exercise keeps the identity and sets substitution_for. add_exercise marks the new item
    added_during_workout. Older builds could reuse a removed identity for that addition, so
    provenance is required before calling the pair a swap.
    """
    if str(original_item.get("exercise_id")) == str(final_item.get("exercise_id")):
        return False
    return not (
        final_item.get("added_during_workout")
        and not final_item.get("substitution_for")
    )


def _analyse_view(
    *,
    label: str,
    items: Sequence[Mapping[str, Any]],
    other_items: Sequence[Mapping[str, Any]],
    working: Sequence[Mapping[str, Any]],
    warm_up_by_exercise: Mapping[str, int],
    bodyweight_kg: float | None,
    entities: Mapping[str, Any],
    original_view: bool,
) -> dict[str, Any]:
    if not items:
        unmatched = [
            _unmatched_entry(row, "no_prescription_items") for row in working
        ]
        return {
            "view": label,
            "status": "unavailable",
            "reason": "no_prescription_items",
            "prescribed_sets": 0,
            "performed_sets": len(working),
            "matched_sets": 0,
            "missing_sets": 0,
            "extra_sets": len(working),
            "unattributable_planned_sets": 0,
            "warm_up_sets_excluded": sum(warm_up_by_exercise.values()),
            "set_completion": _ratio(0, 0),
            "reps": _reps_summary([], 0),
            "load": _load_summary([], 0),
            "rir": _rir_summary([], 0),
            "exercises": [],
            "quality": {
                "unmatched_sets": len(working),
                "ambiguous_attribution": 0,
                "mismatched_attribution": 0,
                "stale_attribution": 0,
                "unattributable_items": 0,
                "unavailable_metrics": ["no_prescription_items"],
                "unmatched": unmatched,
            },
        }

    other_by_identity = _items_by_identity(other_items)
    exercise_occurrences: dict[str, int] = {}
    for value in items:
        exercise_id = str(value.get("exercise_id"))
        exercise_occurrences[exercise_id] = exercise_occurrences.get(exercise_id, 0) + 1
    assigned: set[int] = set()
    entries: list[dict[str, Any]] = []
    limitations: set[str] = set()
    if any(
        count > 1 and warm_up_by_exercise.get(exercise_id, 0)
        for exercise_id, count in exercise_occurrences.items()
    ):
        # Warm-up rows carry no plan-item identity, so a repeated exercise occurrence cannot
        # own them. The workout-level count stays authoritative.
        limitations.add("ambiguous_warm_up_attribution")
    reported: set[int] = set()
    planned_total = 0
    matched_total = 0
    missing_total = 0
    unattributable_planned = 0

    for position, item in enumerate(items):
        identity = item_identity(item, position)
        exercise_id = str(item.get("exercise_id"))
        entity = entities.get(exercise_id) or {}
        is_bodyweight = bool(entity.get("bodyweight_type"))
        is_time_based = bool(entity.get("time_based"))
        planned = max(0, int(item.get("sets") or 0))
        counterpart = other_by_identity.get(identity)
        swapped = counterpart is not None and _is_swap(item, counterpart)
        attributable = not (original_view and swapped)
        warm_up_count = (
            warm_up_by_exercise.get(exercise_id, 0)
            if exercise_occurrences[exercise_id] == 1 else None
        )
        base = {
            "plan_item_index": identity,
            "position": position,
            "exercise_id": exercise_id,
            "exercise_name": str(entity.get("display") or exercise_id),
            "planned_sets": planned,
            "attributable": attributable,
            "set_groups": [
                {"role": group.get("role"), "sets": group.get("sets"),
                 "load_kg": group.get("load_kg"), "reps_low": group.get("reps_low"),
                 "reps_high": group.get("reps_high"),
                 "rir_target": group.get("rir_target")}
                for group in (item.get("set_groups") or [])
                if isinstance(group, Mapping)
            ],
        }
        if not attributable:
            limitations.add("swapped_exercise")
            unattributable_planned += planned
            entries.append({
                **base,
                "status": "unavailable",
                "attribution": "unavailable",
                "prescribed_sets": 0,
                "performed_sets": 0,
                "matched_sets": 0,
                "missing_sets": 0,
                "extra_sets": 0,
                "unattributable_planned_sets": planned,
                "warm_up_sets_excluded": warm_up_count,
                "set_completion": _ratio(0, 0),
                "reps": _reps_summary([], 0),
                "load": _load_summary([], 0),
                "rir": _rir_summary([], 0),
                "sets": [],
                "limitations": ["swapped_exercise"],
            })
            continue

        matching = [
            row for row in working
            if row_plan_identity(items, row) == identity
            and str(row.get("exercise_id")) == exercise_id
        ]
        matching.sort(
            key=lambda row: (int(row.get("set_index") or 0), int(row.get("set_id") or 0))
        )
        matched_rows = matching[:planned]
        assigned.update(int(row["set_id"]) for row in matching)
        details = []
        for index, row in enumerate(matching):
            included = index < planned
            details.append(_set_metrics(
                row,
                item,
                bodyweight_kg=bodyweight_kg,
                is_bodyweight=is_bodyweight,
                is_time_based=is_time_based,
                included=included,
                matched=included,
            ))
        for row in details:
            limitations.update(row["limitations"])

        performed = len(matching)
        matched = len(matched_rows)
        missing = max(0, planned - performed)
        extra = max(0, performed - planned)
        planned_total += planned
        matched_total += matched
        missing_total += missing
        entries.append({
            **base,
            "status": (
                "missing" if performed == 0 and planned > 0 else
                "under" if matched < planned else
                "over" if performed > planned else "complete"
            ),
            "attribution": "matched",
            "prescribed_sets": planned,
            "performed_sets": performed,
            "matched_sets": matched,
            "missing_sets": missing,
            "extra_sets": extra,
            "unattributable_planned_sets": 0,
            "warm_up_sets_excluded": warm_up_count,
            "set_completion": _ratio(matched, planned),
            "reps": _reps_summary(details, matched),
            "load": _load_summary(details, matched),
            "rir": _rir_summary(details, matched),
            "sets": details,
            "limitations": sorted(set(
                limitation
                for row in details
                for limitation in row["limitations"]
            )),
        })

    unmatched = []
    for row in working:
        set_id = int(row["set_id"])
        if set_id in assigned or set_id in reported:
            continue
        reported.add(set_id)
        reason = _unmatched_reason(
            row, items, other_items, original_view=original_view
        )
        limitations.add(reason)
        unmatched.append(_unmatched_entry(row, reason))

    performed_total = len(working)
    extra_total = max(0, performed_total - matched_total)
    reasons = [entry["reason"] for entry in unmatched]
    return {
        "view": label,
        "status": "available",
        "prescribed_sets": planned_total,
        "performed_sets": performed_total,
        "matched_sets": matched_total,
        "missing_sets": missing_total,
        "extra_sets": extra_total,
        "unattributable_planned_sets": unattributable_planned,
        "warm_up_sets_excluded": sum(warm_up_by_exercise.values()),
        "set_completion": _ratio(matched_total, planned_total),
        "reps": _reps_summary(
            [detail for entry in entries for detail in entry["sets"]],
            matched_total,
        ),
        "load": _load_summary(
            [detail for entry in entries for detail in entry["sets"]],
            matched_total,
        ),
        "rir": _rir_summary(
            [detail for entry in entries for detail in entry["sets"]],
            matched_total,
        ),
        "exercises": entries,
        "quality": {
            "unmatched_sets": len(unmatched),
            "ambiguous_attribution": reasons.count("ambiguous_attribution"),
            "mismatched_attribution": reasons.count("mismatched_exercise"),
            "stale_attribution": sum(
                reasons.count(reason)
                for reason in ("stale_identity", "invalid_identity", "unresolved_identity")
            ),
            "added_exercise_sets": reasons.count("added_in_final_plan"),
            "removed_exercise_sets": reasons.count("removed_from_final_plan"),
            "unattributable_items": sum(1 for entry in entries if not entry["attributable"]),
            "unavailable_metrics": sorted(limitations),
            "unmatched": unmatched,
        },
    }


def _target_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "reps_low": item.get("reps_low"),
        "reps_high": item.get("reps_high"),
        "load_kg": item.get("load_kg"),
        "load_basis": item.get("load_basis"),
        "rir_target": item.get("rir_target"),
        "set_groups": json.dumps(item.get("set_groups") or [], sort_keys=True),
    }


def _changes(
    original: Sequence[Mapping[str, Any]], final: Sequence[Mapping[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    before = _items_by_identity(original)
    after = _items_by_identity(final)
    swapped: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    set_count: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for identity in sorted(before):
        old = before[identity]
        new = after.get(identity)
        if new is None:
            removed.append({
                "plan_item_index": identity,
                "exercise_id": old.get("exercise_id"),
                "sets": old.get("sets"),
            })
            continue
        if str(old.get("exercise_id")) != str(new.get("exercise_id")):
            if _is_swap(old, new):
                swapped.append({
                    "plan_item_index": identity,
                    "from_exercise_id": old.get("exercise_id"),
                    "to_exercise_id": new.get("exercise_id"),
                })
            else:
                # Legacy identity reuse: report removal and addition, not a swap.
                removed.append({
                    "plan_item_index": identity,
                    "exercise_id": old.get("exercise_id"),
                    "sets": old.get("sets"),
                    "identity_reused": True,
                })
                added.append({
                    "plan_item_index": identity,
                    "exercise_id": new.get("exercise_id"),
                    "sets": new.get("sets"),
                    "identity_reused": True,
                })
            continue
        if int(old.get("sets") or 0) != int(new.get("sets") or 0):
            set_count.append({
                "plan_item_index": identity,
                "exercise_id": old.get("exercise_id"),
                "from_sets": int(old.get("sets") or 0),
                "to_sets": int(new.get("sets") or 0),
            })
        # Set count and target dimensions are independent: an item can have both edited,
        # and the drill-down must report each rather than stopping at the first difference.
        old_fields = _target_fields(old)
        new_fields = _target_fields(new)
        changed = sorted(key for key in old_fields if old_fields[key] != new_fields[key])
        if changed:
            targets.append({
                "plan_item_index": identity,
                "exercise_id": old.get("exercise_id"),
                "fields": changed,
            })
    for identity in sorted(set(after) - set(before)):
        item = after[identity]
        added.append({
            "plan_item_index": identity,
            "exercise_id": item.get("exercise_id"),
            "sets": item.get("sets"),
        })
    return {
        "swapped": swapped,
        "added": added,
        "removed": removed,
        "set_count_changed": set_count,
        "targets_changed": targets,
    }


def _definitions() -> dict[str, Any]:
    return {
        "working_set": (
            "clean_set.is_working_set when materialised, otherwise the RIR 6 warm-up sentinel"
        ),
        "set_completion": "filled prescribed slots / attributable prescribed slots",
        "rir_tolerance": RIR_TOLERANCE,
        "load_tolerance": "plan rounding_increment, else default load increment",
    }


def analyse(workout: Mapping[str, Any]) -> dict[str, Any]:
    """Derive adherence for one workout snapshot without writing anything.

    The caller supplies the payload already returned by workout.get(): original_plan is the
    frozen issued snapshot, plan is the final in-workout plan, sets are the replayed actual
    sets, and readiness carries the bodyweight used for load-basis resolution.
    """
    original = _items(workout.get("original_plan") or {})
    final = _items(workout.get("plan") or {})
    modified = bool(workout.get("plan_modified"))
    rows = [row for row in (workout.get("sets") or []) if isinstance(row, Mapping)]
    entities = exercises.taxonomy().entities
    bodyweight_kg = _number((workout.get("readiness") or {}).get("bodyweight_kg"))

    working: list[Mapping[str, Any]] = []
    warm_up_by_exercise: dict[str, int] = {}
    ambiguous_status = 0
    sets_without_rir = 0
    for row in rows:
        kind = _classify_set(row)
        if kind == "warm_up":
            exercise_id = str(row.get("exercise_id"))
            warm_up_by_exercise[exercise_id] = warm_up_by_exercise.get(exercise_id, 0) + 1
        elif kind == "ambiguous":
            ambiguous_status += 1
        else:
            working.append(row)
        if _integer(row.get("rir")) is None:
            sets_without_rir += 1

    original_view = _analyse_view(
        label="original",
        items=original,
        other_items=final,
        working=working,
        warm_up_by_exercise=warm_up_by_exercise,
        bodyweight_kg=bodyweight_kg,
        entities=entities,
        original_view=True,
    )
    final_view = _analyse_view(
        label="final_plan",
        items=final,
        other_items=original,
        working=working,
        warm_up_by_exercise=warm_up_by_exercise,
        bodyweight_kg=bodyweight_kg,
        entities=entities,
        original_view=False,
    )

    status = "available" if (original or final) else "unavailable"
    payload: dict[str, Any] = {
        "version": VERSION,
        "status": status,
        "reason": None if status == "available" else "no_prescription_items",
        "original": original_view,
        "final_plan": final_view,
        "changes": _changes(original, final) if modified else {
            "swapped": [],
            "added": [],
            "removed": [],
            "set_count_changed": [],
            "targets_changed": [],
        },
        "quality": {
            "plan_modified": modified,
            "legacy_plan_without_order_index": any(
                "order_index" not in item for item in [*original, *final]
            ),
            "warm_up_sets_excluded": sum(warm_up_by_exercise.values()),
            "ambiguous_status_sets": ambiguous_status,
            "sets_without_rir": sets_without_rir,
            "unmatched_sets": {
                "original": original_view["quality"]["unmatched_sets"],
                "final_plan": final_view["quality"]["unmatched_sets"],
            },
            "ambiguous_attribution": {
                "original": original_view["quality"]["ambiguous_attribution"],
                "final_plan": final_view["quality"]["ambiguous_attribution"],
            },
            "unattributable_planned_sets": {
                "original": original_view["unattributable_planned_sets"],
                "final_plan": final_view["unattributable_planned_sets"],
            },
            "unavailable_metrics": sorted({
                *original_view["quality"]["unavailable_metrics"],
                *final_view["quality"]["unavailable_metrics"],
            }),
        },
        "definitions": _definitions(),
    }
    return payload


def unavailable(reason: str) -> dict[str, Any]:
    """Return the explicit unavailable shape for a session with no usable prescription.

    History detail must always carry the key so a consumer can render "not available" without
    guessing whether the field is absent, zero or not applicable.
    """
    original_view = _analyse_view(
        label="original",
        items=[],
        other_items=[],
        working=[],
        warm_up_by_exercise={},
        bodyweight_kg=None,
        entities={},
        original_view=True,
    )
    final_view = _analyse_view(
        label="final_plan",
        items=[],
        other_items=[],
        working=[],
        warm_up_by_exercise={},
        bodyweight_kg=None,
        entities={},
        original_view=False,
    )
    for view in (original_view, final_view):
        view["reason"] = reason
        view["quality"]["unavailable_metrics"] = [reason]
    return {
        "version": VERSION,
        "status": "unavailable",
        "reason": reason,
        "original": original_view,
        "final_plan": final_view,
        "changes": _changes([], []),
        "quality": {
            "plan_modified": False,
            "legacy_plan_without_order_index": False,
            "warm_up_sets_excluded": 0,
            "ambiguous_status_sets": 0,
            "sets_without_rir": 0,
            "unmatched_sets": {"original": 0, "final_plan": 0},
            "ambiguous_attribution": {"original": 0, "final_plan": 0},
            "unattributable_planned_sets": {"original": 0, "final_plan": 0},
            "unavailable_metrics": [reason],
        },
        "definitions": _definitions(),
    }
