"""Longitudinal prescription-adherence aggregation.

The per-workout engine in strength_coach.adherence owns every definition. This module only
collects completed app-tracked workouts, applies filters, and sums the engine's numerators and
denominators by period and exercise. It never averages per-workout percentages and never
combines set completion, reps, load and RIR into a composite score.

A completed workout is included only when it has a materialised session row, the session is not
voided, and its frozen plan snapshot is readable. Imported sessions have no workout prescription
and are therefore outside this aggregation.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Any

from strength_coach import adherence
from strength_coach.store import queries
from strength_coach.utils import exercises

VERSION = 1
# Display guard only: a period with fewer than three workouts or five prescribed sets is shown
# in the table but omitted from trend lines. It is not a statistical confidence claim.
TREND_MIN_WORKOUTS = 3
TREND_MIN_PRESCRIBED_SETS = 5
MAX_RANGE_DAYS = 366 * 5


def _value(query: Mapping[str, Any], key: str, default: Any = None) -> Any:
    raw = query.get(key)
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    return default if raw in (None, "") else raw


def _date(value: str, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a YYYY-MM-DD date") from exc


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": int(numerator),
        "denominator": int(denominator),
        "ratio": round(numerator / denominator, 4) if denominator else None,
    }


def _weighted_mean(mean: Any, count: Any) -> float:
    if mean is None or count is None:
        return 0.0
    try:
        return float(mean) * int(count)
    except (TypeError, ValueError):
        return 0.0


def _empty_raw() -> dict[str, Any]:
    return {
        "workout_ids": set(),
        "prescribed_sets": 0,
        "performed_sets": 0,
        "matched_sets": 0,
        "missing_sets": 0,
        "extra_sets": 0,
        "unattributable_planned_sets": 0,
        "warm_up_sets_excluded": 0,
        "reps_within": 0,
        "reps_below": 0,
        "reps_above": 0,
        "reps_unavailable": 0,
        "reps_evaluated": 0,
        "load_at_target": 0,
        "load_above": 0,
        "load_below": 0,
        "load_unavailable": 0,
        "load_evaluated": 0,
        "load_deviation_sum": 0.0,
        "rir_at_target": 0,
        "rir_above": 0,
        "rir_below": 0,
        "rir_unavailable": 0,
        "rir_evaluated": 0,
        "rir_deviation_sum": 0.0,
    }


_ADDITIVE = (
    "prescribed_sets", "performed_sets", "matched_sets", "missing_sets", "extra_sets",
    "unattributable_planned_sets", "warm_up_sets_excluded",
    "reps_within", "reps_below", "reps_above", "reps_unavailable", "reps_evaluated",
    "load_at_target", "load_above", "load_below", "load_unavailable", "load_evaluated",
    "load_deviation_sum",
    "rir_at_target", "rir_above", "rir_below", "rir_unavailable", "rir_evaluated",
    "rir_deviation_sum",
)


def _add_raw(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["workout_ids"].update(source["workout_ids"])
    for key in _ADDITIVE:
        target[key] += source[key]


def _raw_view(view: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one engine view summary into additive counts."""
    reps = view.get("reps") or {}
    load = view.get("load") or {}
    rir = view.get("rir") or {}
    return {
        "workout_ids": set(),
        "prescribed_sets": int(view.get("prescribed_sets") or 0),
        "performed_sets": int(view.get("performed_sets") or 0),
        "matched_sets": int(view.get("matched_sets") or 0),
        "missing_sets": int(view.get("missing_sets") or 0),
        "extra_sets": int(view.get("extra_sets") or 0),
        "unattributable_planned_sets": int(view.get("unattributable_planned_sets") or 0),
        "warm_up_sets_excluded": int(view.get("warm_up_sets_excluded") or 0),
        "reps_within": int(reps.get("within_target") or 0),
        "reps_below": int(reps.get("below_target") or 0),
        "reps_above": int(reps.get("above_target") or 0),
        "reps_unavailable": int(reps.get("unavailable_sets") or 0),
        "reps_evaluated": int(reps.get("evaluated_sets") or 0),
        "load_at_target": int(load.get("at_target") or 0),
        "load_above": int(load.get("above_target") or 0),
        "load_below": int(load.get("below_target") or 0),
        "load_unavailable": int(load.get("unavailable_sets") or 0),
        "load_evaluated": int(load.get("evaluated_sets") or 0),
        "load_deviation_sum": _weighted_mean(
            load.get("mean_absolute_deviation_kg"), load.get("evaluated_sets")
        ),
        "rir_at_target": int(rir.get("at_target") or 0),
        "rir_above": int(rir.get("above_target") or 0),
        "rir_below": int(rir.get("below_target") or 0),
        "rir_unavailable": int(rir.get("unavailable_sets") or 0),
        "rir_evaluated": int(rir.get("evaluated_sets") or 0),
        "rir_deviation_sum": _weighted_mean(
            rir.get("mean_deviation"), rir.get("evaluated_sets")
        ),
    }


