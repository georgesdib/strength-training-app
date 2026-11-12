"""Read-only VBT target applicability and target-versus-actual analysis.

The server owns the arithmetic. This module resolves the target frozen into the workout plan,
applies explicit comparability rules, computes per-set residuals and aggregates them per
exercise. It never writes, never changes a prescription and never combines exercises into a
single score.

The target is conditional on rep count and RIR band, not on load. Actual load and load basis are
reported as context; only a known/compatible load basis enters the comparability decision.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from strength_coach.domain.plan_identity import item_identity, row_plan_identity
from strength_coach.utils import exercises as exercises_mod
from strength_coach.utils import stats

_REASON_TEXT = {
    "no_target": "No trustworthy VBT target was issued for this exercise.",
    "legacy_target": "A legacy target has no calibration band, rep count or calibration id.",
    "unattributed_set": "The set has no stable prescription-item attribution.",
    "exercise_mismatch": "The set's exercise does not match the attributed prescription item.",
    "missing_velocity": "No actual mean velocity was recorded.",
    "invalid_velocity": "The actual mean velocity is not positive and finite.",
    "warm_up": "Warm-up sets are not target comparisons.",
    "rep_mismatch": "The actual rep count differs from the target's calibration rep count.",
    "group_rep_mismatch": "The selected set group's rep count differs from the target's rep count.",
    "ambiguous_set_role": "The set group could not be resolved; choose a set role.",
    "actual_rir_missing": "Actual RIR is missing, so effort comparability cannot be established.",
    "actual_rir_outside_band": "Actual RIR is outside the target's calibration band.",
    "load_basis_unknown": "The actual or prescribed load basis is unknown.",
    "load_basis_mismatch": "The actual and prescribed load bases are not comparable.",
    "time_based": "Time-based movements are not scored against a velocity target.",
    "data_quality_flag": "The set is flagged for a data-quality problem.",
}

_HARD_REASONS = {
    "legacy_target", "unattributed_set", "exercise_mismatch", "missing_velocity",
    "invalid_velocity", "warm_up", "rep_mismatch", "group_rep_mismatch",
    "ambiguous_set_role", "actual_rir_missing", "actual_rir_outside_band",
    "load_basis_unknown", "load_basis_mismatch", "time_based", "data_quality_flag",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _flags(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return [value]
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return []


def _entity(exercise_id: Any) -> Mapping[str, Any]:
    return exercises_mod.taxonomy().entities.get(str(exercise_id)) or {}


def _load_basis_compatible(actual: str, prescribed: str) -> bool:
    if actual in ("", "unknown") or prescribed in ("", "unknown"):
        return False
    if actual == "bodyweight_total" or prescribed == "bodyweight_total":
        return actual == prescribed == "bodyweight_total"
    return actual in {"external", "added"} and prescribed in {"external", "added"}


def _target_for_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    vbt = item.get("vbt")
    if isinstance(vbt, Mapping):
        target = _number(vbt.get("target_mps"))
        if target is None or target <= 0:
            return None
        return {
            "target_mps": target,
            "low_mps": _number(vbt.get("low_mps")),
            "high_mps": _number(vbt.get("high_mps")),
            "rep_count": _integer(vbt.get("rep_count")),
            "rir_low": _integer(vbt.get("rir_low")),
            "rir_high": _integer(vbt.get("rir_high")),
            "scope": vbt.get("scope"),
            "family": vbt.get("family"),
            "n_sets": _integer(vbt.get("n_sets")),
            "n_sessions": _integer(vbt.get("n_sessions")),
            "method_version": vbt.get("method_version"),
            "calibration_id": vbt.get("calibration_id"),
            "source": vbt.get("source"),
            "metadata": "complete",
        }
    legacy = _number(item.get("velocity_target"))
    if legacy is not None and legacy > 0:
        return {
            "target_mps": legacy,
            "low_mps": None,
            "high_mps": None,
            "rep_count": _integer(item.get("reps_low")),
            "rir_low": None,
            "rir_high": None,
            "scope": None,
            "family": None,
            "n_sets": None,
            "n_sessions": None,
            "method_version": None,
            "calibration_id": None,
            "source": "legacy",
            "metadata": "legacy",
        }
    return None


def _group_for_set(item: Mapping[str, Any], set_role: Any) -> tuple[Mapping[str, Any] | None, str | None]:
    groups = [group for group in (item.get("set_groups") or []) if isinstance(group, Mapping)]
    if not groups:
        return None, None
    if set_role in (None, ""):
        return (groups[0], None) if len(groups) == 1 else (None, "ambiguous_set_role")
    for group in groups:
        if group.get("role") == set_role:
            return group, None
    return None, "ambiguous_set_role"


def _base_result(
    row: Mapping[str, Any],
    *,
    reasons: Sequence[str],
    target: Mapping[str, Any] | None = None,
    target_source: str | None = None,
    actual_velocity: float | None = None,
    velocity_source: str | None = None,
    actual_load_basis: str | None = None,
    prescribed_load_basis: str | None = None,
    actual_rir: int | None = None,
    delta: float | None = None,
    delta_pct: float | None = None,
    within: bool | None = None,
    comparable: bool = False,
    extra_set: bool = False,
    flags: Sequence[str] = (),
    prescribed_rir: int | None = None,
) -> dict[str, Any]:
    target = target or {}
    return {
        "set_id": row.get("set_id"),
        "set_index": row.get("set_index"),
        "exercise_id": row.get("exercise_id"),
        "session_id": row.get("session_id"),
        "set_role": row.get("set_role"),
        "reps": _integer(row.get("reps")),
        "load_kg": _number(row.get("load_kg")),
        "load_basis": actual_load_basis or prescribed_load_basis,
        "prescribed_load_basis": prescribed_load_basis,
        "actual_velocity_mps": None if actual_velocity is None else round(actual_velocity, 3),
        "velocity_source": velocity_source,
        "target_mps": target.get("target_mps"),
        "low_mps": target.get("low_mps"),
        "high_mps": target.get("high_mps"),
        "delta_mps": delta,
        "delta_pct": delta_pct,
        "abs_error_mps": None if delta is None else round(abs(delta), 3),
        "within_calibration_band": within,
        "comparable": comparable,
        "reasons": sorted(set(reasons)),
        "actual_rir": actual_rir,
        "prescribed_rir": prescribed_rir,
        "target_rir_low": target.get("rir_low"),
        "target_rir_high": target.get("rir_high"),
        "target_rep_count": target.get("rep_count"),
        "scope": target.get("scope"),
        "family": target.get("family"),
        "n_sets": target.get("n_sets"),
        "n_sessions": target.get("n_sessions"),
        "method_version": target.get("method_version"),
        "calibration_id": target.get("calibration_id"),
        "target_metadata": target.get("metadata") if target else "missing",
        "target_source": target_source,
        "extra_set": extra_set,
        "flags": sorted(set(flags)),
        "target": dict(target) if target else None,
    }


def _missing_result(row: Mapping[str, Any], reasons: Sequence[str], target_source: str | None = None) -> dict[str, Any]:
    return _base_result(row, reasons=reasons, target_source=target_source)


def _compare_item(
    item: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    target_source: str,
    actual_load_basis: str | None = None,
    velocity_override: float | None = None,
    flags: Sequence[str] = (),
) -> dict[str, Any]:
    reasons: list[str] = []
    target = _target_for_item(item)
    prescribed_basis = str(item.get("load_basis") or "unknown")
    actual_basis = actual_load_basis if actual_load_basis is not None else prescribed_basis
    if not _load_basis_compatible(actual_basis, prescribed_basis):
        reasons.append(
            "load_basis_mismatch"
            if actual_basis not in ("", "unknown") and prescribed_basis not in ("", "unknown")
            else "load_basis_unknown"
        )
    entity = _entity(row.get("exercise_id"))
    if entity.get("time_based"):
        reasons.append("time_based")
    if "REPS_TYPO" in flags:
        reasons.append("data_quality_flag")
    if "LOAD_BASIS_UNKNOWN" in flags and "load_basis_unknown" not in reasons:
        reasons.append("load_basis_unknown")
    actual = velocity_override
    velocity_source = "override" if actual is not None else "stored"
    if actual is None:
        actual = _number(row.get("velocity_mps", row.get("velocity")))
    if actual is None:
        reasons.append("missing_velocity")
    elif actual <= 0:
        reasons.append("invalid_velocity")
    actual_rir = _integer(row.get("rir"))
    working = _integer(row.get("is_working_set"))
    if working == 0 or actual_rir == 6:
        reasons.append("warm_up")
    if target is None:
        reasons.append("legacy_target" if item.get("velocity_target") is not None else "no_target")
        return _base_result(
            row, reasons=reasons, target_source=target_source,
            actual_velocity=actual, velocity_source=velocity_source,
            actual_load_basis=actual_basis, prescribed_load_basis=prescribed_basis,
            actual_rir=actual_rir, flags=flags,
        )
    if target.get("metadata") == "legacy":
        reasons.append("legacy_target")
    reps = _integer(row.get("reps"))
    if reps is None or (target.get("rep_count") is not None and reps != target["rep_count"]):
        reasons.append("rep_mismatch")
    group, group_error = _group_for_set(item, row.get("set_role"))
    if group_error:
        reasons.append(group_error)
    elif (
        group is not None
        and target.get("rep_count") is not None
        and _integer(group.get("reps_low")) != target["rep_count"]
    ):
        reasons.append("group_rep_mismatch")
    prescribed_rir = _integer((group if group is not None else item).get("rir_target"))
    if actual_rir is None:
        reasons.append("actual_rir_missing")
    elif (
        target.get("rir_low") is not None
        and target.get("rir_high") is not None
        and not int(target["rir_low"]) <= actual_rir <= int(target["rir_high"])
    ):
        reasons.append("actual_rir_outside_band")
    delta = None if actual is None else round(actual - target["target_mps"], 3)
    delta_pct = (
        round((actual - target["target_mps"]) / target["target_mps"] * 100, 2)
        if actual is not None and target["target_mps"] > 0 else None
    )
    low, high = target.get("low_mps"), target.get("high_mps")
    within = bool(low <= actual <= high) if actual is not None and low is not None and high is not None else None
    extra_set = bool(
        _integer(row.get("set_index")) is not None
        and _integer(item.get("sets")) is not None
        and int(row["set_index"]) > int(item["sets"])
    )
    comparable = not any(reason in _HARD_REASONS for reason in reasons)
    return _base_result(
        row, reasons=reasons, target=target, target_source=target_source,
        actual_velocity=actual, velocity_source=velocity_source,
        actual_load_basis=actual_basis, prescribed_load_basis=prescribed_basis,
        actual_rir=actual_rir, delta=delta, delta_pct=delta_pct, within=within,
        comparable=comparable, extra_set=extra_set, flags=flags,
        prescribed_rir=prescribed_rir,
    )


def compare_set(items: Sequence[Mapping[str, Any]], row: Mapping[str, Any]) -> dict[str, Any]:
    """Compare one active-workout set with the target on its stable plan item."""
    reasons: list[str] = []
    identity = row_plan_identity(items, row)
    item = None
    if identity is not None:
        for position, candidate in enumerate(items):
            if item_identity(candidate, position) == identity:
                item = candidate
                break
    else:
        raw_identity = row.get("prescription_item_index")
        if raw_identity is not None:
            try:
                index = int(raw_identity)
            except (TypeError, ValueError):
                index = None
            if index is not None:
                for position, candidate in enumerate(items):
                    if item_identity(candidate, position) == index:
                        reasons.append("exercise_mismatch")
                        break
        if not reasons:
            reasons.append("unattributed_set")
    if item is None:
        return _missing_result(row, reasons, target_source="final_plan")
    return _compare_item(item, row, target_source="final_plan")


def _item_at(items: Sequence[Mapping[str, Any]], identity: int) -> Mapping[str, Any] | None:
    for position, item in enumerate(items):
        if item_identity(item, position) == identity:
            return item
    return None


def _resolve_completed_item(
    final_items: Sequence[Mapping[str, Any]],
    original_items: Sequence[Mapping[str, Any]],
    row: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str | None, list[str]]:
    """Resolve the plan item whose target was actually issued to this set.

    A final-plan item is preferred. A removed item falls back to the original plan only when the
    identity and exercise still match. A swapped item is never given the old target.
    """
    final_identity = row_plan_identity(final_items, row)
    if final_identity is not None:
        item = _item_at(final_items, final_identity)
        if item is not None:
            return item, "final_plan", []
    raw = row.get("prescription_item_index")
    if raw is None:
        return None, None, ["unattributed_set"]
    try:
        identity = int(raw)
    except (TypeError, ValueError):
        return None, None, ["unattributed_set"]
    original_identity = row_plan_identity(original_items, row)
    final_item = _item_at(final_items, identity)
    if original_identity is not None:
        if final_item is not None and str(final_item.get("exercise_id")) != str(row.get("exercise_id")):
            return None, None, ["exercise_mismatch"]
        return _item_at(original_items, original_identity), "original_plan", []
    for collection in (final_items, original_items):
        item = _item_at(collection, identity)
        if item is not None and str(item.get("exercise_id")) != str(row.get("exercise_id")):
            return None, None, ["exercise_mismatch"]
    return None, None, ["unattributed_set"]


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": int(numerator),
        "denominator": int(denominator),
        "ratio": round(numerator / denominator, 4) if denominator else None,
    }


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _median(values: Sequence[float]) -> float | None:
    value = stats.median(values)
    return None if value != value else round(float(value), 3)


def _exercise_summary(exercise_id: str, comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    comparable = [row for row in comparisons if row["comparable"]]
    deltas = [float(row["delta_mps"]) for row in comparable if row["delta_mps"] is not None]
    relative = [float(row["delta_pct"]) for row in comparable if row["delta_pct"] is not None]
    absolute_relative = [abs(value) for value in relative]
    band = [row for row in comparable if row["within_calibration_band"] is not None]
    within = sum(1 for row in band if row["within_calibration_band"])
    above = sum(1 for value in deltas if value > 0)
    below = sum(1 for value in deltas if value < 0)
    at = sum(1 for value in deltas if value == 0)
    targets: list[dict[str, Any]] = []
    seen = set()
    for row in comparisons:
        target = row.get("target")
        if not target:
            continue
        key = (
            target.get("calibration_id"), target.get("scope"), target.get("family"),
            target.get("rep_count"), target.get("target_mps"),
        )
        if key in seen:
            continue
        seen.add(key)
        targets.append(dict(target))
    actual_rirs = [row["actual_rir"] for row in comparable if row["actual_rir"] is not None]
    prescribed_rirs = [row["prescribed_rir"] for row in comparable if row["prescribed_rir"] is not None]
    reason_counts = Counter(
        reason for row in comparisons for reason in row.get("reasons") or []
    )
    return {
        "exercise_id": exercise_id,
        "exercise_name": comparisons[0].get("exercise_name") if comparisons else exercise_id,
        "sets": len(comparisons),
        "comparable_sets": len(comparable),
        "excluded_sets": len(comparisons) - len(comparable),
        "target_sets": sum(1 for row in comparisons if row.get("target_mps") is not None),
        "extra_sets": sum(1 for row in comparisons if row.get("extra_set")),
        "mean_signed_delta_mps": _mean(deltas),
        "median_signed_delta_mps": _median(deltas),
        "mean_absolute_error_mps": _mean([abs(value) for value in deltas]),
        "median_absolute_error_mps": _median([abs(value) for value in deltas]),
        "mean_relative_delta_pct": _mean(relative),
        "median_relative_delta_pct": _median(relative),
        "mean_absolute_relative_error_pct": _mean(absolute_relative),
        "median_absolute_relative_error_pct": _median(absolute_relative),
        "within_calibration_band": _ratio(within, len(band)),
        "above_target": _ratio(above, len(deltas)),
        "below_target": _ratio(below, len(deltas)),
        "at_target": _ratio(at, len(deltas)),
        "mean_actual_rir": _mean([float(value) for value in actual_rirs]),
        "mean_prescribed_rir": _mean([float(value) for value in prescribed_rirs]),
        "target": targets[0] if len(targets) == 1 else None,
        "targets": targets,
        "target_sources": sorted({row["target_source"] for row in comparisons if row.get("target_source")}),
        "comparable_set_ids": [row.get("set_id") for row in comparable],
        "excluded_set_ids": [row.get("set_id") for row in comparisons if not row["comparable"]],
        "reasons": dict(sorted(reason_counts.items())),
    }


def _quality(rows: Sequence[Mapping[str, Any]], comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reasons = Counter(reason for row in comparisons for reason in row.get("reasons") or [])
    metadata = Counter(row.get("target_metadata") or "missing" for row in comparisons)
    return {
        "logged_sets": len(rows),
        "working_sets": sum(
            1 for row in rows
            if not (row.get("is_working_set") == 0 or row.get("rir") == 6)
        ),
        "sets_with_velocity": sum(1 for row in comparisons if row["actual_velocity_mps"] is not None),
        "sets_with_valid_velocity": sum(
            1 for row in comparisons
            if row["actual_velocity_mps"] is not None and row["actual_velocity_mps"] > 0
        ),
        "target_sets": sum(1 for row in comparisons if row.get("target_mps") is not None),
        "comparable_sets": sum(1 for row in comparisons if row["comparable"]),
        "excluded_sets": sum(1 for row in comparisons if not row["comparable"]),
        "extra_sets": sum(1 for row in comparisons if row["extra_set"]),
        "target_metadata": dict(sorted(metadata.items())),
        "reasons": dict(sorted(reasons.items())),
    }


def completed_sets(
    data: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    overrides: Mapping[int, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Per-set comparisons for a completed workout, without the exercise aggregation."""
    final_items = list((data.get("plan") or {}).get("items") or [])
    original_items = list((data.get("original_plan") or {}).get("items") or [])
    overrides = overrides or {}
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        item, source, reasons = _resolve_completed_item(final_items, original_items, row)
        if item is None:
            comparison = _missing_result(row, reasons, target_source=source)
        else:
            override = overrides.get(int(row["set_id"])) if row.get("set_id") is not None else None
            comparison = _compare_item(
                item,
                row,
                target_source=source or "final_plan",
                actual_load_basis=row.get("load_basis"),
                velocity_override=_number(override.get("velocity_mps")) if override else None,
                flags=_flags(row.get("flags")),
            )
        comparison["workout_id"] = data.get("workout_id")
        comparison["exercise_name"] = str(_entity(row.get("exercise_id")).get("display") or row.get("exercise_id"))
        comparisons.append(comparison)
    return comparisons


