"""Longitudinal VBT target performance for the Performance view.

This is a read-only descriptive layer over the frozen targets and corrected clean_set rows used
by `vbt_analysis`. It reports residuals, calibration-band evidence, actual/prescribed RIR and
within-set velocity drift by cohort. Cohorts are never collapsed into one cross-lift model and
the output is not a prescription input.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from strength_coach.features import residual, vbt_analysis
from strength_coach.store import queries
from strength_coach.utils import exercises as exercises_mod

DRIFT_MIN_SETS = 5
DRIFT_MIN_WEEKS = 3
BOOTSTRAP_RESAMPLES = 2000


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _week_start(value: Any) -> str | None:
    day = _date(value)
    return None if day is None else (day - dt.timedelta(days=day.weekday())).isoformat()


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _mad(values: Sequence[float]) -> float | None:
    if not values:
        return None
    center = statistics.median(values)
    return round(statistics.median([abs(value - center) for value in values]), 3)


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": int(numerator),
        "denominator": int(denominator),
        "ratio": round(numerator / denominator, 4) if denominator else None,
    }


def _consecutive_weeks(weeks: Sequence[str]) -> int:
    """Longest run of weekly buckets that are exactly seven days apart."""
    days = sorted({_date(week) for week in weeks if _date(week) is not None})
    if not days:
        return 0
    longest = current = 1
    for previous, current_day in zip(days, days[1:], strict=False):
        if (current_day - previous).days == 7:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def _bootstrap_ci(values: Sequence[float]) -> dict[str, Any] | None:
    """Deterministic percentile bootstrap for a mean residual, descriptive only."""
    if len(values) < residual.MIN_OBSERVATIONS:
        return None
    ordered = sorted(values)
    payload = ",".join(f"{value:.6f}" for value in ordered).encode("utf-8")
    seed = int(hashlib.sha256(payload).hexdigest()[:16], 16)
    rng = random.Random(seed)
    n = len(ordered)
    means = sorted(sum(rng.choices(ordered, k=n)) / n for _ in range(BOOTSTRAP_RESAMPLES))
    return {
        "low": round(means[int(0.025 * (len(means) - 1))], 3),
        "high": round(means[int(0.975 * (len(means) - 1))], 3),
        "level": 0.95,
        "resamples": BOOTSTRAP_RESAMPLES,
        "method": "deterministic percentile bootstrap; descriptive, not a prediction interval",
    }


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


def _band_evidence(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evaluable = [
        row for row in rows
        if row.get("actual_velocity_mps") is not None
        and float(row["actual_velocity_mps"]) > 0
        and row.get("low_mps") is not None
        and row.get("high_mps") is not None
    ]
    below = sum(1 for row in evaluable if row["actual_velocity_mps"] < row["low_mps"])
    above = sum(1 for row in evaluable if row["actual_velocity_mps"] > row["high_mps"])
    within = sum(
        1 for row in evaluable
        if float(row["low_mps"]) <= float(row["actual_velocity_mps"]) <= float(row["high_mps"])
    )
    return {
        "below_band": below,
        "within_band": within,
        "above_band": above,
        "evaluable": len(evaluable),
        "within_ratio": _ratio(within, len(evaluable)),
    }


def _rir_evidence(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    with_rir = [row for row in rows if row.get("actual_rir") is not None]
    outside = 0
    for row in with_rir:
        low, high = row.get("target_rir_low"), row.get("target_rir_high")
        if low is not None and high is not None and not int(low) <= int(row["actual_rir"]) <= int(high):
            outside += 1
    return {
        "sets_with_rir": len(with_rir),
        "missing_rir": len(rows) - len(with_rir),
        "outside_band": outside,
        "mean_actual_rir": _mean([float(row["actual_rir"]) for row in with_rir]),
        "mean_prescribed_rir": _mean([
            float(row["prescribed_rir"]) for row in with_rir
            if row.get("prescribed_rir") is not None
        ]),
        "target_rir_low": next(
            (row.get("target_rir_low") for row in rows if row.get("target_rir_low") is not None),
            None,
        ),
        "target_rir_high": next(
            (row.get("target_rir_high") for row in rows if row.get("target_rir_high") is not None),
            None,
        ),
    }


def _cohort(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    comparable = [row for row in rows if row["comparable"]]
    residuals = [float(row["delta_mps"]) for row in comparable if row.get("delta_mps") is not None]
    relative = [float(row["delta_pct"]) for row in comparable if row.get("delta_pct") is not None]
    absolute_relative = [abs(value) for value in relative]
    dates = sorted({str(row.get("workout_date") or "") for row in rows if row.get("workout_date")})
    weeks = 0.0
    if dates:
        first, last = _date(dates[0]), _date(dates[-1])
        if first is not None and last is not None:
            weeks = round((last - first).days / 7.0, 1)
    n = len(residuals)
    spread = round(statistics.stdev(residuals), 3) if n > 1 else None
    if rows and rows[0].get("target_metadata") == "legacy":
        gate, reason = "insufficient", "legacy target has no calibration band"
    elif n < residual.MIN_OBSERVATIONS:
        gate, reason = "insufficient", f"{n} comparable observations, need {residual.MIN_OBSERVATIONS}"
    elif n >= residual.EVAL_OBSERVATIONS and weeks >= residual.EVAL_WEEKS and spread is not None:
        gate, reason = "evaluation", (
            f"{n} comparable observations over {weeks} weeks with a residual spread; "
            "ready for prospective evaluation, not for automatic change"
        )
    else:
        gate, reason = "signal", (
            f"{n} comparable observations; need {residual.EVAL_OBSERVATIONS} over "
            f"{residual.EVAL_WEEKS} weeks before evaluation"
        )
    first = rows[0] if rows else {}
    target = first.get("target") or {}
    return {
        "exercise_id": first.get("exercise_id"),
        "exercise_name": first.get("exercise_name"),
        "scope": first.get("scope") or "legacy",
        "family": first.get("family"),
        "target_rep_count": first.get("target_rep_count"),
        "target_rir_low": first.get("target_rir_low"),
        "target_rir_high": first.get("target_rir_high"),
        "n": n,
        "weeks": weeks,
        "sets": len(rows),
        "comparable_sets": len(comparable),
        "excluded_sets": len(rows) - len(comparable),
        "mean_residual_mps": _mean(residuals),
        "median_residual_mps": _median(residuals),
        "mean_absolute_error_mps": _mean([abs(value) for value in residuals]),
        "median_absolute_error_mps": _median([abs(value) for value in residuals]),
        "spread_mps": spread,
        "mad_mps": _mad(residuals),
        "mean_relative_delta_pct": _mean(relative),
        "median_relative_delta_pct": _median(relative),
        "mean_absolute_relative_error_pct": _mean(absolute_relative),
        "median_absolute_relative_error_pct": _median(absolute_relative),
        "within_calibration_band": _ratio(
            sum(1 for row in comparable if row.get("within_calibration_band") is True),
            sum(1 for row in comparable if row.get("within_calibration_band") is not None),
        ),
        "above_target": _ratio(sum(1 for value in residuals if value > 0), len(residuals)),
        "below_target": _ratio(sum(1 for value in residuals if value < 0), len(residuals)),
        "band_evidence": _band_evidence(rows),
        "rir": _rir_evidence(rows),
        "bootstrap_mean_ci": _bootstrap_ci(residuals),
        "gate": gate,
        "reason": reason,
        "target": target,
        "calibration_ids": sorted({
            str(row["calibration_id"]) for row in rows if row.get("calibration_id")
        }),
        "method_versions": sorted({
            str(row["method_version"]) for row in rows if row.get("method_version")
        }),
        "target_sources": sorted({
            str(row["target_source"]) for row in rows if row.get("target_source")
        }),
        "reasons": dict(sorted(Counter(
            reason for row in rows for reason in row.get("reasons") or []
        ).items())),
        "set_ids": [row.get("set_id") for row in rows],
        # Weekly series stay inside their cohort; a multi-cohort weekly mean would be a
        # cross-exercise pool and is deliberately not produced.
        "weekly": _weekly([row for row in rows if row["comparable"]]),
    }


def _weekly(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        week = _week_start(row.get("workout_date"))
        if week is not None:
            grouped[week].append(row)
    output: list[dict[str, Any]] = []
    for week, items in sorted(grouped.items()):
        comparable = [row for row in items if row["comparable"]]
        residuals = [float(row["delta_mps"]) for row in comparable if row.get("delta_mps") is not None]
        band = _band_evidence(items)
        output.append({
            "week_start": week,
            "sets": len(items),
            "comparable_sets": len(comparable),
            "mean_residual_mps": _mean(residuals),
            "median_residual_mps": _median(residuals),
            "mean_absolute_error_mps": _mean([abs(value) for value in residuals]),
            "within_band_ratio": band["within_ratio"],
            "above_band": band["above_band"],
            "below_band": band["below_band"],
        })
    return output


def _workout_rows(conn, start: str, end: str, exercise_id: str | None) -> list[Mapping[str, Any]]:
    workouts = conn.execute(
        "SELECT w.workout_id, w.for_date, w.plan_json, w.plan_modified_json "
        "FROM workout_session w JOIN session s ON s.session_id = w.workout_id "
        "WHERE w.status = 'completed' AND COALESCE(s.voided, 0) = 0 "
        "AND w.for_date BETWEEN ? AND ? ORDER BY w.for_date, w.workout_id",
        (start, end),
    ).fetchall()
    output: list[Mapping[str, Any]] = []
    for workout in workouts:
        original = json.loads(workout["plan_json"])
        modified_raw = workout["plan_modified_json"]
        data = {
            "workout_id": workout["workout_id"],
            "for_date": workout["for_date"],
            "original_plan": original,
            "plan": json.loads(modified_raw) if modified_raw else original,
        }
        rows = queries.session_clean_sets(conn, str(workout["workout_id"]))
        comparisons = vbt_analysis.completed_sets(
            data, rows, overrides=queries.session_vbt_overrides(conn, str(workout["workout_id"])),
        )
        for comparison in comparisons:
            if exercise_id and str(comparison.get("exercise_id")) != exercise_id:
                continue
            comparison["workout_date"] = str(workout["for_date"])
            output.append(comparison)
    return output


def _drift(conn, start: str, end: str, exercise_id: str | None) -> dict[str, Any]:
    sql = (
        "SELECT r.clean_set_id, r.rep_index, r.velocity_mps, s.exercise_id, s.set_id, "
        "s.reps, s.is_working_set, s.flags, s.load_basis, w.for_date "
        "FROM clean_rep r JOIN clean_set s ON s.set_id = r.clean_set_id "
        "JOIN workout_session w ON w.workout_id = s.session_id "
        "JOIN session sess ON sess.session_id = s.session_id "
        "WHERE w.status = 'completed' AND COALESCE(sess.voided, 0) = 0 "
        "AND s.voided = 0 AND NOT EXISTS (SELECT 1 FROM clean_set child "
        "WHERE child.supersedes_id = s.set_id) "
        "AND w.for_date BETWEEN ? AND ?"
    )
    params: list[Any] = [start, end]
    if exercise_id:
        sql += " AND s.exercise_id = ?"
        params.append(exercise_id)
    reps = conn.execute(sql + " ORDER BY w.for_date, s.set_id, r.rep_index", params).fetchall()
    override_sql = (
        "SELECT o.set_id, o.rep_index, o.velocity_mps FROM vbt_override o "
        "JOIN clean_set s ON s.set_id = o.set_id "
        "JOIN workout_session w ON w.workout_id = s.session_id "
        "JOIN session sess ON sess.session_id = s.session_id "
        "WHERE o.rep_index IS NOT NULL AND COALESCE(sess.voided, 0) = 0 "
        "AND s.voided = 0 AND NOT EXISTS (SELECT 1 FROM vbt_override child "
        "WHERE child.supersedes_id = o.override_id) "
        "AND w.for_date BETWEEN ? AND ?"
    )
    override_params: list[Any] = [start, end]
    if exercise_id:
        override_sql += " AND s.exercise_id = ?"
        override_params.append(exercise_id)
    overrode = {
        (int(row["set_id"]), int(row["rep_index"])): float(row["velocity_mps"])
        for row in conn.execute(override_sql, override_params).fetchall()
    }
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for row in reps:
        set_id = int(row["clean_set_id"])
        if int(row["is_working_set"] or 0) != 1:
            continue
        if "REPS_TYPO" in _flags(row["flags"]):
            continue
        key = (str(row["exercise_id"]), set_id)
        item = grouped.setdefault(key, {
            "exercise_id": str(row["exercise_id"]),
            "set_id": set_id,
            "date": str(row["for_date"]),
            "reps": int(row["reps"] or 0),
            "load_basis": row["load_basis"],
            "values": {},
        })
        value = overrode.get((set_id, int(row["rep_index"])), _float(row["velocity_mps"]))
        if value is not None and value > 0:
            item["values"][int(row["rep_index"])] = value
    records = []
    for item in grouped.values():
        ordered = sorted(item["values"].items())
        if len(ordered) < 2:
            continue
        first = ordered[0][1]
        last = ordered[-1][1]
        records.append({
            "exercise_id": item["exercise_id"],
            "set_id": item["set_id"],
            "date": item["date"],
            "reps": item["reps"],
            "rep_count": len(ordered),
            "load_basis": item["load_basis"],
            "first_mps": round(first, 3),
            "last_mps": round(last, 3),
            "loss_mps": round(first - last, 3),
            "loss_pct": round((first - last) / first * 100, 2) if first else None,
        })
    grouped_exercise: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped_exercise[record["exercise_id"]].append(record)
    summaries = []
    for exercise_id, items in sorted(grouped_exercise.items()):
        weekly: dict[str, list[float]] = defaultdict(list)
        for item in items:
            week = _week_start(item["date"])
            if week is not None and item["loss_pct"] is not None:
                weekly[week].append(float(item["loss_pct"]))
        weeks = sorted(weekly)
        weekly_rows = [
            {
                "week_start": week,
                "sets": len(values),
                "median_loss_pct": _median(values),
            }
            for week, values in sorted(weekly.items())
        ]
        loss_values = [float(item["loss_pct"]) for item in items if item["loss_pct"] is not None]
        consecutive = _consecutive_weeks(weeks)
        gate = (
            "descriptive"
            if len(items) >= DRIFT_MIN_SETS and consecutive >= DRIFT_MIN_WEEKS
            else "insufficient"
        )
        summaries.append({
            "exercise_id": exercise_id,
            "exercise_name": str(
                exercises_mod.taxonomy().entities.get(exercise_id, {}).get("display") or exercise_id
            ),
            "n_sets": len(items),
            "n_reps": sum(int(item["rep_count"]) for item in items),
            "weeks": len(weeks),
            "consecutive_weeks": consecutive,
            "median_loss_pct": _median(loss_values),
            "mean_loss_pct": _mean(loss_values),
            "first_week_median_loss_pct": weekly_rows[0]["median_loss_pct"] if weekly_rows else None,
            "last_week_median_loss_pct": weekly_rows[-1]["median_loss_pct"] if weekly_rows else None,
            "change_pct_points": (
                round(weekly_rows[-1]["median_loss_pct"] - weekly_rows[0]["median_loss_pct"], 2)
                if len(weekly_rows) >= 2
                and weekly_rows[0]["median_loss_pct"] is not None
                and weekly_rows[-1]["median_loss_pct"] is not None
                else None
            ),
            "weekly": weekly_rows,
            "gate": gate,
            "reason": (
                "descriptive; at least 5 sets over 3 weeks"
                if gate == "descriptive" else "insufficient; need at least 5 sets over 3 weeks"
            ),
            "sets": sorted(items, key=lambda item: (item["date"], item["set_id"])),
        })
    return {
        "n_sets": len(records),
        "n_exercises": len(summaries),
        "gates": {"min_sets": DRIFT_MIN_SETS, "min_weeks": DRIFT_MIN_WEEKS},
        "exercises": summaries,
        "sets": sorted(records, key=lambda item: (item["date"], item["set_id"])),
    }


def analyse(
    conn,
    *,
    start: str,
    end: str,
    exercise_id: str | None = None,
) -> dict[str, Any]:
    """Build the longitudinal VBT performance payload for one date range."""
    rows = _workout_rows(conn, start, end, exercise_id)
    target_rows = [row for row in rows if row.get("target_mps") is not None]
    comparable = [row for row in target_rows if row["comparable"]]

    cohorts_map: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in target_rows:
        key = (
            str(row.get("exercise_id")),
            row.get("scope") or "legacy",
            row.get("family"),
            row.get("target_rep_count"),
            row.get("target_rir_low"),
            row.get("target_rir_high"),
        )
        cohorts_map[key].append(row)
    cohorts = [
        _cohort(group)
        for _, group in sorted(
            cohorts_map.items(), key=lambda item: tuple(str(part) for part in item[0])
        )
    ]
    # A single cohort may show its weekly series at the panel level. With several cohorts the
    # weekly series is kept inside each cohort and not averaged across exercises/scopes.
    weekly = _weekly(comparable) if len(cohorts) == 1 else []
    weekly_note = (
        "Weekly residuals are shown for the single cohort in this view."
        if len(cohorts) == 1 and weekly
        else "Weekly residuals are shown per cohort; choose one cohort for a panel-level series."
        if len(cohorts) > 1
        else "No comparable weekly residuals."
    )
    drift = _drift(conn, start, end, exercise_id)
    evaluation_ready = sum(1 for cohort in cohorts if cohort["gate"] == "evaluation") >= 2
    scope_sets = Counter(str(row.get("scope") or "legacy") for row in target_rows)
    scope_cohorts = Counter(str(cohort["scope"]) for cohort in cohorts)
    metadata = Counter(str(row.get("target_metadata") or "missing") for row in target_rows)
    abstain: list[str] = []
    if not target_rows:
        abstain.append("no completed set in this range has a stored VBT target")
    if target_rows and not comparable:
        abstain.append("no target set met the exclusion/effort comparability rules")
    abstain.extend(
        f"{cohort['exercise_id']} {cohort['scope']} {cohort['target_rep_count']} reps: {cohort['reason']}"
        for cohort in cohorts if cohort["gate"] == "insufficient"
    )
    if not drift["sets"]:
        abstain.append("no working set with at least two valid per-rep velocities")
    return {
        "from": start,
        "to": end,
        "exercise_id": exercise_id,
        "summary": {
            "target_sets": len(target_rows),
            "comparable_sets": len(comparable),
            "excluded_sets": len(target_rows) - len(comparable),
            "cohorts": len(cohorts),
            "exercises": len({row.get("exercise_id") for row in target_rows}),
            "scopes": dict(sorted(scope_cohorts.items())),
            "scope_sets": dict(sorted(scope_sets.items())),
            "target_metadata": dict(sorted(metadata.items())),
            "evaluation_ready": evaluation_ready,
            "abstain": abstain,
        },
        "gates": {
            "descriptive_min_observations": residual.MIN_OBSERVATIONS,
            "evaluation_observations": residual.EVAL_OBSERVATIONS,
            "evaluation_weeks": residual.EVAL_WEEKS,
            "drift_min_sets": DRIFT_MIN_SETS,
            "drift_min_weeks": DRIFT_MIN_WEEKS,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "note": "Gates make a cohort readable/evaluable; they do not authorize a change.",
        },
        "cohorts": cohorts,
        "weekly": weekly,
        "weekly_note": weekly_note,
        "drift": drift,
        "sets": sorted(target_rows, key=lambda row: (str(row.get("workout_date")), int(row.get("set_id") or 0))),
    }