def _raw_exercise(entry: Mapping[str, Any]) -> dict[str, Any]:
    reps = entry.get("reps") or {}
    load = entry.get("load") or {}
    rir = entry.get("rir") or {}
    return {
        "workout_ids": set(),
        "prescribed_sets": int(entry.get("prescribed_sets") or 0),
        "performed_sets": int(entry.get("performed_sets") or 0),
        "matched_sets": int(entry.get("matched_sets") or 0),
        "missing_sets": int(entry.get("missing_sets") or 0),
        "extra_sets": int(entry.get("extra_sets") or 0),
        "unattributable_planned_sets": int(entry.get("unattributable_planned_sets") or 0),
        "warm_up_sets_excluded": int(entry.get("warm_up_sets_excluded") or 0),
        "reps_within": int(reps.get("within_target") or 0),
        "reps_below": int(reps.get("below_target") or 0),
        "reps_above": int(reps.get("above_target") or 0),
        "reps_unavailable": int(reps.get("unavailable_sets") or 0),
        "reps_evaluated": int(reps.get("evaluated_sets") or 0),
        "load_at_target": int(load.get("at_target") or 0),
        "load_above": int(load.get("above_target") or 0),
        "load_below": int(load.get("below_target") or 0),
        "load_unavailable": int(load.get("unavailable_sets") or 0),
        "load_evaluated": int(load.get("evaluated_sets") or 0),
        "load_deviation_sum": _weighted_mean(
            load.get("mean_absolute_deviation_kg"), load.get("evaluated_sets")
        ),
        "rir_at_target": int(rir.get("at_target") or 0),
        "rir_above": int(rir.get("above_target") or 0),
        "rir_below": int(rir.get("below_target") or 0),
        "rir_unavailable": int(rir.get("unavailable_sets") or 0),
        "rir_evaluated": int(rir.get("evaluated_sets") or 0),
        "rir_deviation_sum": _weighted_mean(
            rir.get("mean_deviation"), rir.get("evaluated_sets")
        ),
    }


def _raw_filtered(view: Mapping[str, Any], exercise_id: str) -> dict[str, Any] | None:
    entries = [
        entry for entry in (view.get("exercises") or [])
        if str(entry.get("exercise_id")) == exercise_id
    ]
    unmatched = [
        row for row in ((view.get("quality") or {}).get("unmatched") or [])
        if str(row.get("exercise_id")) == exercise_id
    ]
    if not entries and not unmatched:
        return None
    raw = _empty_raw()
    for entry in entries:
        _add_raw(raw, _raw_exercise(entry))
    # An unmatched set has no plan-item attribution, so it can add extra work but never a
    # prescribed slot or a target-attainment denominator.
    raw["performed_sets"] += len(unmatched)
    raw["extra_sets"] += len(unmatched)
    return raw


def _finalize(raw: Mapping[str, Any]) -> dict[str, Any]:
    prescribed = int(raw["prescribed_sets"])
    matched = int(raw["matched_sets"])
    reps_evaluated = int(raw["reps_evaluated"])
    load_evaluated = int(raw["load_evaluated"])
    rir_evaluated = int(raw["rir_evaluated"])
    workouts = len(raw["workout_ids"])
    return {
        "workouts": workouts,
        "prescribed_sets": prescribed,
        "performed_sets": int(raw["performed_sets"]),
        "matched_sets": matched,
        "missing_sets": int(raw["missing_sets"]),
        "extra_sets": int(raw["extra_sets"]),
        "unattributable_planned_sets": int(raw["unattributable_planned_sets"]),
        "warm_up_sets_excluded": int(raw["warm_up_sets_excluded"]),
        "set_completion": _ratio(matched, prescribed),
        "reps": {
            "evaluated_sets": reps_evaluated,
            "within": int(raw["reps_within"]),
            "below": int(raw["reps_below"]),
            "above": int(raw["reps_above"]),
            "unavailable": int(raw["reps_unavailable"]),
            "attainment": _ratio(int(raw["reps_within"]), reps_evaluated),
        },
        "load": {
            "evaluated_sets": load_evaluated,
            "at_target": int(raw["load_at_target"]),
            "above": int(raw["load_above"]),
            "below": int(raw["load_below"]),
            "unavailable": int(raw["load_unavailable"]),
            "attainment": _ratio(int(raw["load_at_target"]), load_evaluated),
            "mean_absolute_deviation_kg": (
                round(float(raw["load_deviation_sum"]) / load_evaluated, 2)
                if load_evaluated else None
            ),
        },
        "rir": {
            "evaluated_sets": rir_evaluated,
            "at_target": int(raw["rir_at_target"]),
            "above": int(raw["rir_above"]),
            "below": int(raw["rir_below"]),
            "unavailable": int(raw["rir_unavailable"]),
            "attainment": _ratio(int(raw["rir_at_target"]), rir_evaluated),
            "mean_deviation": (
                round(float(raw["rir_deviation_sum"]) / rir_evaluated, 2)
                if rir_evaluated else None
            ),
        },
        "has_data": bool(prescribed or raw["performed_sets"]),
        "small_sample": bool(
            workouts < TREND_MIN_WORKOUTS or prescribed < TREND_MIN_PRESCRIBED_SETS
        ),
    }