def completed(
    data: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    overrides: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyse a completed workout from clean_set leaf rows and its frozen plans."""
    final_items = list((data.get("plan") or {}).get("items") or [])
    original_items = list((data.get("original_plan") or {}).get("items") or [])
    comparisons = completed_sets(data, rows, overrides=overrides)
    has_target = any(row.get("target_mps") is not None for row in comparisons)
    exercise_ids = sorted({str(row.get("exercise_id")) for row in comparisons})
    exercises = [
        _exercise_summary(
            exercise_id,
            [row for row in comparisons if str(row.get("exercise_id")) == exercise_id],
        )
        for exercise_id in exercise_ids
    ]
    quality = _quality(rows, comparisons)
    final_identities = {item_identity(item, position) for position, item in enumerate(final_items)}
    quality["target_items"] = sum(
        1 for position, item in enumerate(final_items)
        if _target_for_item(item) is not None
    ) + sum(
        1 for position, item in enumerate(original_items)
        if item_identity(item, position) not in final_identities
        and _target_for_item(item) is not None
    )
    return {
        "status": "available" if has_target else "unavailable",
        "reason": None if has_target else "no_vbt_target_issued",
        "sets": comparisons,
        "exercises": exercises,
        "quality": quality,
    }


def active_feedback(data: Mapping[str, Any]) -> dict[str, Any]:
    """Comparisons for an in-progress workout from the live workout_set rows."""
    items = list((data.get("plan") or {}).get("items") or [])
    rows = list(data.get("sets") or [])
    comparisons = [compare_set(items, row) for row in rows]
    for comparison in comparisons:
        comparison["workout_id"] = data.get("workout_id")
        comparison["exercise_name"] = str(
            _entity(comparison.get("exercise_id")).get("display") or comparison.get("exercise_id")
        )
    targets = sum(1 for item in items if _target_for_item(item) is not None)
    quality = _quality(rows, comparisons)
    quality["target_items"] = targets
    return {
        "status": "available" if targets else "unavailable",
        "reason": None if targets else "no_vbt_target_issued",
        "sets": comparisons,
        "exercises": [
            _exercise_summary(
                exercise_id,
                [row for row in comparisons if str(row.get("exercise_id")) == exercise_id],
            )
            for exercise_id in sorted({str(row.get("exercise_id")) for row in comparisons})
        ],
        "quality": quality,
    }


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "sets": [],
        "exercises": [],
        "quality": {
            "logged_sets": 0, "working_sets": 0, "sets_with_velocity": 0,
            "sets_with_valid_velocity": 0, "target_sets": 0, "comparable_sets": 0,
            "excluded_sets": 0, "extra_sets": 0, "target_items": 0,
            "target_metadata": {}, "reasons": {},
        },
    }
