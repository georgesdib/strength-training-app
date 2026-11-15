"""Compare two explicit training periods, descriptively.

Every side is produced by the metric's owner. The only arithmetic here is the difference between
the two owner outputs, which is the comparison the caller asked for; no metric is re-derived.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach.features import adherence_analytics, attendance, strength_trend, volume
from strength_coach.intelligence.capabilities._common import envelope, window_period
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import Envelope, FactBlock
from strength_coach.intelligence.errors import IntelligenceError
from strength_coach.intelligence.registry import (
    CAPABILITIES,
    CapabilityRequest,
    CapabilitySpec,
    payload_mapping,
    reject_unknown,
)
from strength_coach.intelligence.service import ExecutionContext
from strength_coach.store import queries
from strength_coach.utils import exercises

CAPABILITY_NAME = "compare_training_periods"
CAPABILITY_VERSION = "1.0.0"
METRICS = ("attendance", "adherence", "volume", "strength_direction")
MAX_RANGE_DAYS = 366
MAX_PERIODS = 60

MODULES = (
    "strength_coach.features.attendance",
    "strength_coach.features.adherence_analytics",
    "strength_coach.features.volume",
    "strength_coach.features.strength_trend",
)

LIMITATIONS = (
    "Descriptive: two windows over one athlete are a comparison, not a treatment effect (LIM-26).",
    "The difference is arithmetic between two owner-produced values; neither side is re-derived.",
    "Windows are not normalised for block, deload or calendar position.",
)


@dataclass(frozen=True)
class CompareRequest(CapabilityRequest):
    start_a: dt.date
    end_a: dt.date
    start_b: dt.date
    end_b: dt.date
    metric: str
    exercise_id: str | None

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> CompareRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("period_a", "period_b", "metric", "exercise_id"))
        start_a, end_a = _period(data.get("period_a"), "period_a", today)
        start_b, end_b = _period(data.get("period_b"), "period_b", today)
        metric = data.get("metric")
        if metric not in METRICS:
            raise IntelligenceError(
                "invalid_argument",
                "metric must be attendance, adherence, volume or strength_direction",
                field="metric",
            )
        exercise_id = data.get("exercise_id")
        if metric == "strength_direction":
            if not isinstance(exercise_id, str) or not exercise_id.strip():
                raise IntelligenceError(
                    "invalid_argument", "exercise_id is required for strength_direction",
                    field="exercise_id",
                )
        elif exercise_id is not None:
            raise IntelligenceError(
                "invalid_argument", "exercise_id is only valid for strength_direction",
                field="exercise_id",
            )
        return cls(
            start_a=start_a, end_a=end_a, start_b=start_b, end_b=end_b,
            metric=metric,
            exercise_id=exercise_id.strip() if isinstance(exercise_id, str) else None,
        )

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "period_a": {"start": self.start_a.isoformat(), "end": self.end_a.isoformat()},
            "period_b": {"start": self.start_b.isoformat(), "end": self.end_b.isoformat()},
            "metric": self.metric,
        }
        if self.exercise_id:
            payload["exercise_id"] = self.exercise_id
        return payload


def _date(value: object, field: str) -> dt.date:
    if not isinstance(value, str):
        raise IntelligenceError("invalid_argument", f"{field} must be YYYY-MM-DD", field=field)
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise IntelligenceError(
            "invalid_argument", f"{field} must be YYYY-MM-DD", field=field
        ) from exc


def _period(value: object, field: str, today: dt.date) -> tuple[dt.date, dt.date]:
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise IntelligenceError(
            "invalid_argument", f"{field} must contain start and end", field=field
        )
    start = _date(value.get("start"), f"{field}.start")
    end = _date(value.get("end"), f"{field}.end")
    if start > end:
        raise IntelligenceError(
            "invalid_argument", f"{field}.start must not be after end", field=field
        )
    if end > today:
        raise IntelligenceError(
            "invalid_argument", f"{field}.end must not be in the future", field=field
        )
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise IntelligenceError(
            "invalid_argument", f"{field} must be at most {MAX_RANGE_DAYS} days", field=field
        )
    return start, end


def _weeks(start: dt.date, end: dt.date) -> int:
    return max(1, ((end - start).days + 1 + 6) // 7)


def _side(conn, request: CompareRequest, start: dt.date, end: dt.date) -> dict[str, object]:
    metric = request.metric
    if metric == "attendance":
        report = attendance.summary(conn, start=start, end=end, weeks=_weeks(start, end))
        return {
            "primary": report.get("completed"),
            "value": {
                key: report.get(key)
                for key in ("completed", "target", "pct", "target_shortfall", "families",
                            "session_types", "duration")
            },
        }
    if metric == "adherence":
        report = adherence_analytics.analytics(
            conn, {"from": start.isoformat(), "to": end.isoformat(), "group_by": "week"}
        )
        planned = report.get("final_plan") or {}
        completion = planned.get("set_completion") or {}
        return {
            "primary": completion.get("ratio"),
            "value": {
                "status": report.get("status"),
                "reason": report.get("reason"),
                "workouts": planned.get("workouts"),
                "prescribed_sets": planned.get("prescribed_sets"),
                "matched_sets": planned.get("matched_sets"),
                "set_completion": completion,
                "small_sample": planned.get("small_sample"),
            },
        }
    if metric == "volume":
        frame = queries.clean_sets(conn, start=start.isoformat(), end=end.isoformat())
        report = volume.compute(frame, on_date=end.isoformat())
        patterns = [
            {
                "pattern": row.get("pattern"),
                "average": row.get("average"),
                "status": row.get("status"),
            }
            for row in (report.get("patterns") or [])
        ]
        total = sum(float(row["average"]) for row in patterns if row.get("average") is not None)
        return {'primary': round(total, 2), "value": {"patterns": patterns,
                                                       "weekly_total_average": round(total, 2)}}
    entities = exercises.taxonomy().entities
    requested = request.exercise_id or ""
    canonical = requested if requested in entities else exercises.canonical_id(requested)
    entity = entities.get(canonical or "")
    if canonical is None or entity is None:
        raise IntelligenceError("not_found", "unknown exercise", field="exercise_id")
    points = strength_trend.observations(conn, canonical, start.isoformat(), end.isoformat())
    summary = strength_trend.summarize(points)
    return {
        "primary": summary.get("recent_median_kg"),
        "value": {"summary": summary, "observations": len(points), "exercise_id": canonical},
    }


def _delta(a: object, b: object) -> dict[str, object]:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return {"absolute": None, "pct": None}
    absolute = round(float(b) - float(a), 3)
    pct = round(100.0 * absolute / float(a), 1) if float(a) != 0 else None
    return {"absolute": absolute, "pct": pct}


def compare(
    conn: sqlite3.Connection, request: CompareRequest, execution: ExecutionContext
) -> Envelope:
    side_a = _side(conn, request, request.start_a, request.end_a)
    side_b = _side(conn, request, request.start_b, request.end_b)
    primary_a = side_a.get("primary")
    primary_b = side_b.get("primary")
    delta = _delta(primary_a, primary_b)

    days = max(
        (request.end_a - request.start_a).days + 1,
        (request.end_b - request.start_b).days + 1,
    )
    facts = {
        "comparison": FactBlock(
            value={
                "metric": request.metric,
                "exercise_id": request.exercise_id,
                "period_a": {
                    "start": request.start_a.isoformat(),
                    "end": request.end_a.isoformat(),
                    **side_a,
                },
                "period_b": {
                    "start": request.start_b.isoformat(),
                    "end": request.end_b.isoformat(),
                    **side_b,
                },
                "delta": delta,
            },
            basis="derived",
            method=_method(request.metric),
            note="Delta is arithmetic between the two owner outputs.",
        )
    }
    missing: list[str] = []
    if primary_a is None:
        missing.append("period_a has no comparable value for this metric")
    if primary_b is None:
        missing.append("period_b has no comparable value for this metric")

    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok" if primary_a is not None and primary_b is not None else "no_data",
        as_of=request.end_b.isoformat(),
        period=window_period(
            request.start_a.isoformat(), request.end_b.isoformat(), days, None,
            execution.timezone,
        ),
        facts=facts,
        coverage={
            "metric": request.metric,
            "period_a_days": (request.end_a - request.start_a).days + 1,
            "period_b_days": (request.end_b - request.start_b).days + 1,
            "delta_defined": int(delta["absolute"] is not None),
        },
        missing=missing,
        limitations=LIMITATIONS,
        execution=execution,
        arguments=request.to_mapping(),
        modules=MODULES,
    )


def _method(metric: str) -> str:
    return {
        "attendance": "strength_coach.features.attendance.summary",
        "adherence": "strength_coach.features.adherence_analytics.analytics",
        "volume": "strength_coach.features.volume.compute",
        "strength_direction": "strength_coach.features.strength_trend.summarize",
    }[metric]


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only comparison of two dates windows for attendance, adherence, weekly volume or "
            "an exercise's strength direction. Supply exercise_id only for strength_direction."
        ),
        request_type=CompareRequest,
        handler=compare,
    )
)
