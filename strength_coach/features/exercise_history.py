"""Read-only per-exercise history for the active-workout panel.

Only completed/imported sessions are history: sets logged in the live workout stay in
`workout_set` until the workout ends. Corrections remain the append-only History editor's
job, so this module never writes.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from strength_coach.utils import exercises

# Mirror of history.CURRENT for clean_set aliased as cs. Features cannot import the
# higher-level corrections module, and a superseded row must never appear in a log view.
_CURRENT_SET = (
    "cs.voided = 0 AND NOT EXISTS "
    "(SELECT 1 FROM clean_set child WHERE child.supersedes_id = cs.set_id)"
)

MAX_LIMIT = 50


def _date_value(name: str, value: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != str(value):
        raise ValueError(f"{name} must be YYYY-MM-DD")
    return parsed.isoformat()


def _validated(exercise_id: str, limit: int, offset: int, on_or_before: str | None,
               start: str | None, end: str | None
               ) -> tuple[str, tuple[str, ...], str | None, str | None]:
    requested = str(exercise_id or "").strip()
    if not requested or requested not in exercises.taxonomy().entities:
        raise ValueError(f"unknown exercise: {exercise_id}")
    if not 1 <= int(limit) <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    if int(offset) < 0:
        raise ValueError("offset must be non-negative")
    before = _date_value("on_or_before", on_or_before)
    start_date = _date_value("start", start)
    end_date = _date_value("end", end)
    if before and end_date and before != end_date:
        raise ValueError("end and on_or_before cannot specify different dates")
    end_date = end_date or before
    if start_date and end_date and start_date > end_date:
        raise ValueError("start must be on or before end")
    return requested, exercises.history_equivalents(requested), start_date, end_date


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    value = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return round(float(value), 3)


def _analytics(conn, included: tuple[str, ...], start: str | None, end: str | None) -> dict[str, Any]:
    """Summarise only the selected exercise/date range using stored working-set facts."""
    placeholders = ",".join("?" for _ in included)
    where = [
        "s.voided = 0", "cs.exercise_id IN (" + placeholders + ")",
        "cs.is_working_set = 1", _CURRENT_SET,
    ]
    params: list[Any] = list(included)
    if start:
        where.append("s.occurred_on >= ?")
        params.append(start)
    if end:
        where.append("s.occurred_on <= ?")
        params.append(end)
    rows = conn.execute(
        "SELECT s.session_id, s.occurred_on, cs.load_kg, cs.load_basis, cs.reps, "
        "cs.reps_unit, cs.rir, cs.tonnage_kg FROM clean_set cs "
        "JOIN session s ON s.session_id = cs.session_id WHERE " + " AND ".join(where) +
        " ORDER BY s.occurred_on, s.session_id, COALESCE(cs.raw_id, cs.set_id), cs.set_id",
        params,
    ).fetchall()
    days: dict[str, dict[str, Any]] = {}
    load_values: dict[str, dict[str, list[float]]] = {}
    reps_values: dict[str, dict[str, dict[str, Any]]] = {}
    rir_values: dict[str, list[float]] = {}
    rir_distribution: dict[int, int] = {}
    total_reps = 0
    reps_missing = 0
    load_observed = 0
    rir_missing = 0
    tonnage_total = 0.0
    tonnage_sets = 0
    for row in rows:
        date = str(row["occurred_on"])[:10]
        day = days.setdefault(date, {"sessions": set(), "working_sets": 0, "tonnage_kg": 0.0,
                                    "tonnage_sets": 0, "tonnage_missing": 0})
        day["sessions"].add(str(row["session_id"]))
        day["working_sets"] += 1
        basis = str(row["load_basis"] or "unspecified")
        if row["load_kg"] is not None:
            load_values.setdefault(basis, {}).setdefault(date, []).append(float(row["load_kg"]))
            load_observed += 1
        if row["reps"] is None:
            reps_missing += 1
        else:
            unit = str(row["reps_unit"] or "unspecified")
            rep_group = reps_values.setdefault(unit, {}).setdefault(
                date, {"total": 0, "observed_sets": 0}
            )
            rep_group["total"] += int(row["reps"])
            rep_group["observed_sets"] += 1
            total_reps += 1
        if row["rir"] is None:
            rir_missing += 1
        else:
            value = int(row["rir"])
            rir_values.setdefault(date, []).append(float(value))
            rir_distribution[value] = rir_distribution.get(value, 0) + 1
        if row["tonnage_kg"] is None:
            day["tonnage_missing"] += 1
        else:
            day["tonnage_kg"] += float(row["tonnage_kg"])
            day["tonnage_sets"] += 1
            tonnage_total += float(row["tonnage_kg"])
            tonnage_sets += 1

    daily = []
    for date in sorted(days):
        day = days[date]
        daily.append({
            "date": date,
            "sessions": len(day["sessions"]),
            "working_sets": day["working_sets"],
            "tonnage_kg": round(day["tonnage_kg"], 3) if day["tonnage_sets"] else None,
            "tonnage_observed_sets": day["tonnage_sets"],
            "tonnage_missing_sets": day["tonnage_missing"],
        })
    weekly = []
    if days:
        first = _date_value("start", start) or min(days)
        last = _date_value("end", end) or max(days)
        first_day = dt.date.fromisoformat(first)
        monday = first_day - dt.timedelta(days=first_day.weekday())
        last_day = dt.date.fromisoformat(last)
        while monday <= last_day:
            week_end = monday + dt.timedelta(days=6)
            from_date = max(monday, first_day)
            to_date = min(week_end, last_day)
            date_rows = [point for point in daily if from_date.isoformat() <= point["date"] <= to_date.isoformat()]
            iso = monday.isocalendar()
            weekly.append({
                "iso_year": iso.year,
                "iso_week": iso.week,
                "start": from_date.isoformat(),
                "end": to_date.isoformat(),
                "training_dates": len(date_rows),
                "working_sets": sum(point["working_sets"] for point in date_rows),
            })
            monday += dt.timedelta(days=7)
    return {
        "session_count": len({session for day in days.values() for session in day["sessions"]}),
        "training_dates": len(days),
        "working_sets": len(rows),
        "load_observed_sets": load_observed,
        "load_missing_sets": len(rows) - load_observed,
        "reps_observed_sets": total_reps,
        "reps_missing_sets": reps_missing,
        "rir_observed_sets": sum(rir_distribution.values()),
        "rir_missing_sets": rir_missing,
        "tonnage_kg": round(tonnage_total, 3) if tonnage_sets else None,
        "tonnage_observed_sets": tonnage_sets,
        "tonnage_missing_sets": len(rows) - tonnage_sets,
        "daily": daily,
        "weekly": weekly,
        "loads": [
            {"basis": basis, "points": [
                {"date": date, "median_kg": _median(values), "observations": len(values)}
                for date, values in sorted(by_date.items())
            ]}
            for basis, by_date in sorted(load_values.items())
        ],
        "repetitions": [
            {"unit": unit, "points": [
                {"date": date, **values} for date, values in sorted(by_date.items())
            ]}
            for unit, by_date in sorted(reps_values.items())
        ],
        "rir": [
            {"date": date, "median": _median(values), "observations": len(values)}
            for date, values in sorted(rir_values.items())
        ],
        "rir_distribution": [
            {"rir": value, "sets": count}
            for value, count in sorted(rir_distribution.items())
        ],
        "tonnage_daily": [point for point in daily if point["tonnage_kg"] is not None],
    }


def history(conn, exercise_id: str, *, limit: int = 5, offset: int = 0,
            on_or_before: str | None = None, start: str | None = None,
            end: str | None = None, include_analytics: bool = False) -> dict[str, Any]:
    """Return completed sessions containing the exercise, newest first.

    `limit` counts sessions, not sets: the panel shows the last five sessions and its
    "Show more" control asks for the next page. Declared history equivalents (currently
    back extension and hyperextension) are included and reported back to the caller.
    """
    requested, included, start_date, end_date = _validated(
        exercise_id, limit, offset, on_or_before, start, end
    )
    placeholders = ",".join("?" for _ in included)
    where = [
        "s.voided = 0",
        "EXISTS (SELECT 1 FROM clean_set cs WHERE cs.session_id = s.session_id "
        f"AND cs.exercise_id IN ({placeholders}) AND cs.is_working_set = 1 "
        f"AND {_CURRENT_SET})",
    ]
    params: list[Any] = list(included)
    if start_date is not None:
        where.append("s.occurred_on >= ?")
        params.append(start_date)
    if end_date is not None:
        where.append("s.occurred_on <= ?")
        params.append(end_date)
    clause = " AND ".join(where)

    total = int(conn.execute(
        f"SELECT COUNT(*) AS n FROM session s WHERE {clause}", params
    ).fetchone()["n"])
    rows = conn.execute(
        "SELECT s.session_id, s.occurred_on, s.session_type FROM session s "
        f"WHERE {clause} ORDER BY s.occurred_on DESC, s.session_id DESC LIMIT ? OFFSET ?",
        params + [int(limit), int(offset)],
    ).fetchall()

    sessions: list[dict[str, Any]] = []
    if rows:
        session_ids = [str(row["session_id"]) for row in rows]
        session_placeholders = ",".join("?" for _ in session_ids)
        set_rows = conn.execute(
            "SELECT cs.session_id, cs.set_id, cs.load_kg, cs.load_basis, cs.reps, "
            "cs.reps_unit, cs.rir, cs.tonnage_kg FROM clean_set cs "
            f"WHERE cs.session_id IN ({session_placeholders}) "
            f"AND cs.exercise_id IN ({placeholders}) AND cs.is_working_set = 1 "
            f"AND {_CURRENT_SET} "
            "ORDER BY cs.session_id, COALESCE(cs.raw_id, cs.set_id), cs.set_id",
            session_ids + list(included),
        ).fetchall()
        by_session: dict[str, list[dict[str, Any]]] = {key: [] for key in session_ids}
        for row in set_rows:
            by_session[str(row["session_id"])].append({
                "set_index": len(by_session[str(row["session_id"])]) + 1,
                "load_kg": row["load_kg"],
                "load_basis": row["load_basis"],
                "reps": row["reps"],
                "reps_unit": row["reps_unit"],
                "rir": row["rir"],
                "tonnage_kg": row["tonnage_kg"],
            })
        for row in rows:
            session_id = str(row["session_id"])
            sessions.append({
                "session_id": session_id,
                "occurred_on": str(row["occurred_on"])[:10],
                "session_type": row["session_type"],
                "sets": by_session[session_id],
            })

    entities = exercises.taxonomy().entities
    result = {
        "exercise_id": requested,
        "included_exercises": [
            {
                "id": item,
                "display": str(entities.get(item, {}).get("display") or item),
            }
            for item in included
        ],
        "limit": int(limit),
        "offset": int(offset),
        "total": total,
        "has_more": int(offset) + len(sessions) < total,
        "start": start_date,
        "end": end_date,
        "sessions": sessions,
    }
    if include_analytics:
        result["analytics"] = _analytics(conn, included, start_date, end_date)
    return result
