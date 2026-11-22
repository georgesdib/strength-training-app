#!/usr/bin/env python
"""Probe per-set heart-rate recovery for watch-owned strength sessions (read-only).

    python tools/hr_recovery_probe.py --db data/coach.db
    python tools/hr_recovery_probe.py --db data/coach.db --end-tolerance 10 --sixty-tolerance 15

Why this exists
---------------
It decides with measurement whether per-set heart-rate recovery is worth product work. It pairs
the watch execution telemetry (`workout_execution_event`, the user's set taps) with the
heart-rate samples already stored in `health_sample` and reports, in order, three things:

* whether both endpoints can be computed from what is stored (coverage);
* whether set-to-set variation leaves any room for a between-session signal;
* whether the number is explained by effort the prescription already knows (load, set duration).

What it is not
--------------
Not a feature, an endpoint or a migration. Nothing imports it, no table is written and the
database is opened read-only through a `file:...?mode=ro` URI. It is a throwaway probe: delete it
or re-run it once enough sessions accumulate.

Privacy
-------
Heart rate is health data. The probe prints aggregates only -- counts, medians, standard
deviations, correlations and verdicts. It never prints a sample, a timestamp or a session
identifier, so its output is safe to paste into an issue or a commit message. Run it on the host
that already holds the database; do not copy the database to a workstation to run it. Standard
library only, so it can be piped over ssh without installing anything:

    ssh odroid 'sudo -u dsh python3 - --db /path/to/coach.db' < tools/hr_recovery_probe.py

Decision rule
-------------
Fixed before the first run, so a re-run cannot be reinterpreted after the fact:

* coverage >= 0.70 -- both endpoints exist for most sets, else the idea is unbuildable;
* within-session SD < between-session SD -- else set-to-set noise *is* the metric;
* |corr(delta, load)| <= 0.40 and |corr(delta, set_duration)| <= 0.40 -- else the metric
  re-encodes how hard the set was, which the prescription already knows;
* |corr(delta, reps)| >= 0.30 -- else it says nothing the logged set does not.

The verdict is advisory, not a gate. Few sessions make the correlations unstable; the report
carries the session and set counts so a reader can weigh that themselves.

Baseline, 2026-11-22 (4 sessions, 71 sets): coverage 0.90, within-SD 12.8 bpm vs between-SD
7.1 bpm, corr(delta, load) +0.51, corr(delta, set_duration) -0.57, corr(delta, reps) -0.16.
Verdict: not worth pursuing. Re-run once there are 20+ sessions.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import statistics
import sys
from typing import Any

#: A sample this close to the set-completion tap counts as the end-of-set value.
DEFAULT_END_TOLERANCE_S = 10.0
#: The +60 s endpoint is matched to the nearest sample within this window.
DEFAULT_SIXTY_TOLERANCE_S = 15.0
#: Below this, the correlations are decoration and the report says so.
MIN_SETS_FOR_CORRELATION = 30
#: Decision-rule bars; see the module docstring.
COVERAGE_BAR = 0.70
CONFOUND_BAR = 0.40
ASSOCIATION_BAR = 0.30
#: Columns correlated against the per-set delta, in report order.
CONFOUND_COLUMNS = ("set_duration", "rest_duration", "load", "reps")


def _epoch(text: str) -> float:
    """Aware ISO-8601 text to a POSIX timestamp."""
    return dt.datetime.fromisoformat(text).timestamp()


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


def _samples(
    session_ids: list[str], conn: sqlite3.Connection
) -> dict[str, list[tuple[float, float]]]:
    """Heart-rate series per session, ordered, from the workouts linked to that session.

    Reads the workout interval and the ten-minute recovery tail: a late set can sit past the
    workout's own `ended_at`, and those samples are exactly the ones a recovery probe needs.
    """
    series: dict[str, list[tuple[float, float]]] = {session_id: [] for session_id in session_ids}
    for session_id in session_ids:
        linked = [
            row["external_workout_id"]
            for row in conn.execute(
                "SELECT DISTINCT external_workout_id FROM workout_link WHERE session_id = ?",
                (session_id,),
            )
        ]
        for workout_id in linked:
            for row in conn.execute(
                """
                SELECT s.sampled_at, s.value
                  FROM health_sample s
                  JOIN external_workout w ON w.external_workout_id = s.external_workout_id
                 WHERE s.external_workout_id = ?
                   AND s.kind = 'heart_rate'
                   AND (s.sampled_at BETWEEN w.started_at AND w.ended_at
                        OR s.association = 'tail')
                """,
                (workout_id,),
            ):
                series[session_id].append((_epoch(row["sampled_at"]), float(row["value"])))
        series[session_id].sort()
    return series


def _nearest(series: list[tuple[float, float]], target: float, tolerance: float) -> float | None:
    """Value of the sample nearest `target` within `tolerance` seconds, else None."""
    candidates = [item for item in series if abs(item[0] - target) <= tolerance]
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item[0] - target))[1]


def _endpoint(series: list[tuple[float, float]], target: float, tolerance: float) -> float | None:
    """Last sample at or before `target` within `tolerance` seconds, else None."""
    candidates = [item for item in series if 0 <= target - item[0] <= tolerance]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _session_sets(
    session_id: str,
    conn: sqlite3.Connection,
    series: list[tuple[float, float]],
    *,
    end_tolerance: float,
    sixty_tolerance: float,
) -> tuple[list[dict[str, Any]], int]:
    """One record per completed set, plus the number of set-completion events seen."""
    events = list(
        conn.execute(
            """
            SELECT event_type, occurred_at, set_id, local_set_id
              FROM workout_execution_event
             WHERE workout_id = ?
             ORDER BY occurred_at
            """,
            (session_id,),
        )
    )
    starts: dict[object, float] = {}
    completed: list[tuple[object, float, int | None]] = []
    for event in events:
        key = event["set_id"] if event["set_id"] is not None else event["local_set_id"]
        if event["event_type"] == "set_started" and key is not None:
            starts[key] = _epoch(event["occurred_at"])
        elif event["event_type"] == "set_completed":
            completed.append((key, _epoch(event["occurred_at"]), event["set_id"]))

    records: list[dict[str, Any]] = []
    for index, (key, finished_at, set_id) in enumerate(completed):
        next_start = completed[index + 1][1] if index + 1 < len(completed) else None
        load = reps = None
        if set_id is not None:
            row = conn.execute(
                "SELECT load_kg, reps FROM workout_set WHERE set_id = ?", (set_id,)
            ).fetchone()
            if row is not None:
                load, reps = row["load_kg"], row["reps"]
        records.append(
            {
                "hr_end": _endpoint(series, finished_at, end_tolerance),
                "hr_60": _nearest(series, finished_at + 60.0, sixty_tolerance),
                "hr_next": _nearest(series, next_start, end_tolerance) if next_start else None,
                "set_duration": (finished_at - starts[key]) if key in starts else None,
                "rest_duration": (next_start - finished_at) if next_start else None,
                "load": load,
                "reps": reps,
            }
        )
    return records, len(completed)


def _spread(values: list[float]) -> dict[str, float | None]:
    """Median, SD and quartiles, which is as much shape as this probe can justify."""
    if not values:
        return {"median": None, "sd": None, "q1": None, "q3": None}
    quartiles = statistics.quantiles(values, n=4) if len(values) >= 4 else []
    return {
        "median": round(statistics.median(values), 1),
        "sd": round(statistics.pstdev(values), 1) if len(values) > 1 else 0.0,
        "q1": round(quartiles[0], 1) if quartiles else None,
        "q3": round(quartiles[2], 1) if quartiles else None,
    }


def _deltas(records: list[dict[str, Any]]) -> list[float]:
    """End-of-set minus one-minute HR, for every set with both endpoints."""
    return [
        float(record["hr_end"]) - float(record["hr_60"])
        for record in records
        if record["hr_end"] is not None and record["hr_60"] is not None
    ]


def _delta_vs(records: list[dict[str, Any]], column: str) -> tuple[list[float], list[float]]:
    """Paired (delta, column) values, keeping only rows where both exist."""
    pairs = [
        (float(record["hr_end"]) - float(record["hr_60"]), float(record[column]))
        for record in records
        if record["hr_end"] is not None
        and record["hr_60"] is not None
        and record[column] is not None
    ]
    return [pair[0] for pair in pairs], [pair[1] for pair in pairs]


def _verdict(
    *,
    coverage: float,
    within: float | None,
    between: float | None,
    confounds: dict[str, float | None],
) -> list[str]:
    """Apply the docstring's decision rule and name every bar that failed."""
    failures: list[str] = []
    if coverage < COVERAGE_BAR:
        failures.append("fail: endpoints missing for too many sets")
    if within is not None and between is not None and within >= between:
        failures.append("fail: within-session noise exceeds the between-session signal")
    for column in ("load", "set_duration"):
        value = confounds.get(f"corr_delta_{column}")
        if value is not None and abs(value) > CONFOUND_BAR:
            failures.append(f"fail: delta tracks {column}, which the prescription already knows")
    association = confounds.get("corr_delta_reps")
    if association is None or abs(association) < ASSOCIATION_BAR:
        failures.append("fail: delta says nothing the logged set does not")
    return failures


