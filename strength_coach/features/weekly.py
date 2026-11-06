"""Weekly RIR, tonnage and VBT residual history for Progress.

This is a descriptive report over stored clean sets. It never fills a missing week and never
mixes units: tonnage is kg, RIR is unitless, residuals are m/s.
"""

from __future__ import annotations

import datetime as dt
import statistics

from strength_coach.features import exposure, residual


def _weeks(start: dt.date, end: dt.date) -> list[dt.date]:
    first = start - dt.timedelta(days=start.weekday())
    last = end - dt.timedelta(days=end.weekday())
    out = []
    cursor = first
    while cursor <= last:
        out.append(cursor)
        cursor += dt.timedelta(days=7)
    return out


def history(conn, on_date: str, *, weeks: int = 12) -> dict:
    if weeks < 1 or weeks > 52:
        raise ValueError("weeks must be an integer from 1 to 52")
    end = dt.date.fromisoformat(str(on_date)[:10])
    # Include the current (possibly partial) week and the preceding weeks.
    start = end - dt.timedelta(days=7 * (weeks - 1))
    rows = conn.execute(
        """
        SELECT occurred_on, session_id, rir, tonnage_kg, is_working_set
          FROM clean_set
         WHERE occurred_on BETWEEN ? AND ?
           AND voided = 0
           AND NOT EXISTS (SELECT 1 FROM session sess
                           WHERE sess.session_id = clean_set.session_id AND sess.voided = 1)
           AND NOT EXISTS (SELECT 1 FROM clean_set child
                           WHERE child.supersedes_id = clean_set.set_id)
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    effort_max = exposure.ExposureConfig.load().effort_max_rir
    by_week: dict[str, dict] = {}
    for row in rows:
        day = dt.date.fromisoformat(str(row["occurred_on"])[:10])
        key = (day - dt.timedelta(days=day.weekday())).isoformat()
        item = by_week.setdefault(key, {
            "dates": set(), "working": 0, "hard": 0, "rir_values": [],
            "tonnage_values": [], "working_with_tonnage": 0,
        })
        item["dates"].add(day.isoformat())
        if not bool(row["is_working_set"]):
            continue
        item["working"] += 1
        rir = row["rir"]
        if rir is not None:
            item["rir_values"].append(float(rir))
            if float(rir) <= effort_max:
                item["hard"] += 1
        if row["tonnage_kg"] is not None:
            item["tonnage_values"].append(float(row["tonnage_kg"]))
            item["working_with_tonnage"] += 1

    residual_by_week = {
        row["week_start"]: row for row in residual.weekly_history(conn, start.isoformat(), end.isoformat())
    }
    week_starts = _weeks(start, end)
    observed = set(by_week) | set(residual_by_week)
    output = []
    for monday in week_starts:
        key = monday.isoformat()
        item = by_week.get(key)
        residual_row = residual_by_week.get(key)
        if item is None and residual_row is None:
            continue
        end_day = min(monday + dt.timedelta(days=6), end)
        rir_values = [] if item is None else item["rir_values"]
        tonnage_values = [] if item is None else item["tonnage_values"]
        working = 0 if item is None else item["working"]
        output.append({
            "week_start": key,
            "week_end": end_day.isoformat(),
            "observed_days": 0 if item is None else len(item["dates"]),
            "working_sets": working,
            "hard_sets": 0 if item is None else item["hard"],
            "rir": {
                "observed_sets": len(rir_values),
                "coverage": round(len(rir_values) / working, 3) if working else None,
                "mean": round(statistics.fmean(rir_values), 2) if rir_values else None,
            },
            "tonnage_kg": round(sum(tonnage_values), 2) if tonnage_values else None,
            "tonnage": {
                "observed_sets": len(tonnage_values),
                "coverage": round(len(tonnage_values) / working, 3) if working else None,
            },
            "residual": residual_row if residual_row else None,
        })
    missing = [monday.isoformat() for monday in week_starts if monday.isoformat() not in observed]
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "weeks": output,
        "missing_weeks": missing,
        "note": "Descriptive weekly history; missing weeks remain missing and units are separate.",
    }
