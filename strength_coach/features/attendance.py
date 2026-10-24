"""Descriptive attendance and exposure metrics.

Target-based, not planned adherence: the rolling programme does not persist a calendar. No
metric here can change a prescription.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter, defaultdict

from strength_coach.store import queries

FAMILIES = ("squat", "hinge", "bench")
BENCH_TYPES = {"bench_squat", "bench_hinge"}


def _family(session_type: str) -> str | None:
    if session_type in BENCH_TYPES:
        return "bench"
    if session_type in {"squat", "hinge"}:
        return session_type
    return None


def summary(conn, *, start: dt.date, end: dt.date, weeks: int,
            target_per_week: int | None = None) -> dict:
    sessions = queries.sessions(conn, start=start.isoformat(), end=end.isoformat())
    completed = int(len(sessions))
    if target_per_week is None:
        profile = queries.athlete_profile(conn) or {}
        target_per_week = profile.get("sessions_per_week_target")
    target = int(target_per_week) * weeks if target_per_week is not None else None
    types = Counter(str(value) for value in sessions["session_type"]) if not sessions.empty else Counter()
    families = Counter(
        _family(str(value)) for value in sessions["session_type"]
    ) if not sessions.empty else Counter()
    families.pop(None, None)

    duration_rows = []
    measured_rows = []
    if not sessions.empty and "duration_basis" in sessions:
        for row in sessions.itertuples(index=False):
            if getattr(row, "duration_min", None) is None:
                continue
            duration_rows.append(float(row.duration_min))
            if getattr(row, "duration_basis", None) == "measured":
                measured_rows.append(float(row.duration_min))

    symptoms = queries.symptom_entries(conn, since=start.isoformat())
    symptoms = [row for row in symptoms if str(row["logged_on"]) <= end.isoformat()]
    logged_weeks: dict[str, list[dict]] = defaultdict(list)
    for row in symptoms:
        stamp = dt.date.fromisoformat(str(row["logged_on"])[:10])
        logged_weeks[stamp.strftime("%G-W%V")].append(row)
    flare_weeks = set()
    for week, rows in logged_weeks.items():
        if any(int(row["level"]) >= 2 for row in rows):
            flare_weeks.add(week)
    # Injury-free is only reported when every week has symptom coverage; absent entries are
    # unknown, never "no flare".
    injury_free = (
        weeks - len(flare_weeks)
        if len(logged_weeks) >= weeks else None
    )

    return {
        "weeks": weeks,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "completed": completed,
        "target": target,
        "pct": round(100 * completed / target, 1) if target else None,
        "target_shortfall": max(0, target - completed) if target is not None else None,
        "completed_vs_planned": None,
        "completed_vs_planned_note": "no stored planned-session calendar",
        "families": {name: int(families.get(name, 0)) for name in FAMILIES},
        "session_types": dict(types),
        "duration": {
            "n": len(duration_rows),
            "mean_min": round(statistics.mean(duration_rows), 1) if duration_rows else None,
            "measured_n": len(measured_rows),
            "measured_mean_min": (
                round(statistics.mean(measured_rows), 1) if measured_rows else None
            ),
        },
        "symptom_weeks_logged": len(logged_weeks),
        "injury_free_weeks": injury_free,
        "note": "target-based attendance, not a stored plan; no prescription effect",
    }
