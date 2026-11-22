"""Per-set heart-rate recovery: computed to be shown, never to be decided on.

The measurement on 2026-11-22 rejected this as a feature. On 4 watch sessions and 64 matched
sets the delta between the end of a set and one minute later tracked set duration (-0.57) and
load (+0.51), and its within-session spread (12.8 bpm) was nearly twice its between-session
spread (7.1 bpm). It is computed here only so the number can appear next to the set that
produced it, carrying its own caveat; nothing reads it back into planning, readiness or
prescriptions. `tools/hr_recovery_probe.py` is the reporting layer over this module.

A value is measured or absent. Nothing is interpolated: both the end-of-set sample and the
one-minute sample must exist inside tolerance, otherwise the set reports no value.
"""

from __future__ import annotations

import datetime as dt
import statistics
from typing import Any

#: A sample this close to the set-completion tap counts as the end-of-set value.
END_TOLERANCE_S = 10.0
#: The +60 s endpoint is matched to the nearest sample within this window.
SIXTY_TOLERANCE_S = 15.0
#: Decision-rule bars, kept here so the probe and the Today card cannot disagree.
COVERAGE_BAR = 0.70
CONFOUND_BAR = 0.40
ASSOCIATION_BAR = 0.30
MIN_SETS_FOR_CORRELATION = 30
#: Corpus size below which the Today prompt waits instead of asking for a review.
MIN_SESSIONS = 15
#: Shown beside every value; the number is not a recovery capacity measure.
CAVEAT = "tracks set duration and load; not a recovery measure"


def _epoch(text: str) -> float:
    """Aware ISO-8601 text to a POSIX timestamp."""
    return dt.datetime.fromisoformat(text).timestamp()


def _endpoint(series: list[tuple[float, float]], target: float, tolerance: float) -> float | None:
    """Last sample at or before `target` within `tolerance` seconds, else None."""
    candidates = [item for item in series if 0 <= target - item[0] <= tolerance]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _nearest(series: list[tuple[float, float]], target: float, tolerance: float) -> float | None:
    """Value of the sample nearest `target` within `tolerance` seconds, else None."""
    candidates = [item for item in series if abs(item[0] - target) <= tolerance]
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item[0] - target))[1]


def series(conn, session_id: str) -> list[tuple[float, float]]:
    """Heart-rate series for a session, ordered, from the workouts currently linked to it.

    Reads the workout interval and the ten-minute recovery tail: a late set can sit past the
    workout's own `ended_at`, and those are exactly the samples a recovery number needs. The
    linked workout ids are resolved first so the sample read stays on the
    (external_workout_id, sampled_at) index instead of scanning the corpus.
    """
    workout_ids = [
        row["external_workout_id"]
        for row in conn.execute(
            """
            SELECT DISTINCT l.external_workout_id
              FROM workout_link l
             WHERE l.session_id = ?
               AND l.action = 'link'
               AND NOT EXISTS (
                   SELECT 1 FROM workout_link u
                    WHERE u.action = 'unlink' AND u.supersedes_id = l.link_id
               )
            """,
            (str(session_id),),
        )
    ]
    if not workout_ids:
        return []
    marks = ",".join("?" * len(workout_ids))
    rows = conn.execute(
        f"""
        SELECT s.sampled_at, s.value
          FROM health_sample s
          JOIN external_workout w ON w.external_workout_id = s.external_workout_id
         WHERE s.kind = 'heart_rate'
           AND s.external_workout_id IN ({marks})
           AND (s.sampled_at BETWEEN w.started_at AND w.ended_at OR s.association = 'tail')
         ORDER BY s.sampled_at
        """,
        tuple(workout_ids),
    ).fetchall()
    return [(_epoch(row["sampled_at"]), float(row["value"])) for row in rows]


