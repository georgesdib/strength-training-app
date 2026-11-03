"""Group session fragments into one training day.

A training day is virtual: fragments are existing `session` rows sharing `occurred_on`.
They are never merged or renumbered. Attendance, scheduling and day-level reports read this
grouping instead of counting fragments as separate sessions.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from strength_coach.store import queries


def _json_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _prescription_types(conn, sessions: pd.DataFrame) -> dict[str, str]:
    if sessions.empty or "prescription_id" not in sessions:
        return {}
    ids = sorted({
        str(value) for value in sessions["prescription_id"].dropna().unique()
        if str(value)
    })
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT prescription_id, session_type FROM prescription "
        f"WHERE prescription_id IN ({placeholders})",
        ids,
    ).fetchall()
    return {str(row["prescription_id"]): str(row["session_type"]) for row in rows}


def _day(fragments: list[dict[str, Any]], prescription_types: dict[str, str],
         exercises: set[str]) -> dict[str, Any]:
    for row in fragments:
        row["occurred_on"] = str(row.get("occurred_on") or "")[:10]
    active = [row for row in fragments if not int(row.get("voided") or 0)]
    fragments = sorted(
        fragments,
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("session_id") or "")),
    )
    types = {str(row.get("session_type") or "") for row in active}
    types.discard("")
    planned = {
        prescription_types[str(row["prescription_id"])]
        for row in active
        if row.get("prescription_id") in prescription_types
    }
    duration_values = [
        float(row["duration_min"]) for row in active
        if row.get("duration_min") is not None
    ]
    bases = {
        str(row.get("duration_basis") or "") for row in active
        if row.get("duration_min") is not None
    }
    duration_basis = None
    if bases:
        duration_basis = bases.pop() if len(bases) == 1 else "mixed"
    main_lifts: list[str] = []
    flags: list[str] = []
    for row in active:
        for exercise in _json_list(row.get("main_lifts")):
            if exercise not in main_lifts:
                main_lifts.append(exercise)
        for flag in _json_list(row.get("flags")):
            if flag not in flags:
                flags.append(flag)
    return {
        "occurred_on": str(fragments[0].get("occurred_on") or "")[:10],
        "session_type": next(iter(types)) if len(types) == 1 else (
            "mixed" if types else ("voided" if fragments else "unknown")
        ),
        "planned_type": next(iter(planned)) if len(planned) == 1 else (
            next(iter(types)) if len(types) == 1 else None
        ),
        "fragment_count": len(fragments),
        "active_fragment_count": len(active),
        "fragments": fragments,
        "set_count": sum(int(row.get("set_count") or 0) for row in active),
        "working_set_count": sum(int(row.get("working_set_count") or 0) for row in active),
        "exercise_count": len(exercises),
        "tonnage_kg": round(sum(float(row.get("tonnage_kg") or 0) for row in active), 2),
        "duration_min": round(sum(duration_values), 2) if duration_values else None,
        "duration_basis": duration_basis,
        "main_lifts": main_lifts,
        "flags": flags,
        "prescription_ids": sorted({
            str(row["prescription_id"]) for row in active
            if row.get("prescription_id")
        }),
        "workout_ids": sorted({
            str(row["workout_id"]) for row in active if row.get("workout_id")
        }),
        "sources": sorted({
            str(row.get("source") or "") for row in active if row.get("source")
        }),
    }


def _day_exercises(conn, *, start: str | None, end: str | None) -> dict[str, set[str]]:
    clauses = [
        "cs.voided = 0",
        "NOT EXISTS (SELECT 1 FROM clean_set child WHERE child.supersedes_id = cs.set_id)",
        "EXISTS (SELECT 1 FROM session s WHERE s.session_id = cs.session_id AND s.voided = 0)",
    ]
    params: list[Any] = []
    if start is not None:
        clauses.append("cs.occurred_on >= ?")
        params.append(start)
    if end is not None:
        clauses.append("cs.occurred_on <= ?")
        params.append(end)
    rows = conn.execute(
        "SELECT DISTINCT cs.occurred_on, cs.exercise_id FROM clean_set cs WHERE "
        + " AND ".join(clauses),
        params,
    ).fetchall()
    out: dict[str, set[str]] = {}
    for row in rows:
        out.setdefault(str(row["occurred_on"])[:10], set()).add(str(row["exercise_id"]))
    return out


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert pandas rows without leaking NaN into JSON responses.

    ``json.dumps`` accepts NaN by default but browsers' JSON.parse does not. A missing
    prescription/workout id must be null, not an unquoted NaN token.
    """
    records = []
    for raw in frame.to_dict("records"):
        row = dict(raw)
        for key, value in row.items():
            try:
                if bool(pd.isna(value)):
                    row[key] = None
            except (TypeError, ValueError):
                # Non-scalar values (for example a list column) are already JSON-safe.
                pass
        records.append(row)
    return records


def group(conn, *, start: str | None = None, end: str | None = None,
          include_voided: bool = False, with_exercises: bool = True) -> list[dict[str, Any]]:
    """Training days in ascending date order, each with its fragments.

    ``with_exercises`` is off for scheduling, where the distinct-exercise scan is not needed
    and would run once per forecast entry.
    """
    sessions = queries.sessions(
        conn, start=start, end=end, include_voided=include_voided
    )
    if sessions.empty:
        return []
    prescriptions = _prescription_types(conn, sessions)
    exercises = _day_exercises(conn, start=start, end=end) if with_exercises else {}
    days: list[dict[str, Any]] = []
    for occurred_on, group_frame in sessions.groupby("occurred_on", sort=True):
        fragments = _records(group_frame)
        day_key = str(occurred_on)[:10]
        day = _day(fragments, prescriptions, exercises.get(day_key, set()))
        day["occurred_on"] = day_key
        days.append(day)
    return days
