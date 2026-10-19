"""Readiness configuration: how the daily input is derived and what moves a load.

The mechanical pipeline — sentinel mapping, numeric coercion, the duplicate-row merge — lives in
`ingest.readiness` and is documented in `docs/READINESS.md`. This module holds the parts a user
may want to change: which fields the fatigue modifier reads, at what threshold, and which merge
strategy is in force.

Only the implemented strategies are accepted. A config value that silently did nothing would be
worse than an error, because the athlete would believe they had changed the behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from strength_coach.utils import paths
from strength_coach.utils import readiness as readiness_utils

KNOWN_FIELDS = readiness_utils.READINESS_FIELDS
MERGE_STRATEGIES = ("most_complete",)
TIE_BREAKS = ("latest",)


class ReadinessConfigError(ValueError):
    """The readiness configuration is invalid or asks for something unimplemented."""


@dataclass(frozen=True)
class ReadinessConfig:
    modifier_fields: tuple[str, ...] = ("sleep", "energy")
    at_or_below: float = 2.0
    merge_strategy: str = "most_complete"
    tie_break: str = "latest"
    composite_enabled: bool = False
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
    def load(cls, path: str | Path | None = None) -> "ReadinessConfig":
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

        composite = raw.get("composite") or {}
        return cls(
            modifier_fields=fields,
            at_or_below=float(modifier.get("at_or_below", 2)),
            merge_strategy=strategy,
            tie_break=tie_break,
            composite_enabled=bool(composite.get("enabled", False)),
            source_path=source,
        )


def as_dict(config: ReadinessConfig) -> dict[str, Any]:
    return {
        "modifier_fields": list(config.modifier_fields),
        "at_or_below": config.at_or_below,
        "merge_strategy": config.merge_strategy,
        "tie_break": config.tie_break,
        "composite_enabled": config.composite_enabled,
    }
