"""Programme block summary: a derived reporting window over the rolling programme.

There is no stored training block (DEC-PROGRAMME-01) and no planned-session calendar
(DEC-W7-01). The window is derived from the request; every value inside it comes from its owner.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach import settings_profile
from strength_coach.features import attendance, breaks, deload, regime_change
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

CAPABILITY_NAME = "get_programme_block_summary"
CAPABILITY_VERSION = "1.0.0"
DEFAULT_WEEKS = 4
ALLOWED_WEEKS = (4, 6, 8)
MAX_FINDINGS = 10
MAX_BREAKS = 10

MODULES = (
    "strength_coach.settings_profile",
    "strength_coach.features.deload",
    "strength_coach.features.regime_change",
    "strength_coach.features.breaks",
    "strength_coach.features.attendance",
)

LIMITATIONS = (
    "No stored training block exists; this is a derived reporting window (DEC-PROGRAMME-01).",
    "Attendance is target-based; no planned-session calendar exists (DEC-W7-01).",
    "Regime findings are descriptive questions, never a verdict or a prescription change.",
    "The volume budget is configuration, not a measured individual threshold (LIM-20).",
)


@dataclass(frozen=True)
class ProgrammeRequest(CapabilityRequest):
    as_of: dt.date
    block_weeks: int

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> ProgrammeRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("as_of", "block_weeks"))
        if data.get("as_of") is None:
            as_of = today
        else:
            if not isinstance(data["as_of"], str):
                raise IntelligenceError(
                    "invalid_argument", "as_of must be YYYY-MM-DD", field="as_of"
                )
            try:
                as_of = dt.date.fromisoformat(data["as_of"])
            except ValueError as exc:
                raise IntelligenceError(
                    "invalid_argument", "as_of must be YYYY-MM-DD", field="as_of"
                ) from exc
            if as_of > today:
                raise IntelligenceError(
                    "invalid_argument", "as_of must not be in the future", field="as_of"
                )
        weeks = require_int(
            data.get("block_weeks", DEFAULT_WEEKS), "block_weeks", minimum=4, maximum=8
        )
        if weeks not in ALLOWED_WEEKS:
            raise IntelligenceError(
                "invalid_argument", "block_weeks must be 4, 6 or 8", field="block_weeks"
            )
        return cls(as_of=as_of, block_weeks=weeks)

    def to_mapping(self) -> dict[str, object]:
        return {"as_of": self.as_of.isoformat(), "block_weeks": self.block_weeks}


def _deload_value(decision: object) -> dict[str, object]:
    if decision is None:
        return {"active": False, "reason": None, "trigger": None, "block_week": None}
    return {
        "active": True,
        "reason": getattr(decision, "reason", None),
        "trigger": getattr(decision, "trigger", None),
        "block_week": getattr(decision, "block_week", None),
    }


def programme_block(
    conn: sqlite3.Connection, request: ProgrammeRequest, execution: ExecutionContext
) -> Envelope:
    end = request.as_of
    start = end - dt.timedelta(days=7 * request.block_weeks - 1)
    day = end.isoformat()

    state = settings_profile.state(conn, day)
    settings = {
        "profile_id": state.get("profile_id"),
        "effective_from": state.get("effective_from"),
        "reason": state.get("reason"),
        "budget": state.get("budget"),
    }
    deload_value = _deload_value(deload.decision(conn, day))
    regime = regime_change.detect(conn, on_date=day)
    declared = breaks.as_dict(breaks.all_breaks(conn))[:MAX_BREAKS]
    attendance_value = attendance.summary(
        conn, start=start, end=end, weeks=request.block_weeks
    )

    facts = {
        "window": FactBlock(
            value={
                "as_of": day,
                "start": start.isoformat(),
                "end": day,
                "weeks": request.block_weeks,
            },
            basis="observed",
            method="strength_coach.settings_profile.state",
            note="Derived reporting window; no stored block exists.",
        ),
        "settings": FactBlock(
            value=settings,
            basis="observed",
            method="strength_coach.settings_profile.state",
        ),
        "deload": FactBlock(
            value=deload_value,
            basis="derived",
            method="strength_coach.features.deload.decision",
        ),
        "regime": FactBlock(
            value={
                "window": regime.get("window"),
                "findings": list(regime.get("findings") or [])[:MAX_FINDINGS],
                "coverage": regime.get("coverage"),
                "note": regime.get("note"),
            },
            basis="derived",
            method="strength_coach.features.regime_change.detect",
            n=len(list(regime.get("findings") or [])[:MAX_FINDINGS]),
        ),
        "breaks": FactBlock(
            value=declared,
            basis="observed",
            method="strength_coach.features.breaks.all_breaks",
            n=len(declared),
        ),
        "attendance": FactBlock(
            value={
                key: attendance_value.get(key)
                for key in (
                    "weeks", "from", "to", "completed", "target", "pct",
                    "target_shortfall", "families", "session_types", "duration",
                )
            },
            basis="derived",
            method="strength_coach.features.attendance.summary",
            n=int(attendance_value.get("completed") or 0),
        ),
    }

    missing: list[str] = []
    if state.get("profile_id") is None:
        missing.append("no settings profile is recorded")
    if not int(attendance_value.get("completed") or 0):
        missing.append("no completed sessions in the window")

    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok" if state.get("profile_id") is not None or attendance_value.get("completed")
        else "no_data",
        as_of=day,
        period=window_period(
            start.isoformat(), day, 7 * request.block_weeks, request.block_weeks,
            execution.timezone,
        ),
        facts=facts,
        coverage={
            "weeks": request.block_weeks,
            "completed_sessions": int(attendance_value.get("completed") or 0),
            "regime_findings": len(list(regime.get("findings") or [])[:MAX_FINDINGS]),
            "breaks": len(declared),
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
            "Read-only summary of a derived 4/6/8-week programme window: settings and volume "
            "budget, deload state, regime findings, declared breaks and target-based attendance. "
            "No stored block or planned-session calendar exists."
        ),
        request_type=ProgrammeRequest,
        handler=programme_block,
    )
)