def analyse(
    conn: sqlite3.Connection,
    *,
    end_tolerance: float = DEFAULT_END_TOLERANCE_S,
    sixty_tolerance: float = DEFAULT_SIXTY_TOLERANCE_S,
) -> dict[str, Any]:
    """Build the aggregate report. Never returns a sample, a timestamp or a session identifier."""
    session_ids = [
        row["workout_id"]
        for row in conn.execute("SELECT DISTINCT workout_id FROM workout_execution_event")
    ]
    series_by_session = _samples(session_ids, conn)

    records: list[dict[str, Any]] = []
    session_medians: list[float] = []
    within_sds: list[float] = []
    completions = 0
    sessions_with_data = 0
    for session_id in session_ids:
        session_records, completed = _session_sets(
            session_id,
            conn,
            series_by_session[session_id],
            end_tolerance=end_tolerance,
            sixty_tolerance=sixty_tolerance,
        )
        completions += completed
        records.extend(session_records)
        matched = _deltas(session_records)
        if matched:
            sessions_with_data += 1
            session_medians.append(statistics.median(matched))
            if len(matched) > 2:
                within_sds.append(statistics.pstdev(matched))

    deltas = _deltas(records)
    rest_drops = [
        float(record["hr_end"]) - float(record["hr_next"])
        for record in records
        if record["hr_end"] is not None and record["hr_next"] is not None
    ]
    coverage = (len(deltas) / completions) if completions else 0.0
    within = statistics.median(within_sds) if within_sds else None
    between = statistics.pstdev(session_medians) if len(session_medians) > 1 else None

    confounds: dict[str, float | None] = {}
    for column in CONFOUND_COLUMNS:
        xs, ys = _delta_vs(records, column)
        value = _corr(xs, ys)
        confounds[f"corr_delta_{column}"] = round(value, 3) if value is not None else None

    failures = _verdict(coverage=coverage, within=within, between=between, confounds=confounds)
    return {
        "parameters": {
            "end_tolerance_s": end_tolerance,
            "sixty_tolerance_s": sixty_tolerance,
        },
        "sample": {
            "sessions_with_telemetry": len(session_ids),
            "sessions_with_matched_sets": sessions_with_data,
            "set_completions": completions,
            "sets_matched": len(deltas),
            "coverage": round(coverage, 3),
        },
        "delta60_bpm": _spread(deltas),
        "hr_rising_at_60s": sum(1 for value in deltas if value < 0),
        "spread": {
            "within_session_sd": round(within, 1) if within is not None else None,
            "between_session_sd": round(between, 1) if between is not None else None,
            "session_medians": [round(value, 1) for value in session_medians],
        },
        "confounds": confounds,
        "rest_window_drop_bpm": _spread(rest_drops),
        "verdict": failures or ["pass: every decision bar cleared -- revisit the feature question"],
        "worth_pursuing": not failures,
        "caveat": (
            None
            if len(deltas) >= MIN_SETS_FOR_CORRELATION
            else f"fewer than {MIN_SETS_FOR_CORRELATION} matched sets: correlations are unstable"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", required=True, help="path to coach.db; opened read-only")
    parser.add_argument(
        "--end-tolerance",
        type=float,
        default=DEFAULT_END_TOLERANCE_S,
        help="seconds a sample may precede the set-completion tap",
    )
    parser.add_argument(
        "--sixty-tolerance",
        type=float,
        default=DEFAULT_SIXTY_TOLERANCE_S,
        help="seconds around set-completion + 60 s in which to find the recovery sample",
    )
    args = parser.parse_args(argv)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        report = analyse(
            conn, end_tolerance=args.end_tolerance, sixty_tolerance=args.sixty_tolerance
        )
    finally:
        conn.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
