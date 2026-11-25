"""Versioned, date-effective registry of daily readiness inputs.

This module owns the registry payload: parsing, strict validation, the effective version for a
date, and an append-only save. It does NOT change the readiness score yet: WP3 wires the score
engine to this model, with golden equivalence to the pre-registry behaviour.

Payload shape (JSON in readiness_registry.payload_json):

    {
      "schema_version": 1,
      "min_core_fields": 3,
      "require_any_of": ["sleep", "energy"],
      "wearable_weight": 0.1,
      "metrics": [
        {"key": "sleep", "role": "core", "enabled": true, "weight": 1.0,
         "baseline_days": 0, "counts_as_core": true, "order": 1},
        {"key": "hrv_ms", "role": "device", "enabled": true, "weight": 0.5,
         "baseline_days": 28, "counts_as_core": false, "min_readings": 7,
         "slope": 0.5, "order": 6}
      ]
    }

Label, scale and direction are read from metric_definition, so the registry stores only the
operational fields. A key that is not in metric_definition is rejected.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from strength_coach.store import queries, repositories

SCHEMA_VERSION = 1
ROLES = ("core", "device")
CORE_WEIGHT_MAX = 2.0
DEVICE_WEIGHT_MAX = 1.0
WEIGHT_MIN = 0.05
WEARABLE_WEIGHT_MAX = 0.5


class RegistryError(ValueError):
    """A payload or edit that the registry must reject, with field-specific reasons."""

    def __init__(self, message: str, fields: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.fields = dict(fields or {})


@dataclass(frozen=True)
class RegistryMetric:
    key: str
    role: str
    enabled: bool
    weight: float
    baseline_days: int
    counts_as_core: bool
    order: int
    min_readings: int | None
    slope: float | None
    label: str
    scale_min: float | None
    scale_max: float | None
    higher_is_better: bool
    unit: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "role": self.role,
            "enabled": self.enabled,
            "weight": self.weight,
            "baseline_days": self.baseline_days,
            "counts_as_core": self.counts_as_core,
            "order": self.order,
            "min_readings": self.min_readings,
            "slope": self.slope,
            "scale_min": self.scale_min,
            "scale_max": self.scale_max,
            "higher_is_better": self.higher_is_better,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class Registry:
    registry_id: int | None
    effective_from: str | None
    schema_version: int
    min_core_fields: int
    require_any_of: tuple[str, ...]
    wearable_weight: float
    metrics: tuple[RegistryMetric, ...]

    @property
    def enabled(self) -> tuple[RegistryMetric, ...]:
        return tuple(metric for metric in self.metrics if metric.enabled)

    @property
    def core(self) -> tuple[RegistryMetric, ...]:
        return tuple(metric for metric in self.metrics if metric.role == "core")

    @property
    def device(self) -> tuple[RegistryMetric, ...]:
        return tuple(metric for metric in self.metrics if metric.role == "device")

    def metric(self, key: str) -> RegistryMetric | None:
        return next((item for item in self.metrics if item.key == key), None)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "min_core_fields": self.min_core_fields,
            "require_any_of": list(self.require_any_of),
            "wearable_weight": self.wearable_weight,
            "metrics": [
                {
                    "key": metric.key,
                    "role": metric.role,
                    "enabled": metric.enabled,
                    "weight": metric.weight,
                    "baseline_days": metric.baseline_days,
                    "counts_as_core": metric.counts_as_core,
                    "order": metric.order,
                    **(
                        {"min_readings": metric.min_readings, "slope": metric.slope}
                        if metric.role == "device"
                        else {}
                    ),
                }
                for metric in self.metrics
            ],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "effective_from": self.effective_from,
            "schema_version": self.schema_version,
            "min_core_fields": self.min_core_fields,
            "require_any_of": list(self.require_any_of),
            "wearable_weight": self.wearable_weight,
            "metrics": [metric.as_dict() for metric in self.metrics],
        }


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RegistryError(f"{field} must be a number", {field: "must be a number"})
    number = float(value)
    if not math.isfinite(number):
        raise RegistryError(
            f"{field} must be a finite number", {field: "must be finite"}
        )
    return number


def _integer(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RegistryError(f"{field} must be an integer", {field: "must be an integer"})
    if minimum is not None and value < minimum:
        raise RegistryError(
            f"{field} must be >= {minimum}", {field: f"must be >= {minimum}"}
        )
    return value


def _metric(
    raw: Any,
    index: int,
    definitions: Mapping[str, Mapping[str, Any]],
) -> RegistryMetric:
    field = f"metrics[{index}]"
    if not isinstance(raw, dict):
        raise RegistryError(f"{field} must be an object", {field: "must be an object"})
    key = raw.get("key")
    if not isinstance(key, str) or not key:
        raise RegistryError(f"{field}.key is required", {f"{field}.key": "required"})
    definition = definitions.get(key)
    if definition is None:
        raise RegistryError(
            f"{field}.key {key!r} is not declared in metric_definition",
            {f"{field}.key": "not in metric_definition"},
        )
    role = raw.get("role")
    if role not in ROLES:
        raise RegistryError(
            f"{field}.role must be one of {ROLES}", {f"{field}.role": "must be core or device"}
        )
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise RegistryError(f"{field}.enabled must be true or false",
                            {f"{field}.enabled": "must be a boolean"})
    weight = _number(raw.get("weight"), f"{field}.weight")
    if not WEIGHT_MIN <= weight <= (CORE_WEIGHT_MAX if role == "core" else DEVICE_WEIGHT_MAX):
        raise RegistryError(
            f"{field}.weight must be between {WEIGHT_MIN} and "
            f"{CORE_WEIGHT_MAX if role == 'core' else DEVICE_WEIGHT_MAX}",
            {f"{field}.weight": "out of bounds"},
        )
    baseline_days = _integer(raw.get("baseline_days"), f"{field}.baseline_days", minimum=0)
    counts_as_core = raw.get("counts_as_core")
    if not isinstance(counts_as_core, bool):
        raise RegistryError(f"{field}.counts_as_core must be true or false",
                            {f"{field}.counts_as_core": "must be a boolean"})
    order = _integer(raw.get("order"), f"{field}.order", minimum=1)

    if role == "core":
        if baseline_days != 0:
            raise RegistryError(
                f"{field}.baseline_days must be 0 for a core metric",
                {f"{field}.baseline_days": "must be 0 for core"},
            )
        if definition.get("scale_min") is None or definition.get("scale_max") is None:
            raise RegistryError(
                f"{field}.key {key!r} has no scale in metric_definition",
                {f"{field}.key": "missing scale"},
            )
        try:
            low = float(definition["scale_min"])
            high = float(definition["scale_max"])
        except (TypeError, ValueError) as exc:
            raise RegistryError(
                f"{field}.key {key!r} has a non-numeric scale",
                {f"{field}.key": "invalid scale"},
            ) from exc
        if not math.isfinite(low) or not math.isfinite(high) or high <= low:
            raise RegistryError(
                f"{field}.key {key!r} has an invalid scale",
                {f"{field}.key": "invalid scale"},
            )
        if raw.get("min_readings") is not None or raw.get("slope") is not None:
            raise RegistryError(
                f"{field} is core; min_readings/slope apply to device metrics only",
                {field: "core metric cannot set min_readings/slope"},
            )
        min_readings = None
        slope = None
    else:
        if baseline_days < 1:
            raise RegistryError(
                f"{field}.baseline_days must be >= 1 for a device metric",
                {f"{field}.baseline_days": "device metric needs a baseline"},
            )
        if counts_as_core:
            raise RegistryError(
                f"{field}.counts_as_core must be false for a device metric",
                {f"{field}.counts_as_core": "device metric cannot count as core"},
            )
        min_readings = _integer(raw.get("min_readings"), f"{field}.min_readings", minimum=1)
        slope = _number(raw.get("slope"), f"{field}.slope")
        if slope <= 0:
            raise RegistryError(f"{field}.slope must be positive",
                                {f"{field}.slope": "must be positive"})
        if int(definition.get("higher_is_better", 1)) not in (0, 1):
            raise RegistryError(
                f"{field}.key {key!r} has no direction in metric_definition",
                {f"{field}.key": "missing direction"},
            )

    return RegistryMetric(
        key=key,
        role=role,
        enabled=enabled,
        weight=weight,
        baseline_days=baseline_days,
        counts_as_core=counts_as_core,
        order=order,
        min_readings=min_readings,
        slope=slope,
        label=str(definition.get("label") or key),
        scale_min=definition.get("scale_min"),
        scale_max=definition.get("scale_max"),
        higher_is_better=bool(definition.get("higher_is_better", 1)),
        unit=definition.get("unit"),
    )


def parse(
    payload: str | Mapping[str, Any],
    definitions: Mapping[str, Mapping[str, Any]],
) -> Registry:
    """Parse and validate a registry payload. Raises RegistryError with field reasons."""
    raw = payload
    if isinstance(payload, str):
        try:
            raw = json.loads(payload)
        except ValueError as exc:
            raise RegistryError(
                f"payload is not valid JSON: {exc}", {"payload": "invalid JSON"}
            ) from exc
    if not isinstance(raw, dict):
        raise RegistryError("payload must be an object", {"payload": "must be an object"})

    schema_version = _integer(raw.get("schema_version"), "schema_version", minimum=1)
    if schema_version != SCHEMA_VERSION:
        raise RegistryError(
            f"schema_version {schema_version} is not supported (expected {SCHEMA_VERSION})",
            {"schema_version": "unsupported"},
        )
    min_core_fields = _integer(raw.get("min_core_fields"), "min_core_fields", minimum=1)
    wearable_weight = _number(raw.get("wearable_weight"), "wearable_weight")
    if not 0 <= wearable_weight <= WEARABLE_WEIGHT_MAX:
        raise RegistryError(
            f"wearable_weight must be between 0 and {WEARABLE_WEIGHT_MAX}",
            {"wearable_weight": "out of bounds"},
        )
    require_any_of_raw = raw.get("require_any_of")
    if not isinstance(require_any_of_raw, list) or not require_any_of_raw:
        raise RegistryError(
            "require_any_of must be a non-empty list",
            {"require_any_of": "must be a non-empty list"},
        )
    require_any_of = tuple(str(item) for item in require_any_of_raw)
    raw_metrics = raw.get("metrics")
    if not isinstance(raw_metrics, list) or not raw_metrics:
        raise RegistryError("metrics must be a non-empty list", {"metrics": "required"})

    metrics = tuple(
        _metric(item, index, definitions) for index, item in enumerate(raw_metrics)
    )
    keys = [metric.key for metric in metrics]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        raise RegistryError(
            f"duplicate metric keys: {', '.join(sorted(duplicates))}",
            {"metrics": "duplicate key"},
        )
    orders = [metric.order for metric in metrics]
    if len(set(orders)) != len(orders):
        raise RegistryError("metric order values must be unique", {"metrics": "duplicate order"})

    enabled_core = {
        metric.key
        for metric in metrics
        if metric.enabled and metric.role == "core" and metric.counts_as_core
    }
    if len(enabled_core) < min_core_fields:
        raise RegistryError(
            f"min_core_fields={min_core_fields} exceeds the {len(enabled_core)} enabled core "
            "metrics",
            {"min_core_fields": "exceeds enabled core metrics"},
        )
    unknown_required = [key for key in require_any_of if key not in enabled_core]
    if unknown_required:
        raise RegistryError(
            "require_any_of must name enabled core metrics: " + ", ".join(unknown_required),
            {"require_any_of": "names a metric that is not an enabled core metric"},
        )
    if not any(metric.enabled for metric in metrics):
        raise RegistryError("at least one metric must be enabled", {"metrics": "all disabled"})

    return Registry(
        registry_id=None,
        effective_from=None,
        schema_version=schema_version,
        min_core_fields=min_core_fields,
        require_any_of=require_any_of,
        wearable_weight=wearable_weight,
        metrics=tuple(sorted(metrics, key=lambda item: item.order)),
    )


def _canonical_date(value: str, field: str = "date") -> str:
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError) as exc:
        raise RegistryError(
            f"{field} must be YYYY-MM-DD", {field: "must be YYYY-MM-DD"}
        ) from exc


def load(conn, on_date: str) -> Registry | None:
    """Effective registry for a date, with metric_definition metadata attached."""
    on_date = _canonical_date(on_date, "on_date")
    row = queries.readiness_registry_row(conn, on_date)
    if row is None:
        return None
    registry = parse(row["payload_json"], queries.metric_definitions(conn))
    return replace(
        registry,
        registry_id=int(row["registry_id"]),
        effective_from=str(row["effective_from"]),
    )


def history(conn, limit: int = 50) -> list[dict]:
    """Version summaries, newest first; payloads are not returned in bulk."""
    out = []
    for row in queries.readiness_registry_history(conn, limit):
        payload = json.loads(row["payload_json"])
        out.append({
            "registry_id": int(row["registry_id"]),
            "effective_from": str(row["effective_from"]),
            "schema_version": int(row["schema_version"]),
            "created_at": row["created_at"],
            "note": row["note"],
            "metrics": len(payload.get("metrics") or []),
            "min_core_fields": payload.get("min_core_fields"),
            "wearable_weight": payload.get("wearable_weight"),
            "digest": hashlib.sha256(
                str(row["payload_json"]).encode("utf-8")
            ).hexdigest()[:12],
        })
    return out


def _today() -> str:
    return dt.date.today().isoformat()


def save(
    conn,
    payload: str | Mapping[str, Any],
    *,
    effective_from: str | None = None,
    note: str | None = None,
) -> Registry:
    """Validate and append a version. No backdating: effective_from defaults to today."""
    day = effective_from or _today()
    try:
        parsed_day = dt.date.fromisoformat(day)
    except ValueError as exc:
        raise RegistryError("effective_from must be YYYY-MM-DD",
                            {"effective_from": "must be YYYY-MM-DD"}) from exc
    if parsed_day < dt.date.fromisoformat(_today()):
        raise RegistryError(
            "effective_from cannot be in the past",
            {"effective_from": "cannot be in the past"},
        )
    day = parsed_day.isoformat()
    registry = parse(payload, queries.metric_definitions(conn))
    payload_json = json.dumps(registry.to_payload(), sort_keys=True)
    registry_id = repositories.append_readiness_registry(
        conn,
        effective_from=day,
        payload_json=payload_json,
        schema_version=registry.schema_version,
        note=note,
    )
    return replace(registry, registry_id=registry_id, effective_from=day)


def diff(current: Registry | None, candidate: Registry) -> list[str]:
    """Human-readable differences between the effective and a candidate registry."""
    changes: list[str] = []
    if current is None:
        return ["no effective registry; candidate would be the first version"]
    for field in ("schema_version", "min_core_fields", "wearable_weight"):
        before = getattr(current, field)
        after = getattr(candidate, field)
        if before != after:
            changes.append(f"{field}: {before} -> {after}")
    if current.require_any_of != candidate.require_any_of:
        changes.append(
            "require_any_of: "
            f"{', '.join(current.require_any_of)} -> {', '.join(candidate.require_any_of)}"
        )
    before_metrics = {metric.key: metric for metric in current.metrics}
    after_metrics = {metric.key: metric for metric in candidate.metrics}
    for key in sorted(set(before_metrics) | set(after_metrics)):
        before = before_metrics.get(key)
        after = after_metrics.get(key)
        if before is None:
            changes.append(f"add metric {key} ({after.role}, weight {after.weight:g})")
            continue
        if after is None:
            changes.append(f"remove metric {key}")
            continue
        for field in (
            "enabled", "weight", "baseline_days", "counts_as_core", "order",
            "min_readings", "slope",
        ):
            if getattr(before, field) != getattr(after, field):
                changes.append(f"{key}.{field}: {getattr(before, field)} -> {getattr(after, field)}")
    return changes


def preview(conn, payload: str | Mapping[str, Any], *, on_date: str | None = None) -> dict[str, Any]:
    """Validate a candidate without writing it; return the effective date and the diff."""
    day = _canonical_date(on_date or _today(), "on_date")
    candidate = parse(payload, queries.metric_definitions(conn))
    current = load(conn, day)
    return {
        "ok": True,
        "on_date": day,
        "changes": diff(current, candidate),
        "candidate": candidate.as_dict(),
    }
