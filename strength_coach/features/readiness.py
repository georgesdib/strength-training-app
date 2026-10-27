"""Readiness configuration: how the daily input is derived and what moves a load.

The mechanical pipeline — sentinel mapping, numeric coercion, the duplicate-row merge — lives in
`ingest.readiness` and is documented in `docs/READINESS.md`. This module holds the parts a user
may want to change: which fields the fatigue modifier reads, at what threshold, and which merge
strategy is in force.

Only the implemented strategies are accepted. A config value that silently did nothing would be
worse than an error, because the athlete would believe they had changed the behaviour.
"""

from __future__ import annotations

import datetime
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from strength_coach.store import repositories
from strength_coach.utils import paths
from strength_coach.utils import readiness as readiness_utils

KNOWN_FIELDS = readiness_utils.READINESS_FIELDS
MERGE_STRATEGIES = ("most_complete",)
TIE_BREAKS = ("latest",)


CONTEXT_FLAGS = (
    "travel", "timezone_change", "illness", "alcohol",
    "poor_sleep_environment", "high_work_stress",
)


class ReadinessConfigError(ValueError):
    """The readiness configuration is invalid or asks for something unimplemented."""


@dataclass(frozen=True)
class ReadinessConfig:
    modifier_fields: tuple[str, ...] = ("sleep", "energy")
    at_or_below: float = 2.0
    merge_strategy: str = "most_complete"
    tie_break: str = "latest"
    composite_enabled: bool = False
    baseline_days: int = 28
    baseline_min_readings: int = 7
    hrv_slope: float = 0.5
    rhr_slope: float = 0.5
    hrv_weight: float = 0.5
    rhr_weight: float = 0.5
    wearable_weight: float = 0.10
    context_flags: tuple[str, ...] = (
        "travel", "timezone_change", "illness", "alcohol",
        "poor_sleep_environment", "high_work_stress",
    )
    device_suppression_flags: tuple[str, ...] = ()
    set_reduction_enabled: bool = True
    set_reduction_score_below: float = 0.50
    set_reduction_sets: int = 1
    set_reduction_include_essential: bool = False
    setting_source: str = "config"
    source_path: Path = Path()

    def trigger(self, readiness: Mapping[str, Any] | None) -> str | None:
        """Which configured field, if any, crosses the fatigue threshold.

        Higher is better on every readiness scale, so a value *at or below* the threshold is
        the risk side. A missing value never triggers, and never counts as fine either — the
        caller reports that the modifier was not applied.
        """
        if not readiness:
            return None
        for field in self.modifier_fields:
            value = readiness.get(field)
            if value is None:
                continue
            try:
                if float(value) <= self.at_or_below:
                    return f"{field}={value:g}"
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def load(cls, path: str | Path | None = None) -> ReadinessConfig:
        source = Path(path or paths.readiness_yaml())
        if not source.exists():
            return cls(source_path=source)
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}

        merge = raw.get("merge") or {}
        strategy = str(merge.get("strategy", "most_complete"))
        tie_break = str(merge.get("tie_break", "latest"))
        if strategy not in MERGE_STRATEGIES:
            raise ReadinessConfigError(
                f"merge.strategy {strategy!r} is not implemented; known: {MERGE_STRATEGIES}"
            )
        if tie_break not in TIE_BREAKS:
            raise ReadinessConfigError(
                f"merge.tie_break {tie_break!r} is not implemented; known: {TIE_BREAKS}"
            )

        modifier = raw.get("modifier") or {}
        fields = tuple(str(f) for f in (modifier.get("fields") or ("sleep", "energy")))
        unknown = [f for f in fields if f not in KNOWN_FIELDS]
        if unknown:
            raise ReadinessConfigError(f"modifier.fields: unknown readiness fields {unknown}")

        context = raw.get("context") or {}
        context_flags = tuple(str(v) for v in (context.get("flags") or ()))
        suppression = tuple(str(v) for v in (context.get("device_suppression_flags") or ()))
        unknown_context = [f for f in (*context_flags, *suppression) if f not in CONTEXT_FLAGS]
        if unknown_context:
            raise ReadinessConfigError(f"context: unknown flags {unknown_context}")

        composite = raw.get("composite") or {}
        score = raw.get("score") or {}
        baseline_days = int(score.get("baseline_days", 28))
        baseline_min = int(score.get("baseline_min_readings", 7))
        hrv_slope = float(score.get("hrv_slope", 0.5))
        rhr_slope = float(score.get("rhr_slope", 0.5))
        hrv_weight = float(score.get("hrv_weight", 0.5))
        rhr_weight = float(score.get("rhr_weight", 0.5))
        wearable_weight = float(score.get("wearable_weight", 0.10))
        set_reduction = raw.get("set_reduction") or {}
        if baseline_days <= 0 or baseline_min <= 0:
            raise ReadinessConfigError("score baseline_days and baseline_min_readings must be positive")
        for name, value in (("hrv_slope", hrv_slope), ("rhr_slope", rhr_slope)):
            if not 0 < value <= 1:
                raise ReadinessConfigError(f"score.{name} must be in (0, 1]")
        for name, value in (("hrv_weight", hrv_weight), ("rhr_weight", rhr_weight),
                            ("wearable_weight", wearable_weight)):
            if not 0 <= value <= 1:
                raise ReadinessConfigError(f"score.{name} must be from 0 to 1")
        return cls(
            modifier_fields=fields,
            at_or_below=float(modifier.get("at_or_below", 2)),
            merge_strategy=strategy,
            tie_break=tie_break,
            composite_enabled=bool(composite.get("enabled", False)),
            baseline_days=baseline_days,
            baseline_min_readings=baseline_min,
            hrv_slope=hrv_slope,
            rhr_slope=rhr_slope,
            hrv_weight=hrv_weight,
            rhr_weight=rhr_weight,
            wearable_weight=wearable_weight,
            context_flags=context_flags,
            device_suppression_flags=suppression,
            set_reduction_enabled=bool(set_reduction.get("enabled", True)),
            set_reduction_score_below=float(set_reduction.get("score_below", 0.50)),
            set_reduction_sets=max(0, int(set_reduction.get("sets", 1))),
            set_reduction_include_essential=bool(
                set_reduction.get("include_essential", False)
            ),
            source_path=source,
        )


