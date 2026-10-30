"""Descriptive comparable-session summary.

The key is deliberately narrow: same session type, at least one common main lift, meaningful
exercise overlap, recent enough, and at least three prior comparable sessions. The result is a
median of prior sessions, not a prediction or a target.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from strength_coach.features import exposure, monitoring
from strength_coach.store import queries


def _flags(value: Any) -> set[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = value.split(";")
        return {str(item) for item in parsed}
    return {str(item) for item in (value or [])}


def _main_lifts(value: Any) -> set[str]:
    if isinstance(value, str):
        try:
            return {str(item) for item in json.loads(value)}
        except (TypeError, ValueError):
            return set()
    return {str(item) for item in (value or [])}


def _session_metrics(sets: pd.DataFrame, session_id: str) -> dict[str, Any]:
    work = sets[sets["session_id"].astype(str).eq(str(session_id))]
    work = work[work["is_working_set"].fillna(False).astype(bool)] if not work.empty else work
    tonnage = pd.to_numeric(work.get("tonnage_kg"), errors="coerce").dropna().sum() if not work.empty else 0.0
    return {
        "session_id": str(session_id),
        "working_sets": int(len(work)),
        "hard_sets": monitoring.hard_sets(work, exposure.ExposureConfig.load()),
        "tonnage_kg": round(float(tonnage), 1),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    return float(ordered[middle]) if len(ordered) % 2 else (
        float(ordered[middle - 1] + ordered[middle]) / 2.0
    )


def comparable_sessions(
    conn,
    session_id: str,
    *,
    window_days: int = 56,
    min_overlap: float = 0.50,
    min_prior_sessions: int = 3,
) -> dict[str, Any]:
    sessions = queries.sessions(conn)
    if sessions.empty:
        return {"status": "unavailable", "reason": "no sessions", "n": 0}
    current_rows = sessions[sessions["session_id"].astype(str).eq(str(session_id))]
    if current_rows.empty:
        return {"status": "unavailable", "reason": "session not found", "n": 0}
    current = current_rows.iloc[0]
    current_date = pd.Timestamp(current["occurred_on"])
    current_type = str(current["session_type"])
    current_flags = _flags(current.get("flags"))
    if current_flags & {"deload", "technique", "minimum"} or current_type in {"technique"}:
        return {"status": "unavailable", "reason": "excluded session type", "n": 0}

    sets = queries.clean_sets(conn)
    if sets.empty:
        return {"status": "unavailable", "reason": "no sets", "n": 0}
    current_exercises = {
        str(value) for value in sets[
            sets["session_id"].astype(str).eq(str(session_id))
            & sets["is_working_set"].fillna(False).astype(bool)
        ]["exercise_id"]
    }
    current_main = _main_lifts(current.get("main_lifts"))
    prior: list[tuple[pd.Series, float]] = []
    for _, row in sessions.iterrows():
        sid = str(row["session_id"])
        if sid == str(session_id):
            continue
        date = pd.Timestamp(row["occurred_on"])
        if date >= current_date or (current_date - date).days > window_days:
            continue
        if str(row["session_type"]) != current_type:
            continue
        flags = _flags(row.get("flags"))
        if flags & {"deload", "technique", "minimum"}:
            continue
        if not (current_main & _main_lifts(row.get("main_lifts"))):
            continue
        other = sets[sets["session_id"].astype(str).eq(sid)]
        other_exercises = {
            str(value) for value in other[
                other["is_working_set"].fillna(False).astype(bool)
            ]["exercise_id"]
        }
        if not current_exercises:
            continue
        overlap = len(current_exercises & other_exercises) / len(current_exercises)
        if overlap < min_overlap:
            continue
        prior.append((row, overlap))

    if len(prior) < min_prior_sessions:
        return {
            "status": "unavailable",
            "reason": "fewer than three comparable prior sessions",
            "n": len(prior),
        }
    metrics = [_session_metrics(sets, str(row["session_id"])) for row, _ in prior]
    return {
        "status": "available",
        "n": len(metrics),
        "key": "same_type+main_lift+overlap",
        "window_days": window_days,
        "min_overlap": min_overlap,
        "metrics": {
            "working_sets": _median([item["working_sets"] for item in metrics]),
            "hard_sets": _median([item["hard_sets"] for item in metrics]),
            "tonnage_kg": _median([item["tonnage_kg"] for item in metrics]),
        },
        "sessions": metrics,
    }
