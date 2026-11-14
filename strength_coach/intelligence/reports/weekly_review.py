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
        values = [value for value in (payload.get("category_scores") or {}).values()
                  if value is not None]
        if values:
            scores.append({"date": point["date"], "score": round(sum(values) / len(values), 3)})
    direction = "unknown"
    if len(scores) >= 2:
        change = scores[-1]["score"] - scores[0]["score"]
        direction = "up" if change > 0.05 else "down" if change < -0.05 else "flat"
    value = {
        "observed_days": len(scores),
        "direction": direction,
        "first_date": scores[0]["date"] if scores else None,
        "last_date": scores[-1]["date"] if scores else None,
    }
    gate = "insufficient" if len(scores) < 3 else "signal"
    return Section(value=value, method="strength_coach.features.readiness_score.compute",
                   n=len(scores), gate=gate), {"scores": scores}


def _progression(conn, week_end: str) -> list[dict]:
    taxonomy = exercises.taxonomy()
    start = (dt.date.fromisoformat(week_end)
             - dt.timedelta(days=MAIN_LIFT_WINDOW_DAYS - 1)).isoformat()
    tracked: list[dict] = []
    for exercise_id, entity in sorted(taxonomy.entities.items()):
        if not entity.get("main_lift"):
            continue
        points = strength_trend.observations(conn, exercise_id, start, week_end)
        if not points:
            continue
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
            "n": summary.get("n"),
            "gate": summary.get("status"),
        })
        if len(tracked) >= MAX_TRACKED_LIFTS:
            break
    return tracked


def _volume_section(conn, start: str, end: str) -> tuple[Section, dict]:
    frame = queries.clean_sets(conn, start=start, end=end)
    report = volume.compute(frame, on_date=end)
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
        value={"status": label, "groups": patterns},
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
    value = {
        "deload": "active" if decision is not None else "none_scheduled",
        "deload_reason": getattr(decision, "reason", None),
        "regime_review": regime_label,
        "regime_findings": len(findings),
        "breaks": active,
    }
    return Section(value=value, method="strength_coach.features.deload.decision",
                   n=len(findings)), {"findings": len(findings)}


def build(
    conn, *, week_end: dt.date, include_observations: bool = True
) -> WeeklyReview:
    monday, sunday = week_bounds(week_end)
    start, end = monday.isoformat(), sunday.isoformat()
    report = WeeklyReview(week_start=start, week_end=end, status="ok")

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

    tracked = _progression(conn, end)
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
        "planned_sessions": "not_tracked",
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
    if include_observations and not report.observations:
        missing.append("no observation passed its evidence gate")
    report.missing = missing

    if not completed:
        report.status = "no_data"
    report.limitations = list(LIMITATIONS)
    return report
