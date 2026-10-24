"""Descriptive multi-week outcome review.

This is a read-only report. It does not rank, predict, change a prescription or claim that a
change was caused by training.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict
from typing import Any

import pandas as pd

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.domain.symptoms import flare_from
from strength_coach.features import cardio as cardio_feature
from strength_coach.features import measurements as measurements_feature
from strength_coach.features import readiness_score
from strength_coach.rules import RuleContext, evaluate, load_document
from strength_coach.store import queries
from strength_coach.utils import exercises

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MEASUREMENT_KEYS = (
    "steps_per_day", "sitting_hours_per_day", "bodyweight_kg", "body_fat_pct",
    "grip_strength_kg", "vo2max", "sit_to_stand_5_s",
)


def _window(on_date: str | None, weeks: int) -> tuple[dt.date, dt.date]:
    end = dt.date.fromisoformat(on_date) if on_date else dt.date.today()
    return end - dt.timedelta(days=7 * weeks - 1), end


def _sets(conn, start: dt.date, end: dt.date) -> pd.DataFrame:
    cursor = conn.execute(
        """
        SELECT occurred_on AS date, session_id, exercise_id, load_kg, reps, rir,
               is_working_set
          FROM clean_set
         WHERE occurred_on BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    )
    columns = [description[0] for description in cursor.description]
    return pd.DataFrame([dict(zip(columns, row)) for row in cursor.fetchall()])


def _strength(conn, sets: pd.DataFrame, start: dt.date, end: dt.date) -> dict:
    taxonomy = exercises.taxonomy().entities
    entities = {k: v for k, v in taxonomy.items() if v.get("main_lift")}
    frame = sets[sets["is_working_set"].astype(bool)] if not sets.empty else sets
    by_lift: dict[str, list[tuple[str, float]]] = defaultdict(list)
    if not frame.empty:
        for row in frame.itertuples():
            if row.exercise_id not in entities:
                continue
            estimate = e1rm_mod.estimate_e1rm(
                row.load_kg, row.reps, row.rir if pd.notna(row.rir) else None
            )
            if estimate is None or not estimate.is_usable:
                continue
            by_lift[str(row.exercise_id)].append((str(row.date)[:10], estimate.value_kg))

    lifts = []
    for exercise_id, points in sorted(by_lift.items()):
        points.sort()
        values = [value for _, value in points]
        first, last = values[0], values[-1]
        change = round(last - first, 2)
        lifts.append({
            "exercise_id": exercise_id,
            "n": len(values),
            "first_on": points[0][0],
            "first_e1rm": round(first, 1),
            "last_on": points[-1][0],
            "last_e1rm": round(last, 1),
            "change_kg": change,
            "change_pct": round(100 * change / first, 1) if first else None,
            "best_e1rm": round(max(values), 1),
        })

    sessions = queries.sessions(conn, start=start.isoformat(), end=end.isoformat())
    session_ids = set(sessions["session_id"].astype(str)) if not sessions.empty else set()
    feedback = {}
    for row in queries.session_feedback_all(conn):
        if str(row["session_id"]) in session_ids:
            feedback[str(row["session_id"])] = row
    srpe = [float(row["srpe"]) for row in feedback.values() if row.get("srpe") is not None]
    duration = [float(row["duration_min"]) for row in feedback.values()
                if row.get("duration_min") is not None]

    patterns = _weekly_pattern_volume(frame, start, end)
    return {
        "main_lifts": lifts,
        "sessions": int(len(sessions)),
        "session_type_counts": (
            sessions["session_type"].value_counts().to_dict() if not sessions.empty else {}
        ),
        "sRPE": {
            "n": len(srpe), "average": round(statistics.mean(srpe), 2) if srpe else None,
        },
        "duration": {
            "n": len(duration),
            "average_min": round(statistics.mean(duration), 1) if duration else None,
            "measured_sessions": int((sessions["duration_basis"] == "measured").sum())
            if not sessions.empty and "duration_basis" in sessions else None,
        },
        "volume": patterns,
        "note": "e1RM values are estimates from working sets; change is descriptive.",
    }


