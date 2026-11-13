"""One deterministic evidence envelope for coaching feedback and the future LLM layer.

Why this module exists: the existing analyses each already describe their own output
(`adherence.quality`, VBT cohort provenance, the residual gates), but there was no single
stable way to say "this claim came from these rows, over this window, at this sample size".
This module formats and hashes that envelope. It never computes a metric: every value is passed
in by the service that owns it.

The gate vocabulary is the one `features/residual.py` established: a cohort is `insufficient`,
a `signal`, or ready for `evaluation`. Gates make a claim readable; they never authorise a
change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

GATES = ("insufficient", "signal", "evaluation")
COMPARABILITY = ("comparable", "partial", "not_comparable")


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Deterministic JSON used for hashing; never for display."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )


def make_evidence_id(
    *,
    source: str,
    source_ids: Sequence[Any],
    window: Mapping[str, Any],
    value: Any,
) -> str:
    """Stable id for the same source rows, window and value.

    A changed window or a changed input row changes the id, so a stored observation cannot
    silently point at different evidence later.
    """
    digest = hashlib.sha256(
        canonical_json(
            {
                "source": source,
                # Row order is a query artefact, not part of the claim.
                "source_ids": sorted(str(identifier) for identifier in source_ids),
                "window": {
                    "start": str(window.get("start") or ""),
                    "end": str(window.get("end") or ""),
                },
                "value": value,
            }
        ).encode("utf-8")
    ).hexdigest()
    return "ev:" + digest[:24]


@dataclass(frozen=True)
class EvidenceItem:
    """One traceable claim input. Values are supplied by an owning service."""

    source: str
    source_ids: tuple[Any, ...]
    window_start: str
    window_end: str
    value: Any
    unit: str | None = None
    n: int | None = None
    comparability: str = "comparable"
    gate: str = "signal"
    quality_flags: tuple[str, ...] = ()
    method_versions: Mapping[str, str] = field(default_factory=dict)
    calibration_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.comparability not in COMPARABILITY:
            raise ValueError(f"unknown comparability {self.comparability!r}")
        if self.gate not in GATES:
            raise ValueError(f"unknown gate {self.gate!r}")
        if self.n is not None and self.n < 0:
            raise ValueError("n cannot be negative")

    @property
    def evidence_id(self) -> str:
        return make_evidence_id(
            source=self.source,
            source_ids=self.source_ids,
            window={"start": self.window_start, "end": self.window_end},
            value=self.value,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "source_ids": [str(identifier) for identifier in self.source_ids],
            "window": {"start": self.window_start, "end": self.window_end},
            "value": self.value,
            "unit": self.unit,
            "n": self.n,
            "comparability": self.comparability,
            "gate": self.gate,
            "quality_flags": list(self.quality_flags),
            "method_versions": dict(self.method_versions),
            "calibration_ids": list(self.calibration_ids),
            "limitations": list(self.limitations),
            "rule_ids": list(self.rule_ids),
            "assumption_ids": list(self.assumption_ids),
        }
