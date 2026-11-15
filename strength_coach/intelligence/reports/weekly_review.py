"""The deterministic weekly review package.

Composition only: every section is produced by its owning service for the Monday-Sunday week.
The report never writes; observations are analysed with persist=False because the review is a read.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field

from strength_coach import history
from strength_coach.features import (
    adherence_analytics,
    attendance,
    breaks,
    deload,
    readiness_score,
    regime_change,
    strength_trend,
    volume,
)
from strength_coach.features import (
    observations as observations_feature,
)
from strength_coach.store import queries
from strength_coach.utils import exercises
from strength_coach.utils import readiness as readiness_utils

MAIN_LIFT_WINDOW_DAYS = 84
MAX_TRACKED_LIFTS = 8
MAX_SESSIONS = 20
MAX_PATTERNS = 12
MAX_BREAKS = 5
MAX_FINDINGS = 2

LIMITATIONS = (
    "Attendance is target-based; no planned-session calendar exists (DEC-W7-01).",
    "A calculated e1RM is not a tested maximum (LIM-24).",
    "The readiness score is a fixed policy composite, not a measurement (LIM-02).",
    "Descriptive only: no prescription, rule or plan is changed by this review.",
)


@dataclass(frozen=True)
class Section:
    value: object
    method: str
    basis: str = "derived"
    n: int | None = None
    gate: str | None = None


@dataclass
class WeeklyReview:
    week_start: str
    week_end: str
    status: str
    sections: dict[str, Section] = field(default_factory=dict)
    observations: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    complete: bool = True


def week_bounds(week_end: dt.date) -> tuple[dt.date, dt.date]:
    monday = week_end - dt.timedelta(days=week_end.weekday())
    return monday, monday + dt.timedelta(days=6)


def _direction(change: float | None) -> str:
    if change is None:
        return "unknown"
    if change > 0:
        return "up"
    if change < 0:
        return "down"
    return "flat"


def _readiness_section(conn, start: str, end: str) -> tuple[Section, dict]:
    observed = queries.readiness_series(
        conn, start, end, tuple(readiness_utils.READINESS_FIELDS)
    )
    scores = []
    for point in observed:
        payload = readiness_score.compute(conn, point["date"]).as_dict()
        # The canonical composite is the owner's answer. Averaging category scores here would
        # re-derive the metric and diverge whenever category overrides make them uneven.
        score = payload.get("score")
        if score is not None:
            scores.append({"date": point["date"], "score": float(score)})
    direction = "unknown"
    if len(scores) >= 2:
        # Presentation rule: the sign of the canonical score change across the week. No
        # invented magnitude threshold; the values themselves are never returned.
        first, last = scores[0]["score"], scores[-1]["score"]
        direction = "up" if last > first else "down" if last < first else "flat"
    value = {
        "observed_days": len(scores),
        "direction": direction,
        "first_date": scores[0]["date"] if scores else None,
        "last_date": scores[-1]["date"] if scores else None,
    }
    gate = "insufficient" if len(scores) < 3 else "signal"
    return Section(value=value, method="strength_coach.features.readiness_score.compute",
                   n=len(scores), gate=gate), {"scores": scores}


def _progression(conn, week_end: str) -> tuple[list[dict], int]:
    """Main lifts with observations, ordered by recency then evidence, not alphabet."""
    taxonomy = exercises.taxonomy()
    start = (dt.date.fromisoformat(week_end)
             - dt.timedelta(days=MAIN_LIFT_WINDOW_DAYS - 1)).isoformat()
    candidates: list[tuple[str, dict]] = []
    for exercise_id, entity in taxonomy.entities.items():
        if not entity.get("main_lift"):
            continue
        points = strength_trend.observations(conn, exercise_id, start, week_end)
        if not points:
            continue
        candidates.append((exercise_id, {"entity": entity, "points": points}))
    # Selection policy: most recently observed lift first, then more observations, then id.
    # Taxonomy order is not a priority order; the cap must not drop a lift that moved this week.
    candidates.sort(
        key=lambda item: (
            item[1]["points"][-1].date,
            len(item[1]["points"]),
            item[0],
        ),
        reverse=True,
    )
    tracked: list[dict] = []
    for exercise_id, item in candidates[:MAX_TRACKED_LIFTS]:
        entity = item["entity"]
        points = item["points"]
        summary = strength_trend.summarize(points)
        change = summary.get("change_from_median_kg")
        median = summary.get("recent_median_kg")
        change_pct = (
            round(100.0 * float(change) / float(median), 1)
            if change is not None and median not in (None, 0) else None
        )
        tracked.append({
            "exercise_id": exercise_id,
            "display": entity.get("display") or exercise_id,
            "direction": _direction(change),
            "change_kg": change,
            "change_pct": change_pct,
            "recent_median_kg": median,
            "n": summary.get("n"),
            "gate": summary.get("status"),
        })
    return tracked, max(0, len(candidates) - len(tracked))


def _volume_section(conn, start: str, end: str) -> tuple[Section, dict]:
    # The engine judges a rolling window, not a single week. Give it the full configured
    # window plus the declared-break weeks, or it would average one observed week and call
    # the coverage complete. No accounting logic is recreated here.
    closing = dt.date.fromisoformat(end)
    current_week_start = closing - dt.timedelta(days=closing.weekday())
    config = volume.VolumeConfig.load()
    window_start = current_week_start - dt.timedelta(weeks=config.window_weeks - 1)
    frame = queries.clean_sets(conn, start=window_start.isoformat(), end=end)
    break_weeks = sorted({
        int(week) for _, week in breaks.break_weeks(conn, window_start.isoformat(), end)
    })
    report = volume.compute(
        frame,
        on_date=end,
        config=config,
        excluded_weeks=break_weeks,
        reset_weeks=break_weeks,
    )
    patterns = [
        {
            "pattern": row.get("pattern"),
            "average": row.get("average"),
            "target": row.get("target"),
            "status": row.get("status"),
        }
        for row in (report.get("patterns") or [])[:MAX_PATTERNS]
    ]
    statuses = {str(row.get("status")) for row in patterns}
    if not patterns:
        label = "no_data"
    elif "over" in statuses:
        label = "above_budget"
    elif statuses and statuses <= {"within", "optimal"}:
        label = "within_budget"
    else:
        label = "mixed"
    return Section(
        value={
            "status": label,
            "groups": patterns,
            "window_weeks": config.window_weeks,
            "coverage": report.get("coverage"),
        },
        method="strength_coach.features.volume.compute",
        n=len(patterns),
        gate="insufficient" if not patterns else "signal",
    ), {"patterns": len(patterns)}


def _programme_section(conn, end: str) -> tuple[Section, dict]:
    decision = deload.decision(conn, end)
    regime = regime_change.detect(conn, on_date=end)
    findings = list(regime.get("findings") or [])
    active = breaks.as_dict(breaks.active_on(conn, end))[:MAX_BREAKS]
    regime_label = "stable" if not findings else (
        "review" if len(findings) >= 2 else "one_finding"
    )
    detail = [
        {
            "main_lift": row.get("main_lift"),
            "category": row.get("category"),
            "kind": row.get("kind"),
            "drop_pct": row.get("drop_pct"),
            "baseline_sets": row.get("baseline_sets"),
            "current_sets": row.get("current_sets"),
            "substitutes": [
                {
                    "exercise_id": substitute.get("exercise_id"),
                    "increase": substitute.get("increase"),
                }
                for substitute in (row.get("substitutes") or [])[:2]
            ],
        }
        for row in findings[:MAX_FINDINGS]
    ]
    value = {
        # Policy state on the report's Sunday, not evidence that a deload was performed.
        "deload": "active" if decision is not None else "none_scheduled",
        "deload_policy": "active" if decision is not None else "none_scheduled",
        "deload_reason": getattr(decision, "reason", None),
        "deload_trigger": getattr(decision, "trigger", None),
        "regime_review": regime_label,
        "regime_findings": len(findings),
        "regime_findings_detail": detail,
        "breaks": active,
    }
    return Section(value=value, method="strength_coach.features.deload.decision",
                   n=len(findings)), {"findings": len(findings)}


def build(
    conn, *, week_end: dt.date, include_observations: bool = True,
    today: dt.date | None = None,
) -> WeeklyReview:
    monday, sunday = week_bounds(week_end)
    complete = week_end < (today or dt.date.today())
    start, end = monday.isoformat(), sunday.isoformat()
    report = WeeklyReview(week_start=start, week_end=end, status="ok", complete=complete)

    listing = history.list_sessions(conn, limit=200, start=start, end=end)
    rows = [row for row in listing["sessions"] if not row.get("voided")]
    completed = len(rows)
    working_sets = sum(int(row.get("working_set_count") or 0) for row in rows)
    session_types = Counter(str(row.get("session_type")) for row in rows)
    srpe = sum(1 for row in rows if row.get("session_rpe_recorded") or row.get("session_rpe") is not None)

    attendance_report = attendance.summary(conn, start=monday, end=sunday, weeks=1)
    report.sections["activity"] = Section(
        value={
            "completed_sessions": completed,
            "target_sessions": attendance_report.get("target"),
            "working_sets": working_sets,
            "session_types": dict(sorted(session_types.items())),
            "sessions_with_srpe": srpe,
        },
        method="strength_coach.features.attendance.summary",
        n=completed,
        gate="signal" if completed else "insufficient",
    )

    adherence_report = adherence_analytics.analytics(
        conn, {"from": start, "to": end, "group_by": "week"}
    )
    planned = adherence_report.get("final_plan") or {}
    completion = planned.get("set_completion") or {}
    adherence_available = (
        str(adherence_report.get("status")) == "available"
        and bool(planned.get("has_data"))
    )
    report.sections["adherence"] = Section(
        value={
            "available": adherence_available,
            "status": adherence_report.get("status"),
            "final_plan_ratio": completion.get("ratio"),
            "planned_sets": planned.get("prescribed_sets"),
            "matched_sets": planned.get("matched_sets"),
            "missing_sets": planned.get("missing_sets"),
            "extra_sets": planned.get("extra_sets"),
        },
        method="strength_coach.features.adherence_analytics.analytics",
        n=int(planned.get("prescribed_sets") or 0),
        gate="insufficient" if not adherence_available else "signal",
    )

    report.sections["sessions"] = Section(
        value=[
            {
                "session_id": row.get("session_id"),
                "date": row.get("occurred_on"),
                "session_type": row.get("session_type"),
                "working_sets": row.get("working_set_count"),
                "duration_min": row.get("duration_min"),
                "srpe": row.get("session_rpe"),
                "source": row.get("source"),
                "flags": row.get("flags") or [],
            }
            for row in rows[:MAX_SESSIONS]
        ],
        method="strength_coach.history.list_sessions",
        n=len(rows),
        basis="observed",
    )

    tracked, omitted = _progression(conn, end)
    report.sections["progression"] = Section(
        value=tracked,
        method="strength_coach.features.strength_trend.summarize",
        n=len(tracked),
        gate="insufficient" if not tracked else "signal",
    )

    volume_section, _ = _volume_section(conn, start, end)
    report.sections["volume"] = volume_section

    readiness_section, readiness_meta = _readiness_section(conn, start, end)
    report.sections["readiness"] = readiness_section

    programme_section, _ = _programme_section(conn, end)
    report.sections["programme"] = programme_section

    if include_observations:
        analysis = observations_feature.analyse(
            conn, as_of=end, weeks=1, persist=False
        )
        report.observations = [
            {
                "family": item.get("family"),
                "text": item.get("statement"),
                "gate": item.get("gate"),
                "n": item.get("n"),
                "evidence_id": item.get("evidence_id"),
                "limitations": ["Descriptive only; a question for the athlete, not a verdict."],
            }
            for item in (analysis.get("observations") or [])[:2]
        ]

    flags = sorted({str(flag) for row in rows for flag in (row.get("flags") or [])})
    if rows and all(str(row.get("source")) != "workout" for row in rows):
        flags.append("imported_sessions_only")
    if not adherence_available:
        flags.append("adherence_unavailable")
    report.quality_flags = flags

    report.coverage = {
        "sessions_considered": completed,
        "working_sets": working_sets,
        "days_with_readiness": len(readiness_meta["scores"]),
        "tracked_lifts": len(tracked),
        "tracked_lifts_omitted": omitted,
        "planned_sessions": "not_tracked",
        "week_complete": int(complete),
        "week_partial": int(not complete),
    }

    missing: list[str] = []
    if not completed:
        missing.append("no completed session in the week")
    if not adherence_available:
        missing.append("no comparable app-tracked workout with a frozen plan")
    if not tracked:
        missing.append("no eligible main-lift observations in the 84-day window")
    if not readiness_meta["scores"]:
        missing.append("no readiness entry in the week")
    if omitted:
        missing.append(
            f"{omitted} further main lift(s) with observations are outside the report cap"
        )
    if not complete:
        missing.append(
            "the current week is still in progress; sections cover only completed work so far"
        )
    if include_observations and not report.observations:
        missing.append("no observation passed its evidence gate")
    report.missing = missing

    if not completed:
        report.status = "no_data"
    report.limitations = list(LIMITATIONS)
    return report
