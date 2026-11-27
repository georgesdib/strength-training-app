"""Read-only VBT target applicability and target-versus-actual analysis.

The server owns the arithmetic. This module resolves the target frozen into the workout plan,
applies explicit comparability rules, computes per-set residuals and aggregates them per
exercise. It never writes, never changes a prescription and never combines exercises into a
single score.

A frozen target is either a per-rep line or pooled model evaluated at the prescribed load,
reps and RIR, or a flat median band. A prescription with a rep range freezes one target per
allowed rep count, so the comparison picks the target measured at the reps actually used
(DEC-VBT-11); the frozen vector is plan provenance and is not repeated in the per-set result.
The comparison evaluates the line/pooled model at the load actually used; an actual load or rep
count outside the fitted range is an extrapolation and not comparable, and a known/compatible
load basis still gates comparability.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from strength_coach.domain.plan_identity import item_identity, row_plan_identity
from strength_coach.features import set_matching
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
    "rep_mismatch": "No calibrated target exists at the rep count this set used.",
    "rep_outside_prescription": "The set's rep count is outside the range the prescription allowed.",
    "group_rep_mismatch": "The selected set group's rep range is not covered by the target.",
    "ambiguous_group": "The set group could not be resolved from the plan's order.",
    "actual_rir_missing": "Actual RIR is missing, so effort comparability cannot be established.",
    "actual_rir_outside_band": "Actual RIR is outside the target's calibration band.",
    "load_basis_unknown": "The actual or prescribed load basis is unknown.",
    "load_basis_mismatch": "The actual and prescribed load bases are not comparable.",
    "time_based": "Time-based movements are not scored against a velocity target.",
    "data_quality_flag": "The set is flagged for a data-quality problem.",
    "load_outside_fitted_range": "The actual load is outside the calibrated load range; the line would be an extrapolation.",
    "rep_outside_fitted_range": "The actual rep count is outside the rep range the pooled model was fitted on; the target is an extrapolation.",
}

_HARD_REASONS = {
    "legacy_target", "unattributed_set", "exercise_mismatch", "missing_velocity",
    "invalid_velocity", "warm_up", "rep_mismatch", "rep_outside_prescription",
    "group_rep_mismatch",
    "ambiguous_group", "actual_rir_missing", "actual_rir_outside_band",
    "load_basis_unknown", "load_basis_mismatch", "time_based", "data_quality_flag",
    "load_outside_fitted_range", "rep_outside_fitted_range",
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


def _plan_target_note(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """The plan's own record of what happened when targets were attached.

    The workout-level reason is necessarily coarse ("no target anywhere"), so the frozen plan
    note is passed through verbatim: it names the rule that skipped the session, the calibration
    shortfall, or the targets that were issued. It is provenance only; nothing here is recomputed.
    """
    plan = data.get("plan")
    if not isinstance(plan, Mapping):
        return None
    notes = plan.get("notes")
    if not isinstance(notes, Mapping):
        return None
    note = notes.get("vbt")
    return dict(note) if isinstance(note, Mapping) else None


def _load_basis_compatible(actual: str, prescribed: str) -> bool:
    if actual in ("", "unknown") or prescribed in ("", "unknown"):
        return False
    if actual == "bodyweight_total" or prescribed == "bodyweight_total":
        return actual == prescribed == "bodyweight_total"
    return actual in {"external", "added"} and prescribed in {"external", "added"}


def _structured_target(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """One frozen target, normalised. None when it carries no usable velocity."""
    target = _number(raw.get("target_mps"))
    if target is None or target <= 0:
        return None
    return {
        "target_mps": target,
        "low_mps": _number(raw.get("low_mps")),
        "high_mps": _number(raw.get("high_mps")),
        "rep_count": _integer(raw.get("rep_count")),
        "rir_low": _integer(raw.get("rir_low")),
        "rir_high": _integer(raw.get("rir_high")),
        "scope": raw.get("scope"),
        "family": raw.get("family"),
        "n_sets": _integer(raw.get("n_sets")),
        "n_sessions": _integer(raw.get("n_sessions")),
        "method_version": raw.get("method_version"),
        "calibration_id": raw.get("calibration_id"),
        "source": raw.get("source"),
        "fit_method": raw.get("fit_method") or "median",
        "velocity_slope": _number(raw.get("velocity_slope")),
        "velocity_intercept": _number(raw.get("velocity_intercept")),
        "velocity_rir_coef": _number(raw.get("velocity_rir_coef")),
        "velocity_residual_mad": _number(raw.get("velocity_residual_mad")),
        "velocity_rep_coef": _number(raw.get("velocity_rep_coef")),
        "reps_min": _integer(raw.get("reps_min")),
        "reps_max": _integer(raw.get("reps_max")),
        "load_min": _number(raw.get("load_min")),
        "load_max": _number(raw.get("load_max")),
        "metadata": "complete",
    }


def _target_for_item(item: Mapping[str, Any]) -> dict[str, Any] | None:
    vbt = item.get("vbt")
    if isinstance(vbt, Mapping):
        target = _structured_target(vbt)
        if target is None:
            return None
        # The frozen plan also carries the target for the other rep counts the prescription
        # allowed, each resolved from its own calibration (DEC-VBT-11). A broken entry is
        # dropped rather than repaired: a comparison needs a number that was actually issued.
        entries = vbt.get("per_rep")
        per_rep: list[dict[str, Any]] = []
        if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
            for raw in entries:
                if isinstance(raw, Mapping):
                    entry = _structured_target(raw)
                    if entry is not None:
                        per_rep.append(entry)
        target["per_rep"] = tuple(per_rep)
        return target
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
            "fit_method": "median",
            "velocity_slope": None,
            "velocity_intercept": None,
            "velocity_rir_coef": None,
            "velocity_residual_mad": None,
            "velocity_rep_coef": None,
            "reps_min": None,
            "reps_max": None,
            "load_min": None,
            "load_max": None,
            "metadata": "legacy",
        }
    return None


def _group_for_set(
    item: Mapping[str, Any], ordinal: int
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Resolve the target group by working-set order; no legacy role is read."""
    return set_matching.group_for_ordinal(item, ordinal), None


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
    expected: float | None = None,
    basis: str = "planned",
    extrapolated: bool = False,
) -> dict[str, Any]:
    target = target or {}
    return {
        "set_id": row.get("set_id"),
        "set_index": row.get("set_index"),
        "exercise_id": row.get("exercise_id"),
        "session_id": row.get("session_id"),
        "reps": _integer(row.get("reps")),
        "load_kg": _number(row.get("load_kg")),
        "load_basis": actual_load_basis or prescribed_load_basis,
        "prescribed_load_basis": prescribed_load_basis,
        "actual_velocity_mps": None if actual_velocity is None else round(actual_velocity, 3),
        "velocity_source": velocity_source,
        "target_mps": target.get("target_mps"),
        "low_mps": target.get("low_mps"),
        "high_mps": target.get("high_mps"),
        "expected_mps": expected,
        "comparison_basis": basis,
        "load_conditional": expected is not None,
        "extrapolated": extrapolated,
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
        "target": (
            {key: value for key, value in target.items() if key != "per_rep"}
            if target else None
        ),
    }


