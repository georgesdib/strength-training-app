"""Longevity assessment: aerobic adequacy, VO2max status and volume headroom.

Facts only. The advisory prose the Today card and the chat show is written by a host model from
this envelope and is never part of it: the capability cannot recommend, and nothing it returns is
wired to a prescription (DEC-LONGEVITY-01, DEC-LONGEVITY-05).

Everything numeric comes from features.cardio_metrics.adequacy and
prescribe.volume_budget.headroom; this module composes and explains, it does not calculate.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from typing import Any

from strength_coach.features import cardio_metrics
from strength_coach.intelligence.capabilities._common import (
    UNITS,
    day_period,
    envelope,
    window_period,
)
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import Envelope, FactBlock, Privacy
from strength_coach.intelligence.errors import IntelligenceError
from strength_coach.intelligence.registry import (
    CAPABILITIES,
    CapabilityRequest,
    CapabilitySpec,
    payload_mapping,
    reject_unknown,
    require_date,
)
from strength_coach.intelligence.service import ExecutionContext
from strength_coach.prescribe import volume_budget

CAPABILITY_NAME = "get_longevity_assessment"
CAPABILITY_VERSION = "1.0.0"

MODULES = (
    "strength_coach.features.cardio_metrics.adequacy",
    "strength_coach.features.cardio_metrics.latest_vo2max",
    "strength_coach.prescribe.volume_budget.headroom",
)

LONGEVITY_PRIVACY = Privacy(
    classification="health",
    excluded_fields=(
        "session notes",
        "symptom narratives",
        "injury details",
        "free text",
    ),
    redactions=(
        "VO2max is the stored consumer estimate with its date, never a diagnosis",
    ),
)

LIMITATIONS = (
    "The WHO 150-300 minute band is context, not a target: no pass/fail is expressed "
    "(DEC-LONGEVITY-01).",
    "Cardio minutes are classified per workout from average METs or average heart rate, so a "
    "lifting session can read moderate and an interval session's rests dilute it (LIM-69).",
    "Time-in-zone is sample-based and covers only continuity-eligible workouts; it is reported "
    "separately and never merged into the weekly total.",
    "Recovery-tail heart-rate samples are retained in the corpus but excluded from workout "
    "classification and time-in-zone.",
    "Time-in-zone integrates elapsed time between adjacent workout samples, clipped to the "
    "workout; gaps over 120 s and the final sample are not allocated, and temporal coverage is "
    "reported separately from continuity eligibility.",
    "VO2max is a consumer estimate and carries no age/sex reference category by design (LIM-70); "
    "absence is not evidence of poor fitness.",
    "Pattern headroom is the configured volume budget, not a measurement of adaptation.",
    "No advice, recommendation or prose is returned: a host model writes that from these facts.",
)

LONGEVITY_UNITS = {**UNITS, "vo2max": "ml/kg/min"}


@dataclass(frozen=True)
class LongevityRequest(CapabilityRequest):
    as_of: dt.date
    include_time_in_zone: bool
    include_patterns: bool

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> LongevityRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("as_of", "include_time_in_zone", "include_patterns"))
        raw = data.get("as_of")
        as_of = today if raw is None else require_date(raw, "as_of")
        if as_of > today:
            raise IntelligenceError(
                "invalid_argument", "as_of must not be in the future", field="as_of"
            )
        return cls(
            as_of=as_of,
            include_time_in_zone=_flag(data.get("include_time_in_zone"), "include_time_in_zone"),
            include_patterns=_flag(data.get("include_patterns"), "include_patterns", default=True),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "include_time_in_zone": self.include_time_in_zone,
            "include_patterns": self.include_patterns,
        }


def _flag(value: object, field: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise IntelligenceError("invalid_argument", f"{field} must be a boolean", field=field)
    return value


def _status(last_week: dict[str, Any] | None) -> str:
    if last_week is None or float(last_week.get("total_minutes") or 0.0) <= 0:
        return "no_data"
    return "ok" if last_week.get("gate") == "signal" else "insufficient"


def longevity_assessment(
    conn: sqlite3.Connection, request: LongevityRequest, execution: ExecutionContext
) -> Envelope:
    day = request.as_of
    headroom = (
        volume_budget.headroom(conn, day.isoformat()) if request.include_patterns else None
    )
    result = cardio_metrics.assessment(
        conn,
        as_of=day.isoformat(),
        include_tiz=request.include_time_in_zone,
        patterns=headroom,
        sessions_remaining=(headroom or {}).get("sessions_remaining"),
    )

    last_week = result["last_week"]
    facts: dict[str, FactBlock] = {}
    if last_week is not None:
        facts["last_week"] = FactBlock(
            value={**last_week, "reference": result["reference"]},
            basis="derived",
            method="strength_coach.features.cardio_metrics.adequacy",
            n=int(last_week.get("workouts") or 0),
            gate=last_week.get("gate"),
        )
    facts["current_week"] = FactBlock(
        value=result["current_week"],
        basis="derived",
        method="strength_coach.features.cardio_metrics.adequacy",
        n=int(result["current_week"].get("workouts") or 0),
    )
    vo2max = result["vo2max"]
    facts["vo2max"] = FactBlock(
        value=vo2max,
        basis="observed",
        method="strength_coach.features.cardio_metrics.latest_vo2max",
        n=1 if vo2max.get("measured_on") else 0,
    )
    if result["time_in_zone"] is not None:
        block = result["time_in_zone"]
        facts["time_in_zone"] = FactBlock(
            value=block,
            basis="observed",
            method="strength_coach.features.cardio_metrics.time_in_zone",
            n=int(block.get("eligible_workouts") or 0),
            gate="signal" if block.get("eligible_workouts") else "insufficient",
        )
    if headroom is not None:
        facts["patterns"] = FactBlock(
            value=headroom,
            basis="derived",
            method="strength_coach.prescribe.volume_budget.headroom",
            n=len(headroom.get("per_pattern") or {}),
            gate="signal" if headroom.get("per_pattern") else "insufficient",
        )

    missing = list(result["missing"])
    if vo2max.get("status") == "absent":
        missing.append("no VO2max measurement has been recorded")

    coverage: dict[str, int | float | str | None] = {
        "workouts": int((last_week or {}).get("workouts") or 0),
        "unclassified_minutes": float((last_week or {}).get("unclassified_minutes") or 0.0),
        "classified_share": float((last_week or {}).get("classified_share") or 0.0),
        "vo2max_age_days": vo2max.get("age_days"),
        "time_in_zone_eligible_workouts": (
            int((result["time_in_zone"] or {}).get("eligible_workouts") or 0)
            if result["time_in_zone"] is not None
            else None
        ),
        "time_in_zone_temporal_coverage": (
            (result["time_in_zone"] or {}).get("temporal_coverage_share")
            if result["time_in_zone"] is not None
            else None
        ),
    }

    period = (
        window_period(
            last_week["start"], last_week["end"], 7, 1, execution.timezone
        )
        if last_week is not None
        else day_period(day.isoformat(), execution.timezone)
    )

    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status=_status(last_week),
        as_of=day.isoformat(),
        period=period,
        facts=facts,
        coverage=coverage,
        missing=missing,
        limitations=LIMITATIONS,
        privacy=LONGEVITY_PRIVACY,
        execution=execution,
        arguments=request.to_mapping(),
        modules=MODULES,
        units=LONGEVITY_UNITS,
    )


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only longevity facts: the last completed week's moderate-equivalent minutes "
            "against the WHO reference as context, the current week's progress, the latest "
            "VO2max with current/stale/absent, optional sample-based time-in-zone and the "
            "per-pattern volume headroom. No advice."
        ),
        request_type=LongevityRequest,
        handler=longevity_assessment,
    )
)