def _completions(conn, workout_id: str) -> dict[int, float]:
    """Set-completion time per workout set, keyed by workout_set.set_id."""
    rows = conn.execute(
        "SELECT set_id, occurred_at FROM workout_execution_event "
        "WHERE workout_id = ? AND event_type = 'set_completed' AND set_id IS NOT NULL "
        "ORDER BY occurred_at",
        (workout_id,),
    ).fetchall()
    return {int(row["set_id"]): _epoch(row["occurred_at"]) for row in rows}


def _clean_to_workout_sets(conn, session_id: str, workout_id: str) -> dict[int, int]:
    """Current clean set id -> its workout set id, through the materialisation row.

    A completed workout materialises each `workout_set` into a `raw_row` whose `source_row`
    is that set id; corrections supersede the clean row, and the leaf is the one that counts, so
    this mirrors `queries.session_clean_sets`.
    """
    rows = conn.execute(
        """
        SELECT c.set_id AS clean_set_id, rr.source_row AS workout_set_id
          FROM clean_set c
          JOIN raw_row rr ON rr.raw_id = c.raw_id
          JOIN workout_set w ON w.set_id = rr.source_row
         WHERE c.session_id = ?
           AND rr.table_name = 'training'
           AND w.workout_id = ?
           AND NOT EXISTS (SELECT 1 FROM clean_set child
                            WHERE child.supersedes_id = c.set_id)
        """,
        (str(session_id), str(workout_id)),
    ).fetchall()
    return {int(row["clean_set_id"]): int(row["workout_set_id"]) for row in rows}


def set_deltas(conn, session_id: str) -> dict[int, dict[str, Any]]:
    """Recovery value per current clean set id, for the sets that have both endpoints."""
    session = conn.execute(
        "SELECT workout_id FROM session WHERE session_id = ?", (str(session_id),)
    ).fetchone()
    workout_id = session["workout_id"] if session is not None else None
    if not workout_id:
        return {}
    series_rows = series(conn, session_id)
    if not series_rows:
        return {}
    completions = _completions(conn, str(workout_id))
    mapping = _clean_to_workout_sets(conn, session_id, str(workout_id))
    out: dict[int, dict[str, Any]] = {}
    for clean_set_id, workout_set_id in mapping.items():
        finished_at = completions.get(workout_set_id)
        if finished_at is None:
            continue
        hr_end = _endpoint(series_rows, finished_at, END_TOLERANCE_S)
        hr_60 = _nearest(series_rows, finished_at + 60.0, SIXTY_TOLERANCE_S)
        if hr_end is None or hr_60 is None:
            continue
        out[clean_set_id] = {
            "bpm": round(hr_end - hr_60),
            "hr_end_bpm": round(hr_end),
            "basis": "hr_at_60s",
        }
    return out


