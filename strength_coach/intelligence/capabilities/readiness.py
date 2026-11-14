"""Readiness history: observed values and the owner's score, read-only.

The score is computed by its owning service per observed day, never re-derived here. Raw readiness
fields are returned only when the caller names them; the default is the score only.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach.features import readiness_score
from strength_coach.intelligence.capabilities._common import (
    HEALTH_PRIVACY,
    envelope,
    window_period,
)
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
from strength_coach.utils import readiness as readiness_utils

CAPABILITY_NAME = "get_readiness_history"
CAPABILITY_VERSION = "1.0.0"
MAX_RANGE_DAYS = 366
MAX_SCORE_DAYS = 120

MODULES = (
    "strength_coach.store.queries.readiness_series",
    "strength_coach.features.readiness_score",
)

LIMITATIONS = (
    "Observed dates only: missing days are not filled or interpolated.",
    "The readiness score is a fixed policy composite, not a measurement (LIM-02, LIM-62).",
    "Values are returned only for the fields the caller names; health data is not implied.",
)


@dataclass(frozen=True)
class ReadinessRequest(CapabilityRequest):
    start: dt.date
    end: dt.date
    fields: tuple[str, ...]

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> ReadinessRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("from", "to", "fields"))
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
        if end > today:
            raise IntelligenceError(
                "invalid_argument", "to must not be in the future", field="to"
            )
        fields = _fields(data.get("fields"))
        return cls(start=start, end=end, fields=fields)

    def to_mapping(self) -> dict[str, object]:
        return {
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "fields": list(self.fields),
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


ALLOWED_FIELDS = tuple(readiness_utils.READINESS_FIELDS) + ("score",)


def _fields(value: object) -> tuple[str, ...]:
    if value is None:
        return ("score",)
    if not isinstance(value, list) or not value:
        raise IntelligenceError(
            "invalid_argument", "fields must be a non-empty list", field="fields"
        )
    cleaned: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or entry not in ALLOWED_FIELDS:
            raise IntelligenceError(
                "invalid_argument",
                "unknown readiness field; use score or a ready-made readiness field",
                field="fields",
            )
        if entry not in cleaned:
            cleaned.append(entry)
    return tuple(cleaned)


def readiness_history(
    conn: sqlite3.Connection, request: ReadinessRequest, execution: ExecutionContext
) -> Envelope:
    start = request.start.isoformat()
    end = request.end.isoformat()
    window_days = (request.end - request.start).days + 1

    observed = queries.readiness_series(
        conn, start, end, tuple(readiness_utils.READINESS_FIELDS)
    )
    observed_days = [point["date"] for point in observed]

    facts: dict[str, FactBlock] = {}
    raw_fields = tuple(field for field in request.fields if field != "score")
    if raw_fields:
        points = queries.readiness_series(conn, start, end, raw_fields)
        facts["readiness"] = FactBlock(
            value=points,
            basis="observed",
            method="strength_coach.store.queries.readiness_series",
            n=len(points),
        )

    score_days = 0
    truncated = False
    if "score" in request.fields:
        selected = observed_days[-MAX_SCORE_DAYS:]
        truncated = len(observed_days) > MAX_SCORE_DAYS
        scores = []
        for day in selected:
            assessment = readiness_score.compute(conn, day)
            payload = assessment.as_dict()
            scores.append({
                "date": day,
                "score": payload.get("score"),
                "status": payload.get("status"),
                "basis": payload.get("basis"),
            })
        score_days = len(scores)
        facts["score_series"] = FactBlock(
            value=scores,
            basis="derived",
            method="strength_coach.features.readiness_score.compute",
            n=score_days,
            gate="signal" if score_days else "insufficient",
        )
        if truncated:
            scores_note = f"score series limited to the most recent {MAX_SCORE_DAYS} observed days"
        else:
            scores_note = None
    else:
        scores_note = None

    missing: list[str] = []
    if not observed_days:
        missing.append("no readiness entries in the window")
    if truncated and scores_note:
        missing.append(scores_note)

    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok" if observed_days else "no_data",
        as_of=end,
        period=window_period(start, end, window_days, None, execution.timezone),
        facts=facts,
        coverage={
            "window_days": window_days,
            "observed_days": len(observed_days),
            "missing_days": window_days - len(observed_days),
            "score_days": score_days,
            "score_truncated": int(truncated),
        },
        missing=missing,
        limitations=LIMITATIONS,
        privacy=HEALTH_PRIVACY,
        execution=execution,
        arguments=request.to_mapping(),
        modules=MODULES,
    )


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only readiness history for a date window: observed raw values only when named, "
            "otherwise the owner's score series; missing days are reported, never filled."
        ),
        request_type=ReadinessRequest,
        handler=readiness_history,
    )
)
