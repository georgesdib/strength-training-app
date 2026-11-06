"""Measurement metric catalogue: declared direction, aggregation and plausible range.

Config, not code: `config/measurements.v1.yaml` is the source of the catalogue. It lives in
`utils` because two layers need it — the feature module that records/reads measurements and
the store importer that copies an exported Fat_Percent column into the measurement log — and
the lower layer may not import the higher one (AGENTS.md §4).

A metric whose direction is assumed is a data bug waiting to happen (the `stress 5 = good`
trap), so direction and aggregation are mandatory and a later direction/unit change is refused
by the store writer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from strength_coach.utils import paths

AGGREGATIONS = ("mean", "max", "best_of_3", "last")


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

    def validate(self, value: Any) -> float:
        """Refuse values the metric's plausible range cannot represent."""
        number = float(value)
        if self.plausible_min is not None and number < self.plausible_min:
            raise MeasurementError(
                f"{self.key}={number:g} is below the plausible minimum {self.plausible_min:g}"
            )
        if self.plausible_max is not None and number > self.plausible_max:
            raise MeasurementError(
                f"{self.key}={number:g} is above the plausible maximum {self.plausible_max:g}"
            )
        return number


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
