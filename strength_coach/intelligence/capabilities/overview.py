"""The first reference capability: a read-only training overview.

It composes the existing deterministic services and projects them into the canonical envelope. It
computes nothing itself: attendance, the performance ratio, the volume ledger and the deload state
are all produced by their owning modules, and readiness contributes a coverage count only.

Why the window is derived here rather than passed to attendance: the dashboard already uses the
same convention (7 * weeks - 1 days ending on the as-of date), and this capability deliberately
does not invent a second one.

What this capability does not do, by design:

* it does not return per-lift progression, VBT analysis or adherence detail (INT-2);
* it does not emit evidence items, because the owning services do not yet produce them for these
  aggregates; the envelope supports them and validates them, and INT-2 adds the producers;
* it does not read symptom, injury or body-measurement values. Those fields are projected out of
  the dashboard payload even when present.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach.features import deload as deload_feature
from strength_coach.features import progress
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import (
    Envelope,
    FactBlock,
    Period,
    Privacy,
)
from strength_coach.intelligence.errors import IntelligenceError
from strength_coach.intelligence.registry import (
    CAPABILITIES,
    CapabilityRequest,
    CapabilitySpec,
    payload_mapping,
    reject_unknown,
    require_date,
    require_int,
)
from strength_coach.intelligence.service import ExecutionContext
from strength_coach.store import queries
from strength_coach.utils import readiness as readiness_utils

CAPABILITY_NAME = "get_training_overview"
CAPABILITY_VERSION = "1.0.0"
DEFAULT_WINDOW_WEEKS = 4
MAX_WINDOW_WEEKS = 52

MODULES = (
    "strength_coach.features.progress",
    "strength_coach.features.attendance",
    "strength_coach.features.volume",
    "strength_coach.features.deload",
    "strength_coach.store.queries",
)

UNITS = {"load": "kg", "duration": "min", "ratio": "ratio"}

LIMITATIONS = (
    "Attendance is target-based; no planned-session calendar exists (DEC-W7-01).",
    "The performance ratio is derived from formula e1RM, not a measured maximum (LIM-24).",
    "Readiness contributes an observed-day count only; readiness values are excluded here.",
    "Per-lift progression and VBT analysis are separate capabilities (INT-2).",
    "No evidence items are emitted by this capability yet; INT-2 adds the producers.",
)


@dataclass(frozen=True)
class OverviewRequest(CapabilityRequest):
    as_of: dt.date
    window_weeks: int

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> OverviewRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("as_of", "window_weeks"))
        raw_as_of = data.get("as_of")
        as_of = today if raw_as_of is None else require_date(raw_as_of, "as_of")
        if as_of > today:
            raise IntelligenceError(
                "invalid_argument", "as_of must not be in the future", field="as_of"
            )
        if as_of.year < 2000:
            raise IntelligenceError(
                "invalid_argument", "as_of is outside the supported range", field="as_of"
            )
        weeks = require_int(
            data.get("window_weeks", DEFAULT_WINDOW_WEEKS),
            "window_weeks",
            minimum=1,
            maximum=MAX_WINDOW_WEEKS,
        )
        if weeks * 7 > config.max_window_days:
            raise IntelligenceError(
                "invalid_argument",
                f"window_weeks exceeds the configured {config.max_window_days}-day window limit",
                field="window_weeks",
            )
        return cls(as_of=as_of, window_weeks=weeks)

    def to_mapping(self) -> dict[str, object]:
        return {"as_of": self.as_of.isoformat(), "window_weeks": self.window_weeks}


def _attendance_value(attendance: dict) -> dict[str, object]:
    """Project the attendance payload; symptom-derived fields never leave this function."""
    return {
        "completed": attendance.get("completed"),
        "target": attendance.get("target"),
        "pct": attendance.get("pct"),
        "target_shortfall": attendance.get("target_shortfall"),
        "families": attendance.get("families"),
        "session_types": attendance.get("session_types"),
        "duration": attendance.get("duration"),
    }


def _deload_value(decision: object) -> dict[str, object]:
    if decision is None:
        return {"active": False, "reason": None, "trigger": None, "block_week": None}
    return {
        "active": True,
        "reason": getattr(decision, "reason", None),
        "trigger": getattr(decision, "trigger", None),
        "block_week": getattr(decision, "block_week", None),
    }


def overview(
    conn: sqlite3.Connection, request: OverviewRequest, execution: ExecutionContext
) -> Envelope:
    day = request.as_of.isoformat()
    weeks = request.window_weeks
    days = 7 * weeks
    start = (request.as_of - dt.timedelta(days=days - 1)).isoformat()

    dashboard = progress.dashboard(conn, day, weeks=weeks)
    deload = deload_feature.decision(conn, day)
    readiness_days = queries.readiness_series(
        conn, start, day, tuple(readiness_utils.READINESS_FIELDS)
    )

    attendance = dashboard["attendance"]
    coverage = dashboard["coverage"]
    performance = dashboard["performance"]
    volume = dashboard["volume"]

    completed = int(attendance.get("completed") or 0)
    observed = len(readiness_days)
    points = int(performance.get("n") or 0)

    facts = {
        "attendance": FactBlock(
            value=_attendance_value(attendance),
            basis="derived",
            method="strength_coach.features.attendance.summary",
            unit=None,
            n=completed,
            note="Target-based, not a stored plan.",
        ),
        "feedback_coverage": FactBlock(
            value={
                "sessions": coverage.get("sessions"),
                "with_srpe": coverage.get("with_srpe"),
                "pct": coverage.get("pct"),
            },
            basis="derived",
            method="strength_coach.features.progress.dashboard",
            n=int(coverage.get("sessions") or 0),
            note="All completed sessions up to as_of, not only the window.",
        ),
        "strength_trend": FactBlock(
            value={
                "latest": performance.get("latest"),
                "median_ratio": performance.get("median_ratio"),
                "points": performance.get("points") or [],
            },
            basis="derived",
            method="strength_coach.features.progress.dashboard",
            unit="ratio",
            n=points,
            gate="signal" if points else "insufficient",
            note="Session median e1RM ratio versus the prior 84-day best for the same lift.",
        ),
        "volume": FactBlock(
            value=list(volume),
            basis="derived",
            method="strength_coach.features.volume.compute",
            n=len(volume),
            note="Per-pattern weekly average against the configured landmarks.",
        ),
        "readiness_coverage": FactBlock(
            value={"observed_days": observed, "window_days": days},
            basis="derived",
            method="strength_coach.store.queries.readiness_series",
            n=observed,
            note="Counts only; readiness values are not returned.",
        ),
        "deload": FactBlock(
            value=_deload_value(deload),
            basis="derived",
            method="strength_coach.features.deload.decision",
            note="Scheduled and reactive triggers combined by the owning policy.",
        ),
    }

    missing: list[str] = []
    if completed == 0:
        missing.append("no completed sessions in the window")
    if attendance.get("target") is None:
        missing.append("no sessions-per-week target in the athlete profile")
    if observed == 0:
        missing.append("no readiness entries in the window")
    if points == 0:
        missing.append("no comparable e1RM observations in the window")
    if not volume:
        missing.append("no recorded working sets in the window")

    return Envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok" if completed else "no_data",
        as_of=day,
        period=Period(start=start, end=day, days=days, weeks=weeks, timezone=execution.timezone),
        units=UNITS,
        facts=facts,
        evidence=(),
        observations=(),
        coverage={
            "weeks": weeks,
            "window_days": days,
            "completed_sessions": completed,
            "readiness_days": observed,
            "volume_patterns": len(volume),
            "performance_points": points,
        },
        missing=tuple(missing),
        limitations=LIMITATIONS,
        quality_flags=(),
        privacy=Privacy(
            classification="training",
            excluded_fields=(
                "symptom level",
                "injury-free weeks",
                "session notes",
                "readiness values",
                "body measurements",
            ),
            redactions=(
                "readiness reduced to an observed-day count",
                "symptom fields removed from the attendance payload",
            ),
        ),
        provenance=execution.provenance(
            capability=CAPABILITY_NAME,
            version=CAPABILITY_VERSION,
            arguments=request.to_mapping(),
            modules=MODULES,
        ),
        generated_at=execution.generated_at,
    )


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only overview of attendance, volume, performance ratio and readiness coverage "
            "for a window of 1-52 weeks ending on a training date."
        ),
        request_type=OverviewRequest,
        handler=overview,
    )
)
