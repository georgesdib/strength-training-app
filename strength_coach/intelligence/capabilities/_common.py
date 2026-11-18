"""Shared envelope construction for the INT-2 capabilities.

Only boilerplate: the capability name/version, period, units, privacy, provenance and the
defaults for evidence/observations. No analytical logic lives here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence

from strength_coach.intelligence.envelope import Envelope, Period, Privacy
from strength_coach.intelligence.service import ExecutionContext

UNITS = {"load": "kg", "velocity": "m/s", "duration": "min", "ratio": "ratio"}

TRAINING_PRIVACY = Privacy(
    classification="training",
    excluded_fields=("session notes", "symptom values", "body measurements", "free text"),
    redactions=(),
)

HEALTH_PRIVACY = Privacy(
    classification="health",
    excluded_fields=("session notes", "symptom narratives", "injury details", "free text"),
    redactions=("readiness values returned only for explicitly requested fields",),
)


def day_period(day: str, timezone: str) -> Period:
    return Period(start=day, end=day, days=1, weeks=None, timezone=timezone)


def window_period(start: str, end: str, days: int, weeks: int | None, timezone: str) -> Period:
    return Period(start=start, end=end, days=days, weeks=weeks, timezone=timezone)


def envelope(
    *,
    capability: str,
    version: str,
    status: str,
    as_of: str,
    period: Period,
    facts: Mapping[str, object],
    coverage: Mapping[str, int | float | str | None],
    execution: ExecutionContext,
    arguments: Mapping[str, object],
    modules: Sequence[str],
    missing: Sequence[str] = (),
    limitations: Sequence[str] = (),
    privacy: Privacy = TRAINING_PRIVACY,
    evidence: Sequence[Mapping[str, object]] = (),
    observations: Sequence[Mapping[str, object]] = (),
    quality_flags: Sequence[str] = (),
    units: Mapping[str, str] | None = None,
) -> Envelope:
    return Envelope(
        capability=capability,
        version=version,
        status=status,
        as_of=as_of,
        period=period,
        units=dict(UNITS) if units is None else dict(units),
        facts=facts,
        evidence=tuple(evidence),
        observations=tuple(observations),
        coverage=coverage,
        missing=tuple(missing),
        limitations=tuple(limitations),
        quality_flags=tuple(quality_flags),
        privacy=privacy,
        provenance=execution.provenance(
            capability=capability,
            version=version,
            arguments=arguments,
            modules=modules,
        ),
        generated_at=execution.generated_at,
    )


def parse_window(
    *,
    from_value: object,
    to_value: object,
    window_days: object,
    default_days: int,
    minimum_days: int,
    maximum_days: int,
    as_of: dt.date,
    require_from_to: bool = False,
) -> tuple[dt.date, dt.date]:
    """Resolve either explicit dates or a trailing window, with one validation rule."""
    from strength_coach.intelligence.errors import IntelligenceError
    from strength_coach.intelligence.registry import require_date, require_int

    has_from = from_value is not None
    has_to = to_value is not None
    has_window = window_days is not None
    if has_from != has_to:
        raise IntelligenceError(
            "invalid_argument", "from and to must be provided together", field="from"
        )
    if has_from and has_window:
        raise IntelligenceError(
            "invalid_argument", "provide either from/to or window_days, not both", field="window_days"
        )
    if not has_from and not has_window and require_from_to:
        raise IntelligenceError(
            "invalid_argument", "from and to are required", field="from"
        )
    if has_from:
        start = require_date(from_value, "from")
        end = require_date(to_value, "to")
        if start > end:
            raise IntelligenceError(
                "invalid_argument", "from must not be after to", field="from"
            )
        span = (end - start).days + 1
        if span > maximum_days:
            raise IntelligenceError(
                "invalid_argument", f"date range must be at most {maximum_days} days",
                field="from",
            )
        return start, end
    days = require_int(
        default_days if window_days is None else window_days,
        "window_days",
        minimum=minimum_days,
        maximum=maximum_days,
    )
    end = as_of
    return end - dt.timedelta(days=days - 1), end
