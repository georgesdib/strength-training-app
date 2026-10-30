"""Raw longitudinal e1RM observations and descriptive trend points.

One point per session, exact exercise identity, no interpolation. The series applies no age
decay and no calibration; those belong only to the prescription load base.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from strength_coach.features import strength_observations
from strength_coach.store import queries
from strength_coach.utils import exercises


@dataclass(frozen=True)
class RawObservation:
    exercise_id: str
    session_id: str
    date: str
    estimate: strength_observations.RawEstimate
    load_basis: str | None = None
    raw_exercise: str | None = None


@dataclass(frozen=True)
class TrendPoint:
    date: str
    kg: float
    rolling_median_kg: float
    n_window: int


@dataclass(frozen=True)
class Break:
    date: str
    reason: str


def _excluded_sets(conn) -> dict[int, str]:
    return {
        int(row["set_id"]): str(row["kind"])
        for row in conn.execute(
            "SELECT set_id, kind FROM high_intensity_exposure WHERE set_id IS NOT NULL"
        )
    }


def _session_ids(
    conn,
    from_date: str,
    to_date: str,
    session_type: str | None,
    include_deloads: bool,
) -> set[str] | None:
    sessions = queries.sessions(conn, start=from_date, end=to_date)
    if sessions.empty:
        return set()
    allowed: set[str] = set()
    for _, row in sessions.iterrows():
        if session_type and str(row.get("session_type")) != session_type:
            continue
        flags = row.get("flags")
        if not include_deloads:
            try:
                parsed = json.loads(flags) if isinstance(flags, str) else (flags or [])
            except (TypeError, ValueError):
                parsed = str(flags or "").split(";")
            if "deload" in {str(item) for item in parsed}:
                continue
        allowed.add(str(row["session_id"]))
    return allowed


def _best_with_quality(
    group: pd.DataFrame,
    session_id: str,
    exercise_id: str,
    props: dict[str, Any],
    excluded: dict[int, str],
    quality: str,
) -> strength_observations.RawEstimate | None:
    best = None
    for row in group.to_dict("records"):
        result = strength_observations.raw_set_e1rm(
            row, props, excluded_set_kinds=excluded
        )
        if isinstance(result, strength_observations.Unavailable):
            continue
        if result.quality != quality:
            continue
        if best is None or (result.kg, result.set_id or -1) > (best.kg, best.set_id or -1):
            best = result
    return best


def _observations(
    conn,
    exercise_id: str,
    from_date: str,
    to_date: str,
    *,
    quality: str,
    session_type: str | None,
    include_deloads: bool,
) -> list[RawObservation]:
    frame = queries.clean_sets(conn, start=from_date, end=to_date)
    if frame.empty:
        return []
    frame = frame[frame["exercise_id"].astype(str).eq(str(exercise_id))]
    if frame.empty:
        return []
    allowed = _session_ids(conn, from_date, to_date, session_type, include_deloads)
    if allowed is not None:
        frame = frame[frame["session_id"].astype(str).isin(allowed)]
    if frame.empty:
        return []
    entities = exercises.taxonomy().entities
    props = dict(entities.get(str(exercise_id), {}))
    excluded = _excluded_sets(conn)
    out: list[RawObservation] = []
    for session_id, group in frame.groupby("session_id", sort=True):
        best = _best_with_quality(group, str(session_id), exercise_id, props, excluded, quality)
        if best is None:
            continue
        row = group[group["set_id"].astype(int).eq(int(best.set_id))].head(1)
        load_basis = None if row.empty else str(row.iloc[0].get("load_basis") or "")
        raw_exercise = None if row.empty else str(row.iloc[0].get("raw_exercise") or "")
        out.append(RawObservation(
            exercise_id=exercise_id,
            session_id=str(session_id),
            date=best.occurred_on,
            estimate=best,
            load_basis=load_basis or None,
            raw_exercise=raw_exercise or None,
        ))
    out.sort(key=lambda item: (item.date, item.session_id))
    return out


def observations(
    conn,
    exercise_id: str,
    from_date: str,
    to_date: str,
    *,
    session_type: str | None = None,
    include_deloads: bool = True,
) -> list[RawObservation]:
    """Eligible ok session bests for one exact exercise in the date range."""
    return _observations(
        conn, exercise_id, from_date, to_date,
        quality=strength_observations.QUALITY_OK,
        session_type=session_type,
        include_deloads=include_deloads,
    )


def degraded_observations(
    conn,
    exercise_id: str,
    from_date: str,
    to_date: str,
    *,
    session_type: str | None = None,
    include_deloads: bool = True,
) -> list[RawObservation]:
    """Degraded session bests, kept out of the primary line and median."""
    return _observations(
        conn, exercise_id, from_date, to_date,
        quality=strength_observations.QUALITY_DEGRADED,
        session_type=session_type,
        include_deloads=include_deloads,
    )


def rolling_median(
    points: list[RawObservation],
    n: int = 3,
) -> list[TrendPoint]:
    if not points:
        return []
    out: list[TrendPoint] = []
    for index, point in enumerate(points):
        window = points[max(0, index - n + 1):index + 1]
        values = sorted(item.estimate.kg for item in window)
        middle = len(values) // 2
        median = (
            values[middle]
            if len(values) % 2
            else (values[middle - 1] + values[middle]) / 2.0
        )
        out.append(TrendPoint(point.date, point.estimate.kg, float(median), len(window)))
    return out


def series_breaks(points: list[RawObservation], taxonomy: Any = None) -> list[Break]:
    """Explicit identity/load-basis markers; equipment is not stored and is not inferred."""
    if not points:
        return []
    breaks: list[Break] = []
    for previous, current in zip(points, points[1:], strict=False):
        reasons = []
        if previous.raw_exercise and current.raw_exercise and previous.raw_exercise != current.raw_exercise:
            reasons.append("raw exercise identity changed")
        if previous.load_basis and current.load_basis and previous.load_basis != current.load_basis:
            reasons.append("load basis changed")
        if reasons:
            breaks.append(Break(current.date, "; ".join(reasons)))
    return breaks


def summarize(points: list[RawObservation]) -> dict[str, Any]:
    if not points:
        return {"n": 0, "status": "unavailable", "latest": None, "recent_median_kg": None}
    values = [point.estimate.kg for point in points]
    recent = values[-3:]
    recent_median = sorted(recent)[len(recent) // 2] if len(recent) % 2 else (
        (sorted(recent)[len(recent) // 2 - 1] + sorted(recent)[len(recent) // 2]) / 2.0
    )
    status = "points_only" if len(points) < 3 else (
        "limited" if len(points) < 5 else "descriptive"
    )
    return {
        "n": len(points),
        "status": status,
        "latest": {"date": points[-1].date, "kg": round(values[-1], 1)},
        "recent_median_kg": round(recent_median, 1),
        "change_from_median_kg": round(values[-1] - recent_median, 1),
        "trend_statement": None if len(points) < 5 else "descriptive rolling median available",
    }
