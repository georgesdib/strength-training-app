"""Longitudinal VBT analysis, read-only and projection-bounded."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach.features import vbt_performance
from strength_coach.intelligence.capabilities._common import envelope, parse_window, window_period
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

CAPABILITY_NAME = "get_vbt_analysis"
CAPABILITY_VERSION = "1.0.0"
DEFAULT_WINDOW_DAYS = 84
MIN_WINDOW_DAYS = 28
MAX_WINDOW_DAYS = 365
MAX_WEEKLY = 52
MAX_FINDINGS = 10

MODULES = ("strength_coach.features.vbt_performance",)

LIMITATIONS = (
    "VBT is sparse: several cohorts are insufficient by design, and every abstention reason is "
    "returned verbatim.",
    "Gates make a cohort readable or evaluable; they never authorize a load or prescription change.",
    "No fallback estimate is invented for an insufficient cohort.",
)


@dataclass(frozen=True)
class VbtRequest(CapabilityRequest):
    start: dt.date
    end: dt.date
    exercise_id: str | None

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> VbtRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("from", "to", "window_days", "as_of", "exercise_id"))
        as_of = today if data.get("as_of") is None else _date(data.get("as_of"), "as_of")
        if as_of > today:
            raise IntelligenceError(
                "invalid_argument", "as_of must not be in the future", field="as_of"
            )
        start, end = parse_window(
            from_value=data.get("from"),
            to_value=data.get("to"),
            window_days=data.get("window_days"),
            default_days=DEFAULT_WINDOW_DAYS,
            minimum_days=MIN_WINDOW_DAYS,
            maximum_days=MAX_WINDOW_DAYS,
            as_of=as_of,
        )
        exercise_id = data.get("exercise_id")
        if exercise_id is not None and (
            not isinstance(exercise_id, str) or not exercise_id.strip()
        ):
            raise IntelligenceError(
                "invalid_argument", "exercise_id must be a non-empty string",
                field="exercise_id",
            )
        return cls(start=start, end=end,
                   exercise_id=exercise_id.strip() if exercise_id else None)

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "from": self.start.isoformat(), "to": self.end.isoformat()
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


def vbt_analysis(
    conn: sqlite3.Connection, request: VbtRequest, execution: ExecutionContext
) -> Envelope:
    start = request.start.isoformat()
    end = request.end.isoformat()
    report = vbt_performance.analyse(
        conn, start=start, end=end, exercise_id=request.exercise_id
    )
    summary = report["summary"]
    drift = {key: value for key, value in report["drift"].items() if key != "sets"}
    drift["sets"] = len(report["drift"].get("sets") or [])
    weekly = list(report["weekly"])[:MAX_WEEKLY]
    cohorts = list(report["cohorts"])
    abstentions = [str(item) for item in summary.get("abstain") or []][:MAX_FINDINGS]

    days = (request.end - request.start).days + 1
    facts = {
        "summary": FactBlock(
            value=summary,
            basis="derived",
            method="strength_coach.features.vbt_performance.analyse",
            n=int(summary.get("target_sets") or 0),
            gate=_gate(summary),
        ),
        "gates": FactBlock(
            value=report["gates"],
            basis="observed",
            method="strength_coach.features.vbt_performance.analyse",
        ),
        "cohorts": FactBlock(
            value=cohorts,
            basis="derived",
            method="strength_coach.features.vbt_performance.analyse",
            n=len(cohorts),
        ),
        "weekly": FactBlock(
            value=weekly,
            basis="derived",
            method="strength_coach.features.vbt_performance.analyse",
            n=len(weekly),
            note=report.get("weekly_note"),
        ),
        "drift": FactBlock(
            value=drift,
            basis="derived",
            method="strength_coach.features.vbt_performance.analyse",
        ),
    }

    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok" if int(summary.get("target_sets") or 0) else "no_data",
        as_of=end,
        period=window_period(start, end, days, None, execution.timezone),
        facts=facts,
        coverage={
            "window_days": days,
            "target_sets": int(summary.get("target_sets") or 0),
            "comparable_sets": int(summary.get("comparable_sets") or 0),
            "cohorts": len(cohorts),
            "weekly": len(weekly),
            "abstentions": len(abstentions),
        },
        missing=tuple(abstentions),
        limitations=LIMITATIONS,
        execution=execution,
        arguments=request.to_mapping(),
        modules=MODULES,
    )


def _gate(summary: dict) -> str:
    if summary.get("evaluation_ready"):
        return "evaluation"
    if int(summary.get("comparable_sets") or 0):
        return "signal"
    return "insufficient"


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only longitudinal VBT analysis for 28-365 days: cohort gates, weekly residuals, "
            "within-set drift and explicit abstentions; per-set rows are summarised, not returned."
        ),
        request_type=VbtRequest,
        handler=vbt_analysis,
    )
)