def _missing_result(row: Mapping[str, Any], reasons: Sequence[str], target_source: str | None = None) -> dict[str, Any]:
    return _base_result(row, reasons=reasons, target_source=target_source)


def _reevaluable_at(target: Mapping[str, Any], reps: int) -> bool:
    """A pooled target carries a rep term, so it can be evaluated at another fitted rep count.

    A line and a median band were fitted at one rep count and have no rep term; evaluating
    either at another rep count would be a guess, so they stay specific to their own count.
    """
    if str(target.get("fit_method") or "").split("_")[0] != "pooled":
        return False
    if target.get("velocity_rep_coef") is None:
        return False
    low, high = target.get("reps_min"), target.get("reps_max")
    if low is None or high is None:
        return False
    return int(low) <= int(reps) <= int(high)


def _target_for_rep(
    target: Mapping[str, Any] | None, reps: int
) -> Mapping[str, Any] | None:
    """The target that applies at one rep count: its own entry, the frozen target, or a
    pooled model evaluated there."""
    if target is None:
        return None
    for entry in target.get("per_rep") or ():
        if entry.get("rep_count") == reps:
            return entry
    if target.get("rep_count") == reps:
        return target
    if _reevaluable_at(target, reps):
        return target
    return None


def _covers_span(target: Mapping[str, Any] | None, span: Mapping[str, Any]) -> bool:
    """Whether the target resolves at least one rep count the span prescribes."""
    low = _integer(span.get("reps_low"))
    high = _integer(span.get("reps_high"))
    if low is None or high is None:
        return True
    return any(_target_for_rep(target, reps) is not None for reps in range(low, high + 1))


