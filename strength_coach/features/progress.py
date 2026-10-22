"""Small descriptive progress dashboard.

This is monitoring, not inference: it reports coverage, a lagged performance ratio, weekly
hard-set volume and the latest back symptom. Nothing here changes a prescription.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.features import volume as volume_feature
from strength_coach.store import queries


def _session_lift_e1rms(conn) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    cursor = conn.execute(
        """
        SELECT session_id, occurred_on, exercise_id, load_kg, reps, rir
          FROM clean_set
         WHERE is_working_set = 1 AND load_kg IS NOT NULL AND load_kg > 0
           AND reps BETWEEN 1 AND 20
        """
    )
    columns = [description[0] for description in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    best: dict[str, dict[str, float]] = defaultdict(dict)
    dates: dict[str, str] = {}
    for row in rows:
        estimate = e1rm_mod.estimate_e1rm(
            float(row["load_kg"]), int(row["reps"]),
            int(row["rir"]) if row["rir"] is not None else None,
        )
        if estimate is None or not estimate.is_usable:
            continue
        sid = str(row["session_id"])
        exercise = str(row["exercise_id"])
        best[sid][exercise] = max(best[sid].get(exercise, 0.0), estimate.value_kg)
        dates[sid] = str(row["occurred_on"])
    return best, dates


def performance_points(conn, on_date: str, *, lookback_days: int = 56) -> list[dict]:
    """Median session e1RM ratio versus the prior 84-day best for the same lift."""
    best, dates = _session_lift_e1rms(conn)
    history: dict[str, list[tuple[dt.date, float]]] = defaultdict(list)
    for sid, exercises in best.items():
        day = dt.date.fromisoformat(dates[sid])
        for exercise, value in exercises.items():
            history[exercise].append((day, value))
    for exercise in history:
        history[exercise].sort()
    cutoff = dt.date.fromisoformat(on_date) - dt.timedelta(days=lookback_days)
    points = []
    for sid, exercises in best.items():
        day = dt.date.fromisoformat(dates[sid])
        if not (cutoff <= day <= dt.date.fromisoformat(on_date)):
            continue
        ratios = []
        for exercise, actual in exercises.items():
            prior = [
                value for prior_day, value in history[exercise]
                if day - dt.timedelta(days=84) <= prior_day < day
            ]
            if prior:
                ratios.append(actual / max(prior))
        if ratios:
            points.append({
                "date": dates[sid],
                "ratio": round(statistics.median(ratios), 3),
                "lifts": len(ratios),
            })
    points.sort(key=lambda row: row["date"])
    return points


def dashboard(conn, on_date: str | None = None, *, weeks: int = 8) -> dict:
    day = on_date or dt.date.today().isoformat()
    sessions = conn.execute(
        "SELECT COUNT(*) AS n FROM session WHERE occurred_on <= ?", (day,)
    ).fetchone()[0]
    feedback = conn.execute(
        """
        SELECT COUNT(DISTINCT session_id) AS n
          FROM session_feedback
         WHERE srpe IS NOT NULL AND duration_min IS NOT NULL
        """
    ).fetchone()[0]
    points = performance_points(conn, day)
    latest = points[-1] if points else None
    median = statistics.median([p["ratio"] for p in points]) if points else None
    volume = volume_feature.compute(_sets(conn), on_date=day)
    symptom = queries.latest_symptom(conn, day)
    return {
        "on_date": day,
        "coverage": {
            "sessions": sessions,
            "with_srpe": feedback,
            "pct": round(100 * feedback / sessions, 1) if sessions else 0.0,
        },
        "performance": {
            "points": points[-12:],
            "latest": latest,
            "median_ratio": round(median, 3) if median is not None else None,
            "n": len(points),
        },
        "volume": [
            {"pattern": row["pattern"], "average": row["average"],
             "status": row["status"], "mrv": row["mrv"]}
            for row in volume["patterns"]
        ],
        "back": {
            "level": symptom["level"] if symptom else None,
            "date": symptom["logged_on"] if symptom else None,
        },
        "note": "Descriptive monitoring only; no prescription change.",
    }


def _sets(conn):
    import pandas as pd
    cursor = conn.execute(
        """
        SELECT occurred_on AS date, session_id, exercise_id, load_kg, reps, rir,
               is_working_set
          FROM clean_set
        """
    )
    columns = [description[0] for description in cursor.description]
    return pd.DataFrame([dict(zip(columns, row)) for row in cursor.fetchall()])
