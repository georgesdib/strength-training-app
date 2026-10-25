"""Read-only form-rating trends and review context.

The ratings are post-lift self-assessments (1=worst, 5=best). They feed the rubric, but this
module only describes them; nothing here changes a prescription.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict
from typing import Any

WEEKS = (4, 8, 12)
CHANGE_THRESHOLD = 0.5   # practical display threshold, not a validated cut-point
EVALUATION_START = dt.date(2026, 10, 25)
EVALUATION_WEEKS = 12
EVALUATION_EXTENSION_WEEKS = 24
LOW_FORM_TARGET = 10
LOW_FORM_LIFT_TARGET = 4


def _window(on_date: str | None, weeks: int) -> tuple[dt.date, dt.date, dt.date, dt.date]:
    if weeks not in WEEKS:
        raise ValueError("weeks must be 4, 8 or 12")
    end = dt.date.fromisoformat(on_date) if on_date else dt.date.today()
    current_start = end - dt.timedelta(days=7 * weeks - 1)
    baseline_end = current_start - dt.timedelta(days=1)
    baseline_start = baseline_end - dt.timedelta(days=7 * weeks - 1)
    return baseline_start, baseline_end, current_start, end


def _ratings(conn, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT f.session_id, s.occurred_on, f.exercise_id, f.rating, f.form_id "
        "FROM session_form_rating f JOIN session s ON s.session_id = f.session_id "
        "WHERE s.occurred_on BETWEEN ? AND ? AND NOT EXISTS ("
        "SELECT 1 FROM session_form_rating child WHERE child.supersedes_id = f.form_id) "
        "ORDER BY s.occurred_on, f.form_id",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return [dict(row) for row in rows]


def _values(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[str(row["exercise_id"])].append(row)
    return out


def _status(current_n: int, baseline_n: int, change: float | None) -> str:
    if current_n < 2 or baseline_n < 2 or change is None:
        return "insufficient"
    if change >= CHANGE_THRESHOLD:
        return "up"
    if change <= -CHANGE_THRESHOLD:
        return "down"
    return "stable"


def report(conn, *, weeks: int = 12, on_date: str | None = None) -> dict:
    baseline_start, baseline_end, current_start, end = _window(on_date, weeks)
    current = _values(_ratings(conn, current_start, end))
    baseline = _values(_ratings(conn, baseline_start, baseline_end))
    rows = []
    for exercise_id in sorted(set(current) | set(baseline)):
        current_rows = current.get(exercise_id, [])
        baseline_rows = baseline.get(exercise_id, [])
        current_values = [float(row["rating"]) for row in current_rows]
        baseline_values = [float(row["rating"]) for row in baseline_rows]
        change = None
        if current_values and baseline_values:
            change = round(statistics.mean(current_values) - statistics.mean(baseline_values), 2)
        latest = current_rows[-1] if current_rows else baseline_rows[-1]
        rows.append({
            "exercise_id": exercise_id,
            "current_n": len(current_values),
            "baseline_n": len(baseline_values),
            "low_current": sum(1 for value in current_values if value <= 2),
            "low_baseline": sum(1 for value in baseline_values if value <= 2),
            "current_avg": round(statistics.mean(current_values), 2) if current_values else None,
            "baseline_avg": round(statistics.mean(baseline_values), 2) if baseline_values else None,
            "change": change,
            "status": _status(len(current_values), len(baseline_values), change),
            "latest_rating": int(latest["rating"]),
            "latest_on": str(latest["occurred_on"])[:10],
        })
    return {
        "window": {
            "weeks": weeks,
            "baseline_from": baseline_start.isoformat(),
            "baseline_to": baseline_end.isoformat(),
            "current_from": current_start.isoformat(),
            "current_to": end.isoformat(),
        },
        "forms": rows,
        "low_form_events": sum(row["low_current"] for row in rows),
        "low_form_lifts": sum(1 for row in rows if row["low_current"] > 0),
        "note": "Descriptive form ratings (1=worst, 5=best). No load or prescription effect.",
    }


def followup(conn, *, as_of: str | None = None) -> dict:
    """Cumulative status of the prospective form evaluation, for the Today page."""
    day = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    window_end = EVALUATION_START + dt.timedelta(days=7 * EVALUATION_WEEKS)
    extension_end = EVALUATION_START + dt.timedelta(days=7 * EVALUATION_EXTENSION_WEEKS)
    rows = conn.execute(
        "SELECT f.exercise_id, f.rating FROM session_form_rating f "
        "JOIN session s ON s.session_id = f.session_id "
        "WHERE s.occurred_on BETWEEN ? AND ? AND NOT EXISTS ("
        "SELECT 1 FROM session_form_rating child WHERE child.supersedes_id = f.form_id)",
        (EVALUATION_START.isoformat(), min(day, extension_end).isoformat()),
    ).fetchall()
    low = [row for row in rows if int(row["rating"]) <= 2]
    events = len(low)
    lifts = len({str(row["exercise_id"]) for row in low})
    if day < window_end:
        due = window_end
        if events >= LOW_FORM_TARGET and lifts >= LOW_FORM_LIFT_TARGET:
            status = "threshold_met_waiting"
            message = "Threshold met; wait for the 12-week window to close before analysis."
        else:
            status = "collecting"
            message = "Collecting low-form events."
    elif day < extension_end:
        if events >= LOW_FORM_TARGET and lifts >= LOW_FORM_LIFT_TARGET:
            due = window_end
            status = "ready"
            message = "Threshold met; run the descriptive analysis."
        else:
            due = extension_end
            status = "extended"
            message = "Below threshold at 12 weeks; extended to 24 weeks."
    else:
        due = None
        if events >= LOW_FORM_TARGET and lifts >= LOW_FORM_LIFT_TARGET:
            status = "ready"
            message = "Threshold met; run the descriptive analysis."
        else:
            status = "insufficient"
            message = "Insufficient low-form events; keep descriptive and do not analyse a handful."
    return {
        "status": status,
        "message": message,
        "started_on": EVALUATION_START.isoformat(),
        "window_end": window_end.isoformat(),
        "extension_end": extension_end.isoformat(),
        "due_on": due.isoformat() if due else None,
        "low_events": events,
        "low_lifts": lifts,
        "target_events": LOW_FORM_TARGET,
        "target_lifts": LOW_FORM_LIFT_TARGET,
        "note": "Follow-up only; form does not change a load or prescription.",
    }


def review_context(conn, session_id: str) -> dict:
    """Current ratings plus prior observations for the same lift, for the review sheet."""
    session = conn.execute(
        "SELECT occurred_on FROM session WHERE session_id = ?", (str(session_id),)
    ).fetchone()
    if session is None:
        return {"forms": []}
    current_rows = conn.execute(
        "SELECT exercise_id, rating FROM session_form_rating f WHERE f.session_id = ? "
        "AND NOT EXISTS (SELECT 1 FROM session_form_rating child "
        "WHERE child.supersedes_id = f.form_id) ORDER BY f.form_id",
        (str(session_id),),
    ).fetchall()
    out = []
    for current in current_rows:
        prior_rows = conn.execute(
            "SELECT s.occurred_on, f.rating FROM session_form_rating f "
            "JOIN session s ON s.session_id = f.session_id "
            "WHERE f.exercise_id = ? AND s.occurred_on < ? AND NOT EXISTS ("
            "SELECT 1 FROM session_form_rating child WHERE child.supersedes_id = f.form_id) "
            "ORDER BY s.occurred_on DESC, f.form_id DESC LIMIT 5",
            (str(current["exercise_id"]), str(session["occurred_on"])[:10]),
        ).fetchall()
        values = [int(row["rating"]) for row in prior_rows]
        out.append({
            "exercise_id": str(current["exercise_id"]),
            "rating": int(current["rating"]),
            "prior_n": len(values),
            "prior_avg": round(statistics.mean(values), 2) if values else None,
            "prior_latest": values[0] if values else None,
            "prior_latest_on": str(prior_rows[0]["occurred_on"])[:10] if prior_rows else None,
        })
    return {"forms": out}
