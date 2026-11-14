"""Exercise progression: the existing e1RM trend for one lift, read-only."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach.features import exercise_history, strength_trend
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
from strength_coach.utils import exercises

CAPABILITY_NAME = "get_exercise_progression"
CAPABILITY_VERSION = "1.0.0"
DEFAULT_WINDOW_DAYS = 84
MIN_WINDOW_DAYS = 28
MAX_WINDOW_DAYS = 365

MODULES = (
    "strength_coach.features.strength_trend",
    "strength_coach.features.exercise_history",
    "strength_coach.utils.exercises",
)

LIMITATIONS = (
    "A calculated e1RM is not a tested maximum (LIM-24).",
    "Decay and measured-test calibration are not applied to this series.",
    "A changed load basis or equipment change breaks the series; breaks are reported, not smoothed.",
    "Fewer than five observations is descriptive only; no verdict is implied.",
)


@dataclass(frozen=True)
class ProgressionRequest(CapabilityRequest):
    exercise_id: str
    as_of: dt.date
    window_days: int
    include_sessions: bool
    limit_sessions: int

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> ProgressionRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("exercise_id", "as_of", "window_days",
                              "include_sessions", "limit_sessions"))
        exercise_id = data.get("exercise_id")
        if not isinstance(exercise_id, str) or not exercise_id.strip():
            raise IntelligenceError(
                "invalid_argument", "exercise_id is required", field="exercise_id"
            )
        as_of = today if data.get("as_of") is None else _date(data.get("as_of"), "as_of")
        if as_of > today:
            raise IntelligenceError(
                "invalid_argument", "as_of must not be in the future", field="as_of"
            )
        window = require_int(
            data.get("window_days", DEFAULT_WINDOW_DAYS),
            "window_days",
            minimum=MIN_WINDOW_DAYS,
            maximum=MAX_WINDOW_DAYS,
        )
        if window > config.max_window_days:
            raise IntelligenceError(
                "invalid_argument", "window_days exceeds the configured window limit",
                field="window_days",
            )
        include_sessions = data.get("include_sessions", False)
        if not isinstance(include_sessions, bool):
            raise IntelligenceError(
                "invalid_argument", "include_sessions must be true or false",
                field="include_sessions",
            )
        limit = require_int(
            data.get("limit_sessions", 5), "limit_sessions", minimum=1, maximum=20
        )
        return cls(
            exercise_id=exercise_id.strip(),
            as_of=as_of,
            window_days=window,
            include_sessions=include_sessions,
            limit_sessions=limit,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "exercise_id": self.exercise_id,
            "as_of": self.as_of.isoformat(),
            "window_days": self.window_days,
            "include_sessions": self.include_sessions,
            "limit_sessions": self.limit_sessions,
        }


def _date(value: object, field: str) -> dt.date:
    if not isinstance(value, str):
        raise IntelligenceError("invalid_argument", f"{field} must be YYYY-MM-DD", field=field)
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise IntelligenceError(
            "invalid_argument", f"{field} must be YYYY-MM-DD", field=field
        ) from exc


def _canonical(exercise_id: str) -> tuple[str, dict]:
    entities = exercises.taxonomy().entities
    canonical = exercise_id if exercise_id in entities else exercises.canonical_id(exercise_id)
    entity = entities.get(canonical or "")
    if canonical is None or entity is None:
        raise IntelligenceError("not_found", "unknown exercise", field="exercise_id")
    return canonical, entity


def progression(
    conn: sqlite3.Connection, request: ProgressionRequest, execution: ExecutionContext
) -> Envelope:
    canonical, entity = _canonical(request.exercise_id)
    end = request.as_of.isoformat()
    start = (request.as_of - dt.timedelta(days=request.window_days - 1)).isoformat()

    points = strength_trend.observations(conn, canonical, start, end)
    trend = strength_trend.rolling_median(points)
    breaks = strength_trend.series_breaks(points)
    summary = strength_trend.summarize(points)

    facts = {
        "exercise": FactBlock(
            value={
                "id": canonical,
                "display": entity.get("display"),
                "pattern": entity.get("pattern"),
                "main_lift": bool(entity.get("main_lift")),
            },
            basis="observed",
            method="strength_coach.utils.exercises.taxonomy",
        ),
        "series": FactBlock(
            value={
                "observations": [
                    {"date": point.date, "kg": round(point.estimate.kg, 1),
                     "session_id": point.session_id}
                    for point in points
                ],
                "rolling_median": [
                    {"date": point.date, "kg": round(point.kg, 1),
                     "rolling_median_kg": round(point.rolling_median_kg, 1),
                     "n_window": point.n_window}
                    for point in trend
                ],
                "breaks": [{"date": item.date, "reason": item.reason} for item in breaks],
            },
            basis="derived",
            method="strength_coach.features.strength_trend.observations",
            unit="kg",
            n=len(points),
            gate=_gate(len(points)),
        ),
        "summary": FactBlock(
            value=summary,
            basis="derived",
            method="strength_coach.features.strength_trend.summarize",
            unit="kg",
            n=len(points),
            gate=_gate(len(points)),
        ),
    }

    missing: list[str] = []
    if not points:
        missing.append("no eligible e1RM observations in the window")
    if request.include_sessions:
        history = exercise_history.history(
            conn, canonical, limit=request.limit_sessions, offset=0
        )
        facts["sessions"] = FactBlock(
            value=history["sessions"],
            basis="observed",
            method="strength_coach.features.exercise_history.history",
            n=len(history["sessions"]),
        )

    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok" if points else "no_data",
        as_of=end,
        period=window_period(start, end, request.window_days, None, execution.timezone),
        facts=facts,
        coverage={
            "window_days": request.window_days,
            "observations": len(points),
            "breaks": len(breaks),
            "sessions_returned": len(facts["sessions"].value) if "sessions" in facts else 0,
        },
        missing=missing,
        limitations=LIMITATIONS,
        execution=execution,
        arguments=request.to_mapping(),
        modules=MODULES,
    )


def _gate(n: int) -> str:
    if n == 0:
        return "insufficient"
    return "signal" if n < 5 else "evaluation"


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only e1RM progression for one canonical exercise over 28-365 days: raw "
            "observations, rolling median, series breaks and the owner's summary, with optional "
            "recent sessions."
        ),
        request_type=ProgressionRequest,
        handler=progression,
    )
)