def _weekly_pattern_volume(frame: pd.DataFrame, start: dt.date, end: dt.date) -> list[dict]:
    if frame.empty:
        return []
    taxonomy = exercises.taxonomy().entities
    work = frame.copy()
    work["pattern"] = work["exercise_id"].map(
        lambda value: (taxonomy.get(str(value), {}) or {}).get("pattern")
    )
    work = work[work["pattern"].notna()]
    work["date"] = pd.to_datetime(work["date"])
    work["week"] = work["date"].dt.strftime("%G-W%V")
    grouped = work.groupby(["week", "pattern"]).size().reset_index(name="sets")
    patterns = sorted(work["pattern"].unique())
    weeks = sorted(work["week"].unique())
    out = []
    for pattern in patterns:
        rows = grouped[grouped["pattern"] == pattern]
        total = int(rows["sets"].sum())
        out.append({
            "pattern": pattern,
            "total_sets": total,
            "weeks_present": int(rows["week"].nunique()),
            "average_per_week": round(total / len(weeks), 2) if weeks else None,
        })
    return sorted(out, key=lambda row: row["pattern"])


def _attendance(conn, start: dt.date, end: dt.date, weeks: int) -> dict:
    profile = queries.athlete_profile(conn) or {}
    target_per_week = profile.get("sessions_per_week_target")
    sessions = conn.execute(
        "SELECT COUNT(*) FROM session WHERE occurred_on BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()[0]
    if target_per_week is None:
        return {"completed": int(sessions), "target": None, "pct": None,
                "note": "no sessions_per_week_target; attendance unknown"}
    target = int(target_per_week) * weeks
    return {
        "completed": int(sessions),
        "target": target,
        "pct": round(100 * sessions / target, 1) if target else None,
        "note": "target-based attendance, not a stored plan",
    }


def _readiness(conn, start: dt.date, end: dt.date) -> dict:
    scores = []
    statuses = defaultdict(int)
    day = start
    while day <= end:
        assessment = readiness_score.compute(conn, day.isoformat())
        statuses[assessment.status] += 1
        if assessment.status == "ready" and assessment.score is not None:
            scores.append(float(assessment.score))
        day += dt.timedelta(days=1)
    return {
        "n_ready": len(scores),
        "average": round(statistics.mean(scores), 3) if scores else None,
        "first": scores[0] if scores else None,
        "last": scores[-1] if scores else None,
        "statuses": dict(statuses),
        "fields": _readiness_fields(conn, start, end),
        "note": "missing readiness is unknown, not zero",
    }


def _readiness_fields(conn, start: dt.date, end: dt.date) -> dict:
    """Trend for the subjective fields used in the readiness score."""
    fields = ("sleep", "energy", "stress", "soreness")
    out = {}
    day = start
    values: dict[str, list[float]] = {field: [] for field in fields}
    while day <= end:
        data = queries.readiness_day(conn, day.isoformat()) or {}
        for field in fields:
            try:
                number = float(data.get(field))
            except (TypeError, ValueError):
                continue
            if 1 <= number <= 5:
                values[field].append(number)
        day += dt.timedelta(days=1)
    for field, series in values.items():
        out[field] = {
            "n": len(series),
            "first": series[0] if series else None,
            "last": series[-1] if series else None,
            "average": round(statistics.mean(series), 2) if series else None,
        }
    return out


def _symptoms(conn, start: dt.date, end: dt.date) -> dict:
    rows = queries.symptom_entries(conn, since=start.isoformat())
    by_region: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if str(row["logged_on"]) > end.isoformat():
            continue
        by_region[str(row["region"])].append(row)
    regions = {}
    for region, entries in by_region.items():
        flares = sum(
            1 for row in entries
            if flare_from(int(row["level"]), row.get("settled_within_48h")) is True
        )
        regions[region] = {
            "readings": len(entries),
            "flares": flares,
            "latest_level": entries[-1]["level"],
            "latest_on": str(entries[-1]["logged_on"]),
        }
    return {
        "regions": regions,
        "note": "absence of a symptom entry is unknown, not a claim of no flare",
    }


def _spinal(conn, start: dt.date, end: dt.date) -> dict:
    context = RuleContext.from_store(conn, end=end.isoformat())
    document = load_document()
    verdict = evaluate(document, context).verdict("PRG-SPINE-001")
    details = verdict.details or {}
    costs = details.get("weighted_costs", {}) or {}
    cap = float(details.get("cap", 3))
    weeks = {}
    for week, cost in costs.items():
        try:
            monday = dt.date.fromisocalendar(int(week[:4]), int(week[6:]), 1)
        except (TypeError, ValueError):
            continue
        if start <= monday <= end:
            weeks[week] = float(cost)
    breaches = [week for week, cost in weeks.items() if cost > cap]
    return {
        "cap": cap,
        "weeks": weeks,
        "breaches": breaches,
        "weeks_at_cap": [week for week, cost in weeks.items() if cost == cap],
        "note": "ordinal weighted sum; at-cap is not a breach",
    }


def _deloads(conn, start: dt.date, end: dt.date) -> dict:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prescription_modifier'"
    ).fetchone()
    if exists is None:
        return {"n": None, "items": [], "note": "modifier provenance table absent"}
    rows = conn.execute(
        "SELECT modifier_key, applied_on, detail_json FROM prescription_modifier "
        "WHERE modifier_key = 'MOD-DELOAD-001' AND applied_on BETWEEN ? AND ? "
        "ORDER BY applied_on",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return {
        "n": len(rows),
        "items": [dict(row) for row in rows],
        "note": "from prescription_modifier; web prescriptions may not be persisted",
    }


def _coverage(strength: dict, readiness: dict, symptoms: dict, deloads: dict) -> dict:
    return {
        "strength_lifts": len(strength["main_lifts"]),
        "sessions": strength["sessions"],
        "readiness_ready_days": readiness["n_ready"],
        "sRPE_sessions": strength["sRPE"]["n"],
        "duration_sessions": strength["duration"]["n"],
        "symptom_regions": len(symptoms["regions"]),
        "deload_modifiers": deloads["n"],
    }


def report(conn, *, weeks: int = 8, on_date: str | None = None) -> dict:
    if weeks <= 0 or weeks > 52:
        raise ValueError("weeks must be between 1 and 52")
    start, end = _window(on_date, weeks)
    sets = _sets(conn, start, end)
    strength = _strength(conn, sets, start, end)
    attendance = _attendance(conn, start, end, weeks)
    readiness = _readiness(conn, start, end)
    symptoms = _symptoms(conn, start, end)
    spinal = _spinal(conn, start, end)
    deloads = _deloads(conn, start, end)
    cardio = cardio_feature.compute(conn, on_date=end.isoformat(), weeks=weeks).as_dict()
    weekly = sorted(cardio.get("weekly_minutes", {}).items())
    last_four = [float(value) for _, value in weekly[-4:]]
    cardio["rolling_4w_average"] = round(statistics.mean(last_four), 1) if last_four else None
    cardio["weeks_with_data"] = len(weekly)
    measured = measurements_feature.summary(conn)
    metrics = {row["key"]: row for row in measured if row["key"] in MEASUREMENT_KEYS}

    return {
        "window": {
            "weeks": weeks, "from": start.isoformat(), "to": end.isoformat(),
        },
        "strength": {
            **strength,
            "attendance": attendance,
            "readiness": readiness,
            "symptoms": symptoms,
            "spinal": spinal,
            "deloads": deloads,
        },
        "longevity": {
            "cardio": cardio,
            "measurements": metrics,
            "readiness": readiness,
            "symptoms": symptoms,
            "note": ("cardio and measurements are captured context; not prescribed. "
                     "WHO minutes are a general reference, not a personalised target."),
        },
        "coverage": _coverage(strength, readiness, symptoms, deloads),
        "references": {
            "sessions": strength["sessions"],
            "rules": ["PRG-SPINE-001", "MOD-FAT-001", "MOD-GAP-001",
                      "MOD-DELOAD-001", "MOD-VOL-001", "MOD-VOL-002"],
            "measurements": sorted(metrics),
        },
        "note": "Descriptive review only. No causal claim, no prescription change.",
    }