def _target_for_reps(
    item: Mapping[str, Any],
    target: Mapping[str, Any] | None,
    reps: int | None,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Resolve the target for the rep count this set actually used.

    A prescription with a rep range freezes one target per rep count, so a 5-rep set is
    judged against the rep-5 target rather than discarded against the rep-3 one
    (DEC-VBT-11). A rep count outside the prescribed range, or one with no target of its
    own, is reported instead of being compared with a different rep count's number.
    """
    if target is None:
        return target, None
    if reps is None:
        return target, "rep_mismatch"
    low = _integer(item.get("reps_low"))
    high = _integer(item.get("reps_high"))
    if low is not None and high is not None and not low <= reps <= high:
        return target, "rep_outside_prescription"
    selected = _target_for_rep(target, reps)
    if selected is None:
        return target, "rep_mismatch"
    return selected, None


def _compare_item(
    item: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    target_source: str,
    actual_load_basis: str | None = None,
    velocity_override: float | None = None,
    flags: Sequence[str] = (),
    ordinal: int = 0,
) -> dict[str, Any]:
    reasons: list[str] = []
    if row.get("substitutes_plan_item_index") is not None:
        return _missing_result(
            row,
            ["substituted_exercise_target_unavailable"],
            target_source=target_source,
        )
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
    frozen = target
    target, rep_reason = _target_for_reps(item, frozen, reps)
    if rep_reason is not None:
        reasons.append(rep_reason)
    group, group_error = _group_for_set(item, ordinal)
    if group_error:
        reasons.append(group_error)
    elif group is not None and not _covers_span(frozen, group):
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
    # A line target is evaluated at the load and RIR actually used; the frozen planned
    # target stays visible as target_mps. Outside the fitted range it is an extrapolation,
    # so the set is reported but not comparable.
    load = _number(row.get("load_kg"))
    expected: float | None = None
    basis = "planned"
    extrapolated = False
    low, high = target.get("low_mps"), target.get("high_mps")
    # A frozen "pooled_extrapolated"/"line_extrapolated" basis names the same model, not
    # another one: the coefficients are unchanged, so the evaluation still uses the actual
    # load and RIR and re-decides the fitted ranges for this set.
    method = str(target.get("fit_method") or "median").split("_")[0]
    if (
        method in ("line", "pooled")
        and target.get("velocity_slope") is not None
        and target.get("velocity_intercept") is not None
        and load is not None
    ):
        rir_for_line = actual_rir if actual_rir is not None else prescribed_rir
        if rir_for_line is None and target.get("rir_low") is not None:
            high_rir = target.get("rir_high")
            rir_for_line = (
                int(target["rir_low"]) if high_rir is None
                else (int(target["rir_low"]) + int(high_rir)) / 2
            )
        reps_for_line = _integer(row.get("reps"))
        if reps_for_line is None:
            reps_for_line = target.get("rep_count")
        if (
            rir_for_line is not None and 0 <= float(rir_for_line) <= 4
            and reps_for_line is not None
        ):
            candidate = (
                float(target["velocity_intercept"])
                + float(target["velocity_slope"]) * load
                + float(target.get("velocity_rir_coef") or 0.0) * float(rir_for_line)
                + float(target.get("velocity_rep_coef") or 0.0) * float(reps_for_line)
            )
            if candidate > 0:
                expected = round(candidate, 3)
                if method == "pooled":
                    reps_min, reps_max = target.get("reps_min"), target.get("reps_max")
                    if (
                        reps_min is not None and reps_max is not None
                        and not (int(reps_min) <= int(reps_for_line) <= int(reps_max))
                    ):
                        extrapolated = True
                        reasons.append("rep_outside_fitted_range")
                load_min, load_max = target.get("load_min"), target.get("load_max")
                if load_min is not None and load_max is not None and not (
                    float(load_min) <= load <= float(load_max)
                ):
                    extrapolated = True
                    reasons.append("load_outside_fitted_range")
                basis = ("pooled" if method == "pooled" else "line") + (
                    "_extrapolated" if extrapolated else ""
                )
                spread = target.get("velocity_residual_mad")
                half = 2.0 * float(spread) if spread and float(spread) > 0 else max(0.02, candidate * 0.05)
                low, high = round(candidate - half, 3), round(candidate + half, 3)
    reference = expected if expected is not None else target["target_mps"]
    delta = None if actual is None else round(actual - reference, 3)
    delta_pct = (
        round((actual - reference) / reference * 100, 2)
        if actual is not None and reference > 0 else None
    )
    within = bool(low <= actual <= high) if actual is not None and low is not None and high is not None else None
    extra_set = bool(
        _integer(row.get("set_index")) is not None
        and _integer(item.get("sets")) is not None
        and int(row["set_index"]) > int(item["sets"])
    )
    comparable = not any(reason in _HARD_REASONS for reason in reasons)
    shown = dict(target)
    if expected is not None:
        shown["low_mps"], shown["high_mps"] = low, high
        shown["expected_mps"] = expected
    return _base_result(
        row, reasons=reasons, target=shown, target_source=target_source,
        actual_velocity=actual, velocity_source=velocity_source,
        actual_load_basis=actual_basis, prescribed_load_basis=prescribed_basis,
        actual_rir=actual_rir, delta=delta, delta_pct=delta_pct, within=within,
        comparable=comparable, extra_set=extra_set, flags=flags,
        prescribed_rir=prescribed_rir, expected=expected, basis=basis,
        extrapolated=extrapolated,
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
    ordinals: dict[int, int] = {}
    seen: dict[int, int] = {}
    for row in sorted(
        rows,
        key=lambda item: (
            _integer(item.get("set_index")) or 0,
            _integer(item.get("set_id")) or 0,
        ),
    ):
        if set_matching.is_warm_up(row):
            continue
        item, _, _ = _resolve_completed_item(final_items, original_items, row)
        if item is None or row.get("set_id") is None:
            continue
        identity = int(item.get("order_index") or 0)
        ordinals[int(row["set_id"])] = seen.get(identity, 0)
        seen[identity] = seen.get(identity, 0) + 1
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
                ordinal=(
                    ordinals.get(int(row["set_id"]), 0)
                    if row.get("set_id") is not None else 0
                ),
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
        "plan_target_note": _plan_target_note(data),
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
        "plan_target_note": _plan_target_note(data),
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
        "plan_target_note": None,
        "sets": [],
        "exercises": [],
        "quality": {
            "logged_sets": 0, "working_sets": 0, "sets_with_velocity": 0,
            "sets_with_valid_velocity": 0, "target_sets": 0, "comparable_sets": 0,
            "excluded_sets": 0, "extra_sets": 0, "target_items": 0,
            "target_metadata": {}, "reasons": {},
        },
    }