def save_set_reduction(
    *,
    enabled: bool,
    score_below: float,
    sets: int,
    include_essential: bool,
    path: str | Path | None = None,
) -> ReadinessConfig:
    """Write the volume-valve block without rewriting the rest of readiness config."""
    if not 0.0 <= float(score_below) <= 1.0:
        raise ValueError("set_reduction.score_below must be 0.00-1.00")
    if int(sets) < 0:
        raise ValueError("set_reduction.sets must be >= 0")
    source = Path(path or paths.readiness_yaml())
    text = source.read_text(encoding="utf-8")
    block = (
        "set_reduction:\n"
        "  # Poor readiness reduces load/RIR; this optional valve removes accessory sets.\n"
        f"  enabled: {'true' if enabled else 'false'}\n"
        f"  score_below: {float(score_below):.2f}\n"
        f"  sets: {int(sets)}\n"
        f"  include_essential: {'true' if include_essential else 'false'}\n"
    )
    pattern = re.compile(r"^set_reduction:\n(?:[ \t].*\n)*", re.MULTILINE)
    text = pattern.sub(block, text, count=1) if pattern.search(text) else text.rstrip() + "\n\n" + block
    fd, tmp = tempfile.mkstemp(prefix=source.name + ".", dir=str(source.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, source)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return ReadinessConfig.load(source)


def as_dict(config: ReadinessConfig) -> dict[str, Any]:
    return {
        "modifier_fields": list(config.modifier_fields),
        "at_or_below": config.at_or_below,
        "merge_strategy": config.merge_strategy,
        "tie_break": config.tie_break,
        "composite_enabled": config.composite_enabled,
        "baseline_days": config.baseline_days,
        "baseline_min_readings": config.baseline_min_readings,
        "hrv_slope": config.hrv_slope,
        "rhr_slope": config.rhr_slope,
        "hrv_weight": config.hrv_weight,
        "rhr_weight": config.rhr_weight,
        "wearable_weight": config.wearable_weight,
        "context_flags": list(config.context_flags),
        "device_suppression_flags": list(config.device_suppression_flags),
        "set_reduction_enabled": config.set_reduction_enabled,
        "set_reduction_score_below": config.set_reduction_score_below,
        "set_reduction_sets": config.set_reduction_sets,
        "set_reduction_include_essential": config.set_reduction_include_essential,
        "setting_source": config.setting_source,
    }


def record_manual(conn, on_date: str, values: Mapping[str, float],
                  note: str | None = None) -> int:
    """Validate the whole reading, then append one entry per provided field.

    Shared by the CLI and the web UI so both obey the same precedence and validation. A
    half-written day would be worse than a rejected one, so every value is checked first.
    """
    try:
        datetime.date.fromisoformat(on_date)
    except ValueError as exc:
        raise ValueError(f"date must be YYYY-MM-DD: {on_date}") from exc
    if not values:
        raise ValueError("give at least one readiness field")
    for field, value in values.items():
        if field in readiness_utils.LEGACY_FIELDS:
            raise ValueError(f"{field} is a legacy calibration label, not a readiness input")
        readiness_utils.validate(field, value)
    # A multi-field save must be all-or-nothing: a constraint error halfway through would
    # leave a partial readiness day that looks like a complete reading.
    started = not conn.in_transaction
    if started:
        conn.execute("BEGIN IMMEDIATE")
    try:
        for field in sorted(values):
            repositories.append_readiness_entry(
                conn, on_date=on_date, field=field, value=float(values[field]), note=note,
            )
    except Exception:
        if started:
            conn.execute("ROLLBACK")
        raise
    if started:
        conn.execute("COMMIT")
    return len(values)


PRESET_FIELDS = ("sleep", "energy", "soreness", "stress")


def presets(path: str | Path | None = None) -> dict[str, dict]:
    """Configured quick-readiness presets. Values are ordinary 1-5 readings."""
    source = Path(path or paths.config_dir("readiness-presets.v1.yaml"))
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    out = {}
    for name, body in (raw.get("presets") or {}).items():
        values = body.get("values") or {}
        if not all(field in values for field in PRESET_FIELDS):
            raise ValueError(f"preset {name!r} must define {PRESET_FIELDS}")
        clean = {field: int(values[field]) for field in PRESET_FIELDS}
        if not all(1 <= value <= 5 for value in clean.values()):
            raise ValueError(f"preset {name!r} values must be 1-5")
        out[str(name)] = {
            "label": str(body.get("label") or name),
            "values": clean,
            "context_flags": tuple(str(v) for v in (body.get("context_flags") or ())),
        }
    return out


def record_preset(conn, on_date: str, name: str, note: str | None = None) -> int:
    """Write the four ordinary readings and any preset context flags.

    This does not bypass the gate or the minimum-data rule: it writes fields, and the normal
    readiness compute decides whether they are sufficient.
    """
    choices = presets()
    if name not in choices:
        raise ValueError(f"unknown readiness preset {name!r}; choose {sorted(choices)}")
    preset = choices[name]
    for field in PRESET_FIELDS:
        repositories.append_readiness_entry(
            conn, on_date=on_date, field=field, value=preset["values"][field],
            source="preset", note=note or f"preset:{name}",
        )
    for flag in preset["context_flags"]:
        repositories.append_readiness_context(
            conn, on_date=on_date, flag=flag, note=note or f"preset:{name}",
        )
    return len(PRESET_FIELDS)


def record_context(conn, on_date: str, flags: list[str] | tuple[str, ...],
                   note: str | None = None) -> int:
    """Append context flags; they are displayed, not scored by default."""
    unknown = [flag for flag in flags if flag not in CONTEXT_FLAGS]
    if unknown:
        raise ValueError(f"unknown readiness context flags {unknown}")
    for flag in dict.fromkeys(flags):
        repositories.append_readiness_context(conn, on_date=on_date, flag=flag, note=note)
    return len(dict.fromkeys(flags))
