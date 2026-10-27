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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from strength_coach.store import queries, repositories
from strength_coach.utils import paths

AGGREGATIONS = ("mean", "max", "best_of_3", "last")
DEFAULT_SOURCE = "user"


class MeasurementError(ValueError):
    """A metric is unknown, mis-declared, or the value is outside a plausible range."""


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str | None
    higher_is_better: bool
    aggregation: str
    plausible_min: float | None = None
    plausible_max: float | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "unit": self.unit,
            "higher_is_better": self.higher_is_better,
            "aggregation": self.aggregation,
            "plausible_min": self.plausible_min,
            "plausible_max": self.plausible_max,
            "note": self.note,
        }


@dataclass(frozen=True)
class MeasurementConfig:
    metrics: Mapping[str, MetricSpec]
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> MeasurementConfig:
        source = Path(path or paths.measurements_yaml())
        if not source.exists():
            return cls(metrics={}, source_path=source)
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        metrics: dict[str, MetricSpec] = {}
        for key, body in (raw.get("metrics") or {}).items():
            name = str(key).strip()
            body = body or {}
            aggregation = str(body.get("aggregation", "last"))
            if aggregation not in AGGREGATIONS:
                raise MeasurementError(
                    f"{name}: aggregation must be one of {AGGREGATIONS}, got {aggregation!r}"
                )
            plausible = body.get("plausible") or (None, None)
            low = None if plausible[0] is None else float(plausible[0])
            high = None if plausible[1] is None else float(plausible[1])
            if low is not None and high is not None and low > high:
                raise MeasurementError(f"{name}: plausible min exceeds max")
            metrics[name] = MetricSpec(
                key=name,
                label=str(body.get("label", name)),
                unit=(str(body["unit"]) if body.get("unit") else None),
                higher_is_better=bool(body.get("higher_is_better", True)),
                aggregation=aggregation,
                plausible_min=low,
                plausible_max=high,
                note=str(body.get("note") or "").strip(),
            )
        if not metrics:
            raise MeasurementError("no measurement metrics configured")
        return cls(metrics=metrics, source_path=source)


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
    number = float(value)
    if spec.plausible_min is not None and number < spec.plausible_min:
        raise MeasurementError(
            f"{spec.key}={number:g} is below the plausible minimum {spec.plausible_min:g}"
        )
    if spec.plausible_max is not None and number > spec.plausible_max:
        raise MeasurementError(
            f"{spec.key}={number:g} is above the plausible maximum {spec.plausible_max:g}"
        )

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
    """Create the metric declaration once; refuse a direction change later.

    A previously declared metric keeps its original direction and unit. Silently accepting a
    different one would reinterpret every stored value, which is exactly the kind of quiet
    inversion the project forbids.
    """
    existing = queries.metric_definitions(conn).get(spec.key)
    if existing is None:
        repositories.append_metric_definition(
            conn,
            metric_key=spec.key,
            label=spec.label,
            higher_is_better=spec.higher_is_better,
            aggregation=spec.aggregation,
            scale_min=spec.plausible_min,
            scale_max=spec.plausible_max,
            unit=spec.unit,
            source="config",
        )
        return
    stored_direction = bool(existing["higher_is_better"])
    stored_unit = existing.get("unit")
    if stored_direction != spec.higher_is_better or stored_unit != spec.unit:
        raise MeasurementError(
            f"{spec.key} is already declared as higher_is_better="
            f"{stored_direction}, unit={stored_unit!r}; config says "
            f"{spec.higher_is_better}, unit={spec.unit!r}"
        )


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