def _sessions_with_telemetry(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT e.workout_id
          FROM workout_execution_event e
         WHERE e.event_type = 'set_completed'
           AND EXISTS (
                 SELECT 1 FROM workout_link l
                  WHERE l.action = 'link'
                    AND (l.session_id = e.workout_id
                         OR l.session_id IN (
                              SELECT s.session_id FROM session s
                               WHERE s.workout_id = e.workout_id))
               )
         ORDER BY e.workout_id
        """
    ).fetchall()
    return [str(row["workout_id"]) for row in rows]


def _corr(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, or None when the sample is too small or has no variation."""
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return numerator / (dx * dy)



def completion_deltas(conn, session_id: str) -> list[dict[str, Any]]:
    """Recovery value per set-completion event, in performed order.

    This is the corpus measurement: it follows the user's taps, so it survives a later session
    edit that breaks the clean-set materialisation link. The display path uses `set_deltas`,
    which is stricter because it must name the set it decorates.
    """
    row = conn.execute(
        "SELECT workout_id FROM session WHERE session_id = ?", (str(session_id),)
    ).fetchone()
    workout_id = row["workout_id"] if row is not None else None
    if not workout_id:
        return []
    series_rows = series(conn, session_id)
    if not series_rows:
        return []
    events = conn.execute(
        "SELECT set_id, occurred_at FROM workout_execution_event "
        "WHERE workout_id = ? AND event_type = 'set_completed' ORDER BY occurred_at",
        (str(workout_id),),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for event in events:
        finished_at = _epoch(event["occurred_at"])
        hr_end = _endpoint(series_rows, finished_at, END_TOLERANCE_S)
        hr_60 = _nearest(series_rows, finished_at + 60.0, SIXTY_TOLERANCE_S)
        if hr_end is None or hr_60 is None:
            continue
        out.append(
            {
                "workout_set_id": None if event["set_id"] is None else int(event["set_id"]),
                "bpm": round(hr_end - hr_60),
                "hr_end_bpm": round(hr_end),
            }
        )
    return out


def _loads_by_workout_set(conn, workout_id: str) -> dict[int, float]:
    """Load per workout set, for the confound check only."""
    rows = conn.execute(
        "SELECT set_id, load_kg FROM workout_set WHERE workout_id = ? AND load_kg IS NOT NULL",
        (str(workout_id),),
    ).fetchall()
    return {int(row["set_id"]): float(row["load_kg"]) for row in rows}


def report(conn) -> dict[str, Any]:
    """Corpus aggregates and the pre-registered verdict, for the Today card and the probe."""
    values: list[float] = []
    medians: list[float] = []
    within: list[float] = []
    load_pairs: list[tuple[float, float]] = []
    completions_total = 0
    sessions_with_deltas = 0
    session_ids = _sessions_with_telemetry(conn)
    for session_id in session_ids:
        row = conn.execute(
            "SELECT workout_id FROM session WHERE session_id = ?", (session_id,)
        ).fetchone()
        workout_id = row["workout_id"] if row is not None else None
        if not workout_id:
            continue
        events = conn.execute(
            "SELECT COUNT(*) AS n FROM workout_execution_event "
            "WHERE workout_id = ? AND event_type = 'set_completed'",
            (str(workout_id),),
        ).fetchone()["n"]
        completions_total += int(events)
        deltas = completion_deltas(conn, session_id)
        if not deltas:
            continue
        sessions_with_deltas += 1
        session_values = [item["bpm"] for item in deltas]
        values.extend(session_values)
        medians.append(statistics.median(session_values))
        if len(session_values) > 2:
            within.append(statistics.pstdev(session_values))
        loads = _loads_by_workout_set(conn, str(workout_id))
        load_pairs.extend(
            (item["bpm"], loads[item["workout_set_id"]])
            for item in deltas
            if item["workout_set_id"] in loads
        )

    coverage = (len(values) / completions_total) if completions_total else 0.0
    within_sd = round(statistics.median(within), 1) if within else None
    between_sd = round(statistics.pstdev(medians), 1) if len(medians) > 1 else None
    corr_load = _corr([pair[0] for pair in load_pairs], [pair[1] for pair in load_pairs])
    verdict: list[str] = []
    if coverage < COVERAGE_BAR:
        verdict.append("fail: endpoints missing for too many sets")
    if within_sd is not None and between_sd is not None and within_sd >= between_sd:
        verdict.append("fail: within-session noise exceeds the between-session signal")
    if corr_load is not None and abs(corr_load) > CONFOUND_BAR:
        verdict.append("fail: delta tracks load, which the prescription already knows")
    return {
        "sessions": len(session_ids),
        "sessions_with_deltas": sessions_with_deltas,
        "sets_matched": len(values),
        "set_completions": completions_total,
        "coverage": round(coverage, 3),
        "median_bpm": round(statistics.median(values), 1) if values else None,
        "within_session_sd": within_sd,
        "between_session_sd": between_sd,
        "corr_load": round(corr_load, 3) if corr_load is not None else None,
        "min_sessions": MIN_SESSIONS,
        "verdict": verdict or ["pass: every decision bar cleared; revisit the feature question"],
        "worth_pursuing": not verdict,
        "caveat": CAVEAT,
    }

