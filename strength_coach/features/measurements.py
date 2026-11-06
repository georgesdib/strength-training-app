"""Periodic measurement metrics: VO2max, grip, function tests, steps, sitting.

Readiness is daily state that can reduce a load; a measurement is an outcome taken every few
weeks. The two must not be mixed: a VO2max estimate has no business changing today's squat
load, and a sleep score is not a longitudinal outcome.

The metric catalogue lives in `config/measurements.v1.yaml`. On first use each metric is
declared in `metric_definition` with its direction and aggregation, because a number whose
direction is assumed is a data bug waiting to happen (the `stress 5 = good` trap).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from strength_coach.store import queries, repositories
from strength_coach.utils import measurements as measurement_utils

AGGREGATIONS = measurement_utils.AGGREGATIONS
DEFAULT_SOURCE = "user"

# The catalogue is config and therefore lives in utils; these re-exports keep the feature's
# public names stable for callers and tests.
MeasurementError = measurement_utils.MeasurementError
MetricSpec = measurement_utils.MetricSpec
MeasurementConfig = measurement_utils.MeasurementConfig


def record(
    conn,
    *,
    metric_key: str,
    value: float,
    measured_on: str | None = None,
    method: str | None = None,
    note: str | None = None,
    source: str = DEFAULT_SOURCE,
    config: MeasurementConfig | None = None,
) -> MetricSpec:
    """Validate, declare the metric if needed, then append the measurement."""
    cfg = config or MeasurementConfig.load()
    spec = cfg.metrics.get(str(metric_key))
    if spec is None:
        known = ", ".join(cfg.metrics) or "none configured"
        raise MeasurementError(
            f"unknown measurement metric {metric_key!r}; configured: {known}"
        )

    try:
        day = dt.date.fromisoformat(measured_on) if measured_on else dt.date.today()
    except ValueError as exc:
        raise MeasurementError(f"date must be YYYY-MM-DD: {measured_on!r}") from exc
    number = spec.validate(value)

    _ensure_definition(conn, spec)
    repositories.append_measurement(
        conn,
        metric_key=spec.key,
        measured_on=day.isoformat(),
        value=number,
        method=method,
        source=source,
        note=note,
    )
    return spec


def _ensure_definition(conn, spec: MetricSpec) -> None:
    """Create the metric declaration once; refuse a direction/unit change later."""
    repositories.ensure_metric_definition(conn, spec)


def summary(conn, *, config: MeasurementConfig | None = None) -> list[dict[str, Any]]:
    """Latest, first and change for every configured metric (count 0 when unmeasured)."""
    cfg = config or MeasurementConfig.load()
    rows = queries.measurements(conn)
    grouped: dict[str, list[dict]] = {key: [] for key in cfg.metrics}
    for row in rows:
        grouped.setdefault(str(row["metric_key"]), []).append(row)

    out: list[dict[str, Any]] = []
    for key, spec in cfg.metrics.items():
        entries = grouped.get(key, [])
        first = entries[0] if entries else None
        latest = entries[-1] if entries else None
        change = (
            round(float(latest["value"]) - float(first["value"]), 3)
            if first is not None and latest is not None else None
        )
        out.append({
            **spec.as_dict(),
            "count": len(entries),
            "first_value": None if first is None else float(first["value"]),
            "first_on": None if first is None else str(first["measured_on"]),
            "latest_value": None if latest is None else float(latest["value"]),
            "latest_on": None if latest is None else str(latest["measured_on"]),
            "change": change,
        })
    return out


def entries(conn, *, metric_key: str | None = None,
            limit: int = 100) -> list[dict[str, Any]]:
    rows = queries.measurements(conn, metric_key=metric_key)
    return rows[-limit:]


def page(
    conn,
    *,
    metric_key: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Newest-first exact-record pagination; entries remain date-ascending.

    Offset 0 preserves the former latest-50 behavior. The next offset walks backwards in
    time; no record is invented for a date without a measurement.
    """
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    rows = queries.measurements(
        conn, metric_key=metric_key, since=since, until=until,
    )
    total = len(rows)
    end = max(0, total - offset)
    start = max(0, end - limit)
    entries = rows[start:end]
    next_offset = offset + limit if start > 0 else None
    return {
        "entries": entries,
        "page": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "next_offset": next_offset,
        },
    }