def _period_meta(day: dt.date, group_by: str) -> dict[str, Any]:
    if group_by == "month":
        start = day.replace(day=1)
        next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        end = next_month - dt.timedelta(days=1)
        return {"key": day.strftime("%Y-%m"), "label": day.strftime("%Y-%m"),
                "start": start.isoformat(), "end": end.isoformat()}
    monday = day - dt.timedelta(days=day.weekday())
    iso = day.isocalendar()
    return {
        "key": f"{iso.year}-W{iso.week:02d}",
        "label": f"{iso.year}-W{iso.week:02d}",
        "start": monday.isoformat(),
        "end": (monday + dt.timedelta(days=6)).isoformat(),
    }


def _period_keys(start: dt.date, end: dt.date, group_by: str) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    if group_by == "month":
        cursor = start.replace(day=1)
        while cursor <= end:
            meta = _period_meta(cursor, group_by)
            meta["start"] = max(start, dt.date.fromisoformat(meta["start"])).isoformat()
            meta["end"] = min(end, dt.date.fromisoformat(meta["end"])).isoformat()
            periods.append(meta)
            cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return periods
    cursor = start - dt.timedelta(days=start.weekday())
    while cursor <= end:
        meta = _period_meta(cursor, group_by)
        meta["start"] = max(start, dt.date.fromisoformat(meta["start"])).isoformat()
        meta["end"] = min(end, dt.date.fromisoformat(meta["end"])).isoformat()
        periods.append(meta)
        cursor += dt.timedelta(days=7)
    return periods


