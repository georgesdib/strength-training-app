"""The weekly review capability: one deterministic Monday-Sunday package."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach.intelligence.capabilities._common import HEALTH_PRIVACY, envelope, window_period
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
from strength_coach.intelligence.reports import weekly_review
from strength_coach.intelligence.service import ExecutionContext

CAPABILITY_NAME = "get_weekly_review"
CAPABILITY_VERSION = "1.0.0"
MODULES = (
    "strength_coach.history.list_sessions",
    "strength_coach.features.attendance.summary",
    "strength_coach.features.adherence_analytics.analytics",
    "strength_coach.features.strength_trend.summarize",
    "strength_coach.features.volume.compute",
    "strength_coach.features.readiness_score.compute",
    "strength_coach.features.deload.decision",
    "strength_coach.features.regime_change.detect",
    "strength_coach.features.breaks.active_on",
    "strength_coach.features.observations.analyse",
)


@dataclass(frozen=True)
class WeeklyRequest(CapabilityRequest):
    week_end: dt.date
    include_observations: bool
    today: dt.date

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> WeeklyRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("week_end", "include_observations"))
        if data.get("week_end") is None:
            week_end = today - dt.timedelta(days=today.weekday() + 1)
        else:
            value = data["week_end"]
            if not isinstance(value, str):
                raise IntelligenceError(
                    "invalid_argument", "week_end must be YYYY-MM-DD", field="week_end"
                )
            try:
                week_end = dt.date.fromisoformat(value)
            except ValueError as exc:
                raise IntelligenceError(
                    "invalid_argument", "week_end must be YYYY-MM-DD", field="week_end"
                ) from exc
            if week_end > today:
                raise IntelligenceError(
                    "invalid_argument", "week_end must not be in the future", field="week_end"
                )
        include_observations = data.get("include_observations", True)
        if not isinstance(include_observations, bool):
            raise IntelligenceError(
                "invalid_argument", "include_observations must be true or false",
                field="include_observations",
            )
        return cls(week_end=week_end, include_observations=include_observations, today=today)

    def to_mapping(self) -> dict[str, object]:
        return {
            "week_end": self.week_end.isoformat(),
            "include_observations": self.include_observations,
        }


def weekly_review_capability(
    conn: sqlite3.Connection, request: WeeklyRequest, execution: ExecutionContext
) -> Envelope:
    report = weekly_review.build(
        conn,
        week_end=request.week_end,
        include_observations=request.include_observations,
        today=request.today,
    )
    facts = {
        name: FactBlock(
            value=section.value,
            basis=section.basis,
            method=section.method,
            n=section.n,
            gate=section.gate,
        )
        for name, section in report.sections.items()
    }
    days = (dt.date.fromisoformat(report.week_end)
            - dt.date.fromisoformat(report.week_start)).days + 1
    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status=report.status,
        as_of=report.week_end,
        period=window_period(
            report.week_start, report.week_end, days, 1, execution.timezone
        ),
        facts=facts,
        observations=[
            {
                "family": item["family"],
                "text": item["text"],
                "gate": item.get("gate"),
                "n": item.get("n"),
                "evidence_id": item.get("evidence_id"),
                "limitations": item.get("limitations") or (),
            }
            for item in report.observations
        ],
        coverage=report.coverage,
        missing=report.missing,
        limitations=report.limitations,
        quality_flags=report.quality_flags,
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
            "Deterministic Monday-Sunday weekly review: activity, adherence, completed sessions, "
            "main-lift progression, volume, readiness coverage and direction, programme state and "
            "at most two gated observations. No narrative and no model."
        ),
        request_type=WeeklyRequest,
        handler=weekly_review_capability,
    )
)
