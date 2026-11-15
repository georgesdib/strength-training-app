"""Adherence analysis over completed app workouts, read-only."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach.features import adherence_analytics
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
    require_int,
)
from strength_coach.intelligence.service import ExecutionContext

CAPABILITY_NAME = "get_adherence_analysis"
CAPABILITY_VERSION = "1.0.0"
MAX_PERIODS = 60
MAX_EXERCISES = 40
MAX_WORKOUTS = 20
MAX_RANGE_DAYS = 366

MODULES = ("strength_coach.features.adherence_analytics",)

LIMITATIONS = (
    "App-tracked completed workouts only; imported sessions have no frozen plan to compare.",
    "No stored training block exists, so the block dimension is unavailable (DEC-PROGRAMME-01).",
    "The small-sample guard is the owner's; a trend is not implied below it.",
    "Descriptive only: no prescription is changed.",
)


@dataclass(frozen=True)
class AdherenceRequest(CapabilityRequest):
    as_of: dt.date
    weeks: int | None
    start: dt.date | None
    end: dt.date | None
    group_by: str
    exercise_id: str | None
    session_type: str | None

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "as_of": self.as_of.isoformat(),
            "group_by": self.group_by,
        }
        if self.start is not None and self.end is not None:
            payload["from"] = self.start.isoformat()
            payload["to"] = self.end.isoformat()
        else:
            payload["weeks"] = self.weeks
        if self.exercise_id:
            payload["exercise_id"] = self.exercise_id
        if self.session_type:
            payload["session_type"] = self.session_type
        return payload

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> AdherenceRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("as_of", "weeks", "from", "to", "group_by",
                              "exercise_id", "session_type"))
        as_of = today if data.get("as_of") is None else _date(data.get("as_of"), "as_of")
        if as_of > today:
            raise IntelligenceError(
                "invalid_argument", "as_of must not be in the future", field="as_of"
            )
        group_by = data.get("group_by", "week")
        if group_by not in ("week", "month"):
            raise IntelligenceError(
                "invalid_argument", "group_by must be week or month", field="group_by"
            )
        has_from = data.get("from") is not None
        has_to = data.get("to") is not None
        if has_from != has_to:
            raise IntelligenceError(
                "invalid_argument", "from and to must be provided together", field="from"
            )
        start = end = None
        weeks = None
        if has_from:
            start = _date(data.get("from"), "from")
            end = _date(data.get("to"), "to")
            if start > end:
                raise IntelligenceError(
                    "invalid_argument", "from must not be after to", field="from"
                )
            if (end - start).days + 1 > MAX_RANGE_DAYS:
                raise IntelligenceError(
                    "invalid_argument", f"date range must be at most {MAX_RANGE_DAYS} days",
                    field="from",
                )
            if data.get("weeks") is not None:
                raise IntelligenceError(
                    "invalid_argument", "provide either weeks or from/to, not both",
                    field="weeks",
                )
        else:
            weeks = require_int(
                data.get("weeks", 8), "weeks", minimum=1, maximum=52
            )
        exercise_id = data.get("exercise_id")
        if exercise_id is not None and (
            not isinstance(exercise_id, str) or not exercise_id.strip()
        ):
            raise IntelligenceError(
                "invalid_argument", "exercise_id must be a non-empty string",
                field="exercise_id",
            )
        session_type = data.get("session_type")
        if session_type is not None and (
            not isinstance(session_type, str) or not session_type.strip()
        ):
            raise IntelligenceError(
                "invalid_argument", "session_type must be a non-empty string",
                field="session_type",
            )
        return cls(
            as_of=as_of, weeks=weeks, start=start, end=end, group_by=group_by,
            exercise_id=exercise_id.strip() if exercise_id else None,
            session_type=session_type.strip() if session_type else None,
        )


def _date(value: object, field: str) -> dt.date:
    if not isinstance(value, str):
        raise IntelligenceError("invalid_argument", f"{field} must be YYYY-MM-DD", field=field)
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise IntelligenceError(
            "invalid_argument", f"{field} must be YYYY-MM-DD", field=field
        ) from exc


def _query(request: AdherenceRequest) -> dict[str, object]:
    query: dict[str, object] = {"group_by": request.group_by}
    if request.start is not None and request.end is not None:
        query["from"] = request.start.isoformat()
        query["to"] = request.end.isoformat()
    else:
        query["date"] = request.as_of.isoformat()
        query["weeks"] = request.weeks
    if request.exercise_id:
        query["exercise_id"] = request.exercise_id
    if request.session_type:
        query["session_type"] = request.session_type
    return query


def adherence_analysis(
    conn: sqlite3.Connection, request: AdherenceRequest, execution: ExecutionContext
) -> Envelope:
    report = adherence_analytics.analytics(conn, _query(request))
    planned = report.get("final_plan") or {}
    status = str(report.get("status") or "unavailable")
    has_data = bool(planned.get("has_data"))
    periods = list(planned.get("periods") or [])[:MAX_PERIODS]
    exercises = list(planned.get("exercises") or [])[:MAX_EXERCISES]
    workouts = list(report.get("workouts") or [])[:MAX_WORKOUTS]

    facts = {
        "adherence": FactBlock(
            value={"status": status, "reason": report.get("reason"),
                   "range": report.get("range")},
            basis="derived",
            method="strength_coach.features.adherence_analytics.analytics",
        ),
        "totals": FactBlock(
            value={
                key: planned.get(key)
                for key in (
                    "workouts", "prescribed_sets", "performed_sets", "matched_sets",
                    "missing_sets", "extra_sets", "unattributable_planned_sets",
                    "warm_up_sets_excluded", "set_completion", "reps", "load", "rir",
                    "has_data", "small_sample",
                )
            },
            basis="derived",
            method="strength_coach.features.adherence_analytics.analytics",
            n=int(planned.get("prescribed_sets") or 0),
            gate="insufficient" if planned.get("small_sample") else "signal",
        ),
        "periods": FactBlock(
            value=periods,
            basis="derived",
            method="strength_coach.features.adherence_analytics.analytics",
            n=len(periods),
        ),
        "exercises": FactBlock(
            value=exercises,
            basis="derived",
            method="strength_coach.features.adherence_analytics.analytics",
            n=len(exercises),
        ),
        "coverage": FactBlock(
            value=report.get("coverage"),
            basis="derived",
            method="strength_coach.features.adherence_analytics.analytics",
        ),
    }
    if workouts:
        facts["workouts"] = FactBlock(
            value=workouts,
            basis="derived",
            method="strength_coach.features.adherence_analytics.analytics",
            n=len(workouts),
            note=f"at most {MAX_WORKOUTS} workouts are returned",
        )

    missing: list[str] = []
    if status != "available":
        missing.append(f"adherence is unavailable: {report.get('reason') or 'unknown reason'}")
    elif not has_data:
        missing.append("no comparable completed workout in the window")

    window = report.get("range") or {}
    start = str(window.get("from") or execution.generated_at[:10])
    end = str(window.get("to") or execution.generated_at[:10])
    days = max(1, (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1)

    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok" if (status == "available" and has_data) else "no_data",
        as_of=request.as_of.isoformat(),
        period=window_period(
            start, end, days, window.get("weeks"), execution.timezone
        ),
        facts=facts,
        coverage={
            "workouts": int(planned.get("workouts") or 0),
            "periods_returned": len(periods),
            "exercises_returned": len(exercises),
            "workouts_returned": len(workouts),
            "prescribed_sets": int(planned.get("prescribed_sets") or 0),
            "matched_sets": int(planned.get("matched_sets") or 0),
        },
        missing=missing,
        limitations=LIMITATIONS,
        execution=execution,
        arguments=request.to_mapping(),
        modules=MODULES,
    )


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only prescription-adherence analysis over app-tracked completed workouts: totals, "
            "weekly or monthly periods, per-exercise comparison and coverage; no block dimension."
        ),
        request_type=AdherenceRequest,
        handler=adherence_analysis,
    )
)