def _exercise_options(views: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    found: dict[str, str] = {}
    for view in views:
        for entry in view.get("exercises") or []:
            exercise_id = str(entry.get("exercise_id"))
            if exercise_id and exercise_id not in found:
                found[exercise_id] = str(entry.get("exercise_name") or exercise_id)
    return [
        {"id": exercise_id, "name": name}
        for exercise_id, name in sorted(found.items(), key=lambda pair: (pair[1], pair[0]))
    ]


def _session_types(conn, start: str, end: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT session_type FROM workout_session "
        "WHERE status = 'completed' AND for_date >= ? AND for_date <= ? "
        "AND session_type IS NOT NULL ORDER BY session_type",
        (start, end),
    ).fetchall()
    return [str(row["session_type"]) for row in rows]


def analytics(conn, query: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate completed-workout adherence by period and exercise.

    Query parameters: date (as-of, default today), weeks (1-52, default 8), or explicit
    from/to; group_by=week|month; exercise_id; session_type. Training-block grouping is not
    offered because no reliable per-workout block identity exists.
    """
    to_raw = _value(query, "to") or _value(query, "date")
    to = _date(to_raw, "to") if to_raw else dt.date.today()
    from_raw = _value(query, "from")
    weeks_raw = _value(query, "weeks")
    if from_raw:
        start = _date(str(from_raw), "from")
        if start > to:
            raise ValueError("from must not be after to")
        if (to - start).days > MAX_RANGE_DAYS:
            raise ValueError(f"date range must be at most {MAX_RANGE_DAYS} days")
        weeks = None
    else:
        try:
            weeks = int(weeks_raw) if weeks_raw not in (None, "") else 8
        except (TypeError, ValueError) as exc:
            raise ValueError("weeks must be an integer from 1 to 52") from exc
        if not 1 <= weeks <= 52:
            raise ValueError("weeks must be an integer from 1 to 52")
        start = to - dt.timedelta(days=weeks * 7 - 1)

    group_by = str(_value(query, "group_by", "week"))
    if group_by not in {"week", "month"}:
        raise ValueError("group_by must be week or month")

    exercise_id = _value(query, "exercise_id")
    exercise_id = str(exercise_id).strip() if exercise_id is not None else None
    if exercise_id:
        if exercise_id not in exercises.taxonomy().entities:
            raise ValueError("exercise_id is not a known exercise")
    else:
        exercise_id = None

    session_type = _value(query, "session_type")
    session_type = str(session_type).strip() if session_type is not None else None
    if session_type and len(session_type) > 50:
        raise ValueError("session_type must be at most 50 characters")
    session_type = session_type or None

    start_iso, to_iso = start.isoformat(), to.isoformat()
    period_meta = _period_keys(start, to, group_by)
    # One accumulator per prescription view: the original and final plan can prescribe
    # different sets and targets, so their period numerators and denominators must never mix.
    period_acc: dict[str, dict[str, dict[str, Any]]] = {
        view_name: {
            meta["key"]: {"meta": meta, "raw": _empty_raw()} for meta in period_meta
        }
        for view_name in ("original", "final_plan")
    }
    total = {"original": _empty_raw(), "final_plan": _empty_raw()}
    exercise_acc: dict[str, dict[str, dict[str, Any]]] = {"original": {}, "final_plan": {}}
    workouts: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    coverage = {
        "workouts_in_range": 0,
        "workouts_analysed": 0,
        "workouts_unavailable": 0,
        "workouts_voided": 0,
        "workouts_without_session": 0,
        "invalid_plan_rows": 0,
        "workouts_filtered_out": 0,
    }

    sql = (
        "SELECT w.workout_id, w.for_date, w.session_type, w.plan_json,"
        " w.plan_modified_json, w.readiness_json, s.session_id AS materialised_session_id,"
        " s.voided AS session_voided"
        " FROM workout_session w LEFT JOIN session s ON s.session_id = w.workout_id"
        " WHERE w.status = 'completed' AND w.for_date >= ? AND w.for_date <= ?"
    )
    params: list[Any] = [start_iso, to_iso]
    if session_type:
        sql += " AND w.session_type = ?"
        params.append(session_type)
    sql += " ORDER BY w.for_date, w.workout_id"
    rows = conn.execute(sql, params).fetchall()
    coverage["workouts_in_range"] = len(rows)
    all_views: list[Mapping[str, Any]] = []

    for row in rows:
        workout_id = str(row["workout_id"])
        for_date = str(row["for_date"])
        if row["materialised_session_id"] is None:
            coverage["workouts_without_session"] += 1
            excluded.append({"workout_id": workout_id, "for_date": for_date,
                             "reason": "missing_materialised_session"})
            continue
        if int(row["session_voided"] or 0):
            coverage["workouts_voided"] += 1
            excluded.append({"workout_id": workout_id, "for_date": for_date,
                             "reason": "session_voided"})
            continue
        try:
            original_plan = json.loads(row["plan_json"])
            modified_raw = row["plan_modified_json"]
            final_plan = json.loads(modified_raw) if modified_raw else original_plan
            readiness = json.loads(row["readiness_json"])
        except (TypeError, ValueError):
            coverage["invalid_plan_rows"] += 1
            excluded.append({"workout_id": workout_id, "for_date": for_date,
                             "reason": "invalid_plan_json"})
            continue
        try:
            analysis = adherence.analyse({
                "original_plan": original_plan,
                "plan": final_plan,
                "plan_modified": bool(modified_raw),
                "readiness": readiness,
                "sets": queries.session_clean_sets(conn, workout_id),
            })
        except (TypeError, ValueError, KeyError, AttributeError):
            # A stored snapshot with unusable item fields is reported, not allowed to turn
            # the whole aggregation into a 500 or to be silently skipped.
            coverage["invalid_plan_rows"] += 1
            excluded.append({"workout_id": workout_id, "for_date": for_date,
                             "reason": "invalid_plan_json"})
            continue
        if analysis.get("status") != "available":
            coverage["workouts_unavailable"] += 1
            excluded.append({"workout_id": workout_id, "for_date": for_date,
                             "reason": str(analysis.get("reason") or "unavailable")})
            continue
        all_views.extend([analysis["original"], analysis["final_plan"]])

        raw_by_view: dict[str, dict[str, Any] | None] = {}
        for view_name in ("original", "final_plan"):
            view = analysis[view_name]
            raw = _raw_filtered(view, exercise_id) if exercise_id else _raw_view(view)
            raw_by_view[view_name] = raw
            if raw is None:
                continue
            raw["workout_ids"].add(workout_id)
            _add_raw(total[view_name], raw)
            meta = _period_meta(dt.date.fromisoformat(for_date), group_by)
            periods = period_acc[view_name]
            if meta["key"] not in periods:
                periods[meta["key"]] = {"meta": meta, "raw": _empty_raw()}
            _add_raw(periods[meta["key"]]["raw"], raw)
            for entry in view.get("exercises") or []:
                entry_id = str(entry.get("exercise_id"))
                if exercise_id and entry_id != exercise_id:
                    continue
                bucket = exercise_acc[view_name].setdefault(
                    entry_id,
                    {"name": str(entry.get("exercise_name") or entry_id),
                     "raw": _empty_raw()},
                )
                entry_raw = _raw_exercise(entry)
                entry_raw["workout_ids"].add(workout_id)
                _add_raw(bucket["raw"], entry_raw)

        if exercise_id and all(raw is None for raw in raw_by_view.values()):
            coverage["workouts_filtered_out"] += 1
            continue
        coverage["workouts_analysed"] += 1
        workouts.append({
            "workout_id": workout_id,
            "for_date": for_date,
            "session_type": row["session_type"],
            "original": _finalize(raw_by_view["original"] or _empty_raw()),
            "final_plan": _finalize(raw_by_view["final_plan"] or _empty_raw()),
        })

    workouts.sort(key=lambda item: (item["for_date"], item["workout_id"]), reverse=True)
    payload_original = _finalize(total["original"])
    payload_original["periods"] = [
        {
            **entry["meta"],
            **_finalize(entry["raw"]),
        }
        for entry in period_acc["original"].values()
    ]
    payload_original["periods"].sort(key=lambda item: item["start"])
    payload_final = _finalize(total["final_plan"])
    payload_final["periods"] = [
        {
            **entry["meta"],
            **_finalize(entry["raw"]),
        }
        for entry in period_acc["final_plan"].values()
    ]
    payload_final["periods"].sort(key=lambda item: item["start"])

    for target, view_name in ((payload_original, "original"), (payload_final, "final_plan")):
        rows_out = []
        for entry_id, bucket in exercise_acc[view_name].items():
            rows_out.append({
                "exercise_id": entry_id,
                "exercise_name": bucket["name"],
                **_finalize(bucket["raw"]),
            })
        rows_out.sort(key=lambda item: (
            -int(item["prescribed_sets"]), item["exercise_name"], item["exercise_id"]
        ))
        target["exercises"] = rows_out

    filter_exercises = _exercise_options(all_views)
    return {
        "version": VERSION,
        "status": "available",
        "reason": None,
        "range": {
            "from": start_iso,
            "to": to_iso,
            "weeks": weeks,
            "group_by": group_by,
        },
        "filters": {
            "exercise_id": exercise_id,
            "session_type": session_type,
            "exercises": filter_exercises,
            "session_types": _session_types(conn, start_iso, to_iso),
        },
        "definitions": {
            "aggregation": (
                "summed numerators and denominators across workouts; never an average of "
                "per-workout percentages"
            ),
            "set_completion": "matched prescribed slots / attributable prescribed slots",
            "reps": "matched sets with reps in target / matched sets with a usable target and actual reps",
            "load": (
                "matched sets whose external load is within the plan rounding increment / matched "
                "sets with comparable load targets and actuals"
            ),
            "rir": "matched sets within +/-1 RIR of target / matched sets with RIR target and actual",
            "extra_sets": (
                "performed working sets that do not fill a prescribed slot, including surplus, "
                "removed-exercise, added-exercise and unmatched work"
            ),
            "small_sample": (
                "display guard only: a period or exercise is marked small when it has fewer than "
                f"{TREND_MIN_WORKOUTS} workouts or fewer than {TREND_MIN_PRESCRIBED_SETS} prescribed sets"
            ),
            "block_dimension": "unavailable: no reliable per-workout training-block identity",
        },
        "coverage": {
            **coverage,
            "excluded": excluded,
            "trend_guard": {
                "min_workouts": TREND_MIN_WORKOUTS,
                "min_prescribed_sets": TREND_MIN_PRESCRIBED_SETS,
            },
            "block_dimension": "unavailable_no_reliable_block_identity",
        },
        "original": payload_original,
        "final_plan": payload_final,
        "workouts": workouts,
    }
