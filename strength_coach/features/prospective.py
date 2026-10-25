"""W5 prospective review: a read-only, pre-specified 4/8/12-week check.

The protocol is docs/W5-PROSPECTIVE-EVALUATION.md. This module implements the summary; it
does not create a model, store a snapshot or change a prescription.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

from strength_coach import workout
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.features import attendance as attendance_feature
from strength_coach.features import readiness_score
from strength_coach.store import queries
from strength_coach.utils import exercises

STATUSES = ("up", "down", "stable", "unclear", "unknown")


def _window(on_date: str | None, weeks: int) -> tuple[dt.date, dt.date, dt.date, dt.date]:
    if weeks not in (4, 8, 12):
        raise ValueError("weeks must be 4, 8 or 12")
    end = dt.date.fromisoformat(on_date) if on_date else dt.date.today()
    current_start = end - dt.timedelta(days=7 * weeks - 1)
    baseline_end = current_start - dt.timedelta(days=1)
    baseline_start = baseline_end - dt.timedelta(days=27)
    return baseline_start, baseline_end, current_start, end


def _sets(conn, start: dt.date, end: dt.date) -> pd.DataFrame:
    cursor = conn.execute(
        "SELECT occurred_on AS date, session_id, exercise_id, load_kg, reps, rir, "
        "is_working_set FROM clean_set WHERE occurred_on BETWEEN ? AND ? "
        "AND voided = 0 AND NOT EXISTS (SELECT 1 FROM clean_set child "
        "WHERE child.supersedes_id = clean_set.set_id)",
        (start.isoformat(), end.isoformat()),
    )
    columns = [description[0] for description in cursor.description]
    return pd.DataFrame([dict(zip(columns, row)) for row in cursor.fetchall()])


def _session_bests(frame: pd.DataFrame, main_lifts: set[str]) -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    if frame.empty:
        return out
    for row in frame[frame["is_working_set"].astype(bool)].itertuples():
        if row.exercise_id not in main_lifts:
            continue
        estimate = e1rm_mod.estimate_e1rm(
            row.load_kg, row.reps, row.rir if pd.notna(row.rir) else None
        )
        if estimate is None or not estimate.is_usable:
            continue
        out[str(row.exercise_id)].append((str(row.date)[:10], float(estimate.value_kg)))
    for values in out.values():
        values.sort()
    return out


def _lift_status(baseline: list[float], current: list[float]) -> tuple[str, float | None]:
    if len(baseline) < 2 or len(current) < 2:
        return "unknown", None
    change = round(100 * (statistics.median(current) - statistics.median(baseline))
                   / statistics.median(baseline), 1) if statistics.median(baseline) else None
    if len(baseline) < 4 or len(current) < 4:
        return "unclear", change
    if change is None:
        return "unknown", None
    if change >= 2.5:
        return "up", change
    if change <= -2.5:
        return "down", change
    return "stable", change


def _strength(baseline_sets, current_sets, entities) -> list[dict]:
    main_lifts = {key for key, value in entities.items() if value.get("main_lift")}
    base = _session_bests(baseline_sets, main_lifts)
    cur = _session_bests(current_sets, main_lifts)
    rows = []
    for exercise_id in sorted(set(base) | set(cur)):
        bvals = [value for _, value in base.get(exercise_id, [])]
        cvals = [value for _, value in cur.get(exercise_id, [])]
        status, change = _lift_status(bvals, cvals)
        rows.append({
            "exercise_id": exercise_id,
            "baseline_n": len(bvals),
            "current_n": len(cvals),
            "baseline_median_e1rm": round(statistics.median(bvals), 1) if bvals else None,
            "current_median_e1rm": round(statistics.median(cvals), 1) if cvals else None,
            "change_pct": change,
            "status": status,
            "current_series": cur.get(exercise_id, []),
        })
    return rows


def _works(conn, start: dt.date, end: dt.date) -> dict:
    rows = conn.execute(
        "SELECT workout_id FROM workout_session WHERE status = 'completed' "
        "AND for_date BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    planned = actual = 0
    incomplete = 0
    for row in rows:
        data = workout.get(conn, str(row["workout_id"]))
        comparison = data.get("comparison") or {}
        items = comparison.get("items") or []
        planned += sum(int(item.get("planned_sets") or 0) for item in items)
        actual += sum(int(item.get("actual_sets") or 0) for item in items)
        if any(item.get("status") in {"missing", "under"} for item in items):
            incomplete += 1
    if not rows:
        return {"workouts": 0, "status": "unknown",
                "note": "no completed workout with a stored plan"}
    ratio = round(actual / planned, 3) if planned else None
    return {
        "workouts": len(rows),
        "planned_sets": planned,
        "actual_sets": actual,
        "ratio": ratio,
        "incomplete": incomplete,
        "status": "complete" if ratio == 1 else "under" if ratio is not None and ratio < 1 else "over",
        "note": "modified plan; imported sessions have no plan",
    }


def _rir(current_sets) -> dict:
    if current_sets.empty:
        return {"n": 0, "adherence": None, "note": "no working sets"}
    working = current_sets[current_sets["is_working_set"].astype(bool)]
    rirs = [float(value) for value in working["rir"].dropna()]
    if not rirs:
        return {"n": 0, "adherence": None, "note": "no logged RIR"}
    return {
        "n": len(rirs),
        "adherence": round(sum(1 for value in rirs if 1 <= value <= 4) / len(rirs), 3),
        "note": "working sets with logged RIR",
    }


def _duration(conn, start: dt.date, end: dt.date) -> dict:
    sessions = queries.sessions(conn, start=start.isoformat(), end=end.isoformat())
    measured = []
    if not sessions.empty and "duration_basis" in sessions:
        for row in sessions.itertuples():
            if getattr(row, "duration_basis", None) == "measured" and pd.notna(getattr(row, "duration_min", None)):
                measured.append(float(row.duration_min))
    return {
        "measured_n": len(measured),
        "median_min": round(statistics.median(measured), 1) if measured else None,
        "planned_cap_min": 80,
        "note": "measured workout duration only; imported sessions unavailable",
    }


def _symptoms(conn, baseline_start: dt.date, current_start: dt.date,
              end: dt.date) -> dict:
    rows = queries.symptom_entries(conn, since=baseline_start.isoformat())
    by_region: dict[str, dict[str, int]] = defaultdict(lambda: {"baseline": 0, "current": 0})
    weeks_current = set()
    for row in rows:
        day = dt.date.fromisoformat(str(row["logged_on"])[:10])
        if day > end:
            continue
        bucket = "base" if day < current_start else "current"
        if bucket == "current":
            weeks_current.add(day.strftime("%G-W%V"))
        if int(row["level"]) >= 2:
            key = "baseline" if bucket == "base" else "current"
            by_region[str(row["region"])][key] += 1
    return {
        "regions": dict(by_region),
        "weeks_current_with_entry": len(weeks_current),
        "note": "level >= 2 is a reported flare; no entry is unknown",
    }


def _srpe(conn, start: dt.date, end: dt.date) -> dict:
    sessions = queries.sessions(conn, start=start.isoformat(), end=end.isoformat())
    ids = set(sessions["session_id"].astype(str)) if not sessions.empty else set()
    values = [
        float(row["srpe"]) for row in queries.session_feedback_all(conn)
        if str(row["session_id"]) in ids and row.get("srpe") is not None
    ]
    return {
        "n": len(values),
        "median": round(statistics.median(values), 2) if values else None,
    }


def _readiness(conn, start: dt.date, end: dt.date) -> dict:
    ready = 0
    day = start
    while day <= end:
        if readiness_score.compute(conn, day.isoformat()).status == "ready":
            ready += 1
        day += dt.timedelta(days=1)
    return {"ready_days": ready, "days": (end - start).days + 1}


def _flags(lifts: list[dict], attendance: dict, rir: dict, symptoms: dict,
           duration: dict, works: dict) -> list[dict]:
    flags = []
    for lift in lifts:
        if lift["status"] == "down" and (lift["change_pct"] or 0) <= -5:
            flags.append({"code": "E1RM_DOWN", "detail": f"{lift['exercise_id']} {lift['change_pct']}%"})
        series = [value for _, value in lift.get("current_series", [])]
        if len(series) >= 2:
            best = max(series)
            if all(value < 0.9 * best for value in series[-2:]):
                flags.append({"code": "E1RM_TWO_LOW", "detail": lift["exercise_id"]})
    if attendance.get("pct") is not None and attendance["pct"] < 60:
        flags.append({"code": "ATTENDANCE_LOW", "detail": f"{attendance['pct']}%"})
    if rir.get("adherence") is not None and rir["n"] >= 8 and rir["adherence"] < 0.7:
        flags.append({"code": "RIR_LOW", "detail": f"{rir['adherence']:.2f}"})
    for region, row in symptoms.get("regions", {}).items():
        if row["current"] and not row["baseline"]:
            flags.append({"code": "SYMPTOM_NEW", "detail": region})
        elif row["current"] > row["baseline"]:
            flags.append({"code": "SYMPTOM_WORSE", "detail": region})
    if duration.get("median_min") is not None and duration["median_min"] > 80:
        flags.append({"code": "DURATION_OVER_PLAN", "detail": f"{duration['median_min']} min"})
    return flags


def report(conn, *, weeks: int = 8, on_date: str | None = None) -> dict:
    baseline_start, baseline_end, current_start, end = _window(on_date, weeks)
    baseline_sets = _sets(conn, baseline_start, baseline_end)
    current_sets = _sets(conn, current_start, end)
    entities = exercises.taxonomy().entities
    profile = queries.athlete_profile(conn) or {}
    target = profile.get("sessions_per_week_target")
    attendance = attendance_feature.summary(
        conn, start=current_start, end=end, weeks=weeks, target_per_week=target,
    )
    symptoms = _symptoms(conn, baseline_start, current_start, end)
    duration = _duration(conn, current_start, end)
    works = _works(conn, current_start, end)
    rir = _rir(current_sets)
    lifts = _strength(baseline_sets, current_sets, entities)
    return {
        "window": {
            "weeks": weeks,
            "baseline_from": baseline_start.isoformat(),
            "baseline_to": baseline_end.isoformat(),
            "current_from": current_start.isoformat(),
            "current_to": end.isoformat(),
        },
        "strength": {"lifts": lifts},
        "attendance": attendance,
        "work": works,
        "rir": rir,
        "duration": duration,
        "symptoms": symptoms,
        "srpe": _srpe(conn, current_start, end),
        "readiness": _readiness(conn, current_start, end),
        "flags": _flags(lifts, attendance, rir, symptoms, duration, works),
        "coverage": {
            "baseline_sets": int(len(baseline_sets)),
            "current_sets": int(len(current_sets)),
            "current_sessions": attendance.get("completed"),
        },
        "note": "Descriptive only; no causal claim, no model and no prescription change.",
    }
