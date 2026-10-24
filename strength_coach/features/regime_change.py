"""Read-only detection of a main lift disappearing while a substitute rises.

This is the "regime change" audit from TRAINING-GUIDELINES §8: a persistent shift in what is
actually trained, not a single missed session. It is descriptive only. A finding is a question
for the athlete, never a prescription change.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

from strength_coach.features import readiness_score
from strength_coach.store import queries
from strength_coach.utils import exercises

DEFAULT_WEEKS = 8
COLLAPSE_RATIO = 0.25      # a quarter or less of the prior volume
MIN_BASELINE_SETS = 4      # ignore sparse lifts; one set is not a regime
MIN_SUBSTITUTE_RISE = 2    # require a real increase, not a one-set fluctuation


def _window(on_date: str | None, weeks: int) -> tuple[dt.date, dt.date, dt.date, dt.date]:
    if weeks not in (8, 12):
        raise ValueError("weeks must be 8 or 12")
    end = dt.date.fromisoformat(on_date) if on_date else dt.date.today()
    current_start = end - dt.timedelta(days=7 * weeks - 1)
    baseline_end = current_start - dt.timedelta(days=1)
    baseline_start = baseline_end - dt.timedelta(days=7 * weeks - 1)
    return baseline_start, baseline_end, current_start, end


def _sets(conn, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT occurred_on, exercise_id FROM clean_set "
        "WHERE is_working_set = 1 AND occurred_on BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return [{"date": str(row["occurred_on"])[:10], "exercise_id": str(row["exercise_id"])}
            for row in rows]


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["exercise_id"]] += 1
    return dict(counts)


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Exercise -> per-week set count, so two windows of different length stay comparable."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        week = dt.date.fromisoformat(row["date"]).isocalendar()[:2]
        out[row["exercise_id"]][f"{week[0]}-W{week[1]:02d}"] += 1
    return {exercise: dict(weeks) for exercise, weeks in out.items()}


def detect(conn, *, on_date: str | None = None, weeks: int = DEFAULT_WEEKS) -> dict:
    start, baseline_end, current_start, end = _window(on_date, weeks)
    baseline_rows = _sets(conn, start, baseline_end)
    current_rows = _sets(conn, current_start, end)
    baseline_counts = _counts(baseline_rows)
    current_counts = _counts(current_rows)
    baseline_weeks = _index(baseline_rows)
    current_weeks = _index(current_rows)
    entities = exercises.taxonomy().entities

    findings = []
    checked = 0
    for exercise_id, entity in entities.items():
        if not entity.get("main_lift"):
            continue
        base = int(baseline_counts.get(exercise_id, 0))
        if base < MIN_BASELINE_SETS:
            continue
        checked += 1
        current = int(current_counts.get(exercise_id, 0))
        if current > base * COLLAPSE_RATIO:
            continue

        category = readiness_score.category_for(exercise_id, entity)
        substitutes = []
        if category is not None:
            for other_id, other_entity in entities.items():
                if other_id == exercise_id:
                    continue
                if readiness_score.category_for(other_id, other_entity) != category:
                    continue
                other_base = int(baseline_counts.get(other_id, 0))
                other_current = int(current_counts.get(other_id, 0))
                increase = other_current - other_base
                if increase >= MIN_SUBSTITUTE_RISE and other_current >= MIN_SUBSTITUTE_RISE:
                    substitutes.append({
                        "exercise_id": other_id,
                        "baseline_sets": other_base,
                        "current_sets": other_current,
                        "increase": increase,
                        "baseline_per_week": round(other_base / weeks, 2),
                        "current_per_week": round(other_current / weeks, 2),
                    })
        substitutes.sort(key=lambda row: (-row["increase"], row["exercise_id"]))
        findings.append({
            "main_lift": exercise_id,
            "category": category,
            "baseline_sets": base,
            "current_sets": current,
            "baseline_per_week": round(base / weeks, 2),
            "current_per_week": round(current / weeks, 2),
            "drop_pct": round(100 * (base - current) / base, 1),
            "kind": "disappeared" if current == 0 else "collapsed",
            "substitutes": substitutes,
        })

    findings.sort(key=lambda row: (-row["drop_pct"], row["main_lift"]))
    return {
        "window": {
            "weeks": weeks,
            "baseline_from": start.isoformat(),
            "baseline_to": baseline_end.isoformat(),
            "current_from": current_start.isoformat(),
            "current_to": end.isoformat(),
        },
        "findings": findings,
        "coverage": {
            "main_lifts_checked": checked,
            "baseline_sets": len(baseline_rows),
            "current_sets": len(current_rows),
            "baseline_weeks_with_data": len({week for values in baseline_weeks.values()
                                             for week in values}),
            "current_weeks_with_data": len({week for values in current_weeks.values()
                                            for week in values}),
        },
        "note": "Descriptive regime check. A finding is a question for the athlete, not a "
                "verdict and never a prescription change.",
    }
