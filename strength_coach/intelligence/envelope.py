"""The canonical intelligence response envelope (contract §3).

One shape for every capability, whether the caller is a future MCP tool, the authenticated iPhone
route, or the server-side agent. The envelope is deliberately boring: a fact is either observed or
derived, it names the function that produced it, and every uncertainty is one of the words the
project already uses (gate, comparability, coverage, quality flag). There is no confidence score,
because the deterministic layer cannot justify one.

This module validates shapes and vocabularies. It never computes a training value.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from strength_coach.features.evidence import (
    COMPARABILITY,
    GATES,
    canonical_json,
)
from strength_coach.intelligence.errors import EnvelopeError

INTELLIGENCE_VERSION = "1.0.0"
SCHEMA_VERSION = "intelligence.envelope.v1"
STATUSES = ("ok", "no_data", "insufficient")
BASES = ("observed", "derived")
PRIVACY_CLASSES = ("training", "performance", "health")
SUBJECT = {"athlete": "self"}

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_EVIDENCE_ID_RE = re.compile(r"^ev:[0-9a-f]{6,64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

#: Keys every evidence item must carry, matching features.evidence.EvidenceItem.as_dict().
EVIDENCE_KEYS = (
    "evidence_id",
    "evidence_version",
    "source_fingerprint",
    "source",
    "source_ids",
    "window",
    "value",
    "n",
    "comparability",
    "gate",
)

OBSERVATION_KEYS = ("family", "text", "gate", "n", "evidence_id", "limitations")


def _date(value: object, field: str) -> dt.date:
    if not isinstance(value, str):
        raise EnvelopeError(f"{field} must be an ISO date string")
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise EnvelopeError(f"{field} must be YYYY-MM-DD") from exc


@dataclass(frozen=True)
class Period:
    start: str
    end: str
    days: int
    weeks: int | None
    timezone: str

    def as_dict(self) -> dict[str, object]:
        return {
            "start": self.start,
            "end": self.end,
            "days": self.days,
            "weeks": self.weeks,
            "timezone": self.timezone,
        }

    def validate(self) -> None:
        start = _date(self.start, "period.start")
        end = _date(self.end, "period.end")
        if start > end:
            raise EnvelopeError("period.start must not be after period.end")
        if isinstance(self.days, bool) or not isinstance(self.days, int) or self.days < 1:
            raise EnvelopeError("period.days must be a positive integer")
        if self.weeks is not None and (
            isinstance(self.weeks, bool) or not isinstance(self.weeks, int) or self.weeks < 1
        ):
            raise EnvelopeError("period.weeks must be null or a positive integer")
        if not isinstance(self.timezone, str) or not self.timezone:
            raise EnvelopeError("period.timezone must be a non-empty string")


@dataclass(frozen=True)
class FactBlock:
    """One named fact: what it is, who computed it, and how uncertain it is."""

    value: Any
    basis: str
    method: str
    unit: str | None = None
    n: int | None = None
    gate: str | None = None
    comparability: str | None = None
    evidence_ids: tuple[str, ...] = ()
    quality_flags: tuple[str, ...] = ()
    note: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "value": self.value,
            "basis": self.basis,
            "method": self.method,
            "unit": self.unit,
            "n": self.n,
            "gate": self.gate,
            "comparability": self.comparability,
            "evidence_ids": list(self.evidence_ids),
            "quality_flags": list(self.quality_flags),
            "note": self.note,
        }

    def validate(self, *, evidence_ids: set[str]) -> None:
        from strength_coach.intelligence.methods import is_registered

        if self.basis not in BASES:
            raise EnvelopeError(f"fact basis {self.basis!r} is not one of {BASES}")
        if not is_registered(self.method):
            raise EnvelopeError(f"fact names an unregistered method {self.method!r}")
        if self.unit is not None and (not isinstance(self.unit, str) or not self.unit):
            raise EnvelopeError("fact unit must be null or a non-empty string")
        if self.n is not None and (
            isinstance(self.n, bool) or not isinstance(self.n, int) or self.n < 0
        ):
            raise EnvelopeError("fact n must be null or a non-negative integer")
        if self.gate is not None and self.gate not in GATES:
            raise EnvelopeError(f"fact gate {self.gate!r} is not one of {GATES}")
        if self.comparability is not None and self.comparability not in COMPARABILITY:
            raise EnvelopeError(
                f"fact comparability {self.comparability!r} is not one of {COMPARABILITY}"
            )
        for evidence_id in self.evidence_ids:
            if evidence_id not in evidence_ids:
                raise EnvelopeError(f"fact references unknown evidence {evidence_id!r}")
        for flag in self.quality_flags:
            if not isinstance(flag, str) or not flag:
                raise EnvelopeError("fact quality flags must be non-empty strings")
        if self.note is not None and (not isinstance(self.note, str) or not self.note):
            raise EnvelopeError("fact note must be null or a non-empty string")


@dataclass(frozen=True)
class Provenance:
    services: tuple[tuple[str, str], ...]
    config_revision: str
    database_revision: int
    builder_version: str
    context_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "services": [{"module": module, "version": version} for module, version in self.services],
            "config_revision": self.config_revision,
            "database_revision": self.database_revision,
            "builder_version": self.builder_version,
            "context_hash": self.context_hash,
        }

    def validate(self) -> None:
        if not self.services:
            raise EnvelopeError("provenance.services must name at least one owning module")
        for module, version in self.services:
            if not module or not version:
                raise EnvelopeError("provenance service entries need a module and a version")
        for name, value in (
            ("config_revision", self.config_revision),
            ("builder_version", self.builder_version),
            ("context_hash", self.context_hash),
        ):
            if not isinstance(value, str) or not value:
                raise EnvelopeError(f"provenance.{name} must be a non-empty string")
        if (
            isinstance(self.database_revision, bool)
            or not isinstance(self.database_revision, int)
            or self.database_revision < 0
        ):
            raise EnvelopeError("provenance.database_revision must be a non-negative integer")


@dataclass(frozen=True)
class Privacy:
    classification: str
    excluded_fields: tuple[str, ...] = ()
    redactions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "class": self.classification,
            "excluded_fields": list(self.excluded_fields),
            "redactions": list(self.redactions),
        }

    def validate(self) -> None:
        if self.classification not in PRIVACY_CLASSES:
            raise EnvelopeError(f"privacy class {self.classification!r} is not one of {PRIVACY_CLASSES}")
        for value in (*self.excluded_fields, *self.redactions):
            if not isinstance(value, str) or not value:
                raise EnvelopeError("privacy entries must be non-empty strings")


@dataclass(frozen=True)
class Envelope:
    capability: str
    version: str
    status: str
    as_of: str
    period: Period
    units: Mapping[str, str]
    facts: Mapping[str, FactBlock]
    evidence: tuple[Mapping[str, Any], ...]
    observations: tuple[Mapping[str, Any], ...]
    coverage: Mapping[str, int | float | str | None]
    missing: tuple[str, ...]
    limitations: tuple[str, ...]
    quality_flags: tuple[str, ...]
    privacy: Privacy
    provenance: Provenance
    generated_at: str
    intelligence_version: str = INTELLIGENCE_VERSION
    schema_version: str = SCHEMA_VERSION
    subject: Mapping[str, str] = field(default_factory=lambda: dict(SUBJECT))

    def as_dict(self) -> dict[str, object]:
        return {
            "intelligence_version": self.intelligence_version,
            "schema_version": self.schema_version,
            "capability": self.capability,
            "capability_version": self.version,
            "status": self.status,
            "as_of": self.as_of,
            "period": self.period.as_dict(),
            "subject": dict(self.subject),
            "units": dict(self.units),
            "facts": {name: fact.as_dict() for name, fact in self.facts.items()},
            "evidence": [dict(item) for item in self.evidence],
            "observations": [dict(item) for item in self.observations],
            "coverage": dict(self.coverage),
            "missing": list(self.missing),
            "limitations": list(self.limitations),
            "quality_flags": list(self.quality_flags),
            "privacy": self.privacy.as_dict(),
            "provenance": self.provenance.as_dict(),
            "generated_at": self.generated_at,
        }

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())

    def validate(self) -> None:
        """Raise EnvelopeError if the envelope violates the contract."""
        if self.intelligence_version != INTELLIGENCE_VERSION:
            raise EnvelopeError("unsupported intelligence_version")
        if self.schema_version != SCHEMA_VERSION:
            raise EnvelopeError("unsupported schema_version")
        if not _NAME_RE.match(self.capability):
            raise EnvelopeError("capability must be a lower_snake_case identifier")
        if self.status not in STATUSES:
            raise EnvelopeError(f"status {self.status!r} is not one of {STATUSES}")
        _date(self.as_of, "as_of")
        self.period.validate()
        if not self.units:
            raise EnvelopeError("units must declare at least one unit")
        for name, unit in self.units.items():
            if not _NAME_RE.match(str(name)) or not isinstance(unit, str) or not unit:
                raise EnvelopeError("units must map names to non-empty strings")
        if dict(self.subject) != SUBJECT:
            raise EnvelopeError("subject is fixed to the single athlete")

        if not isinstance(self.facts, Mapping):
            raise EnvelopeError("facts must be a mapping")
        evidence_ids = self._evidence_ids()
        for name, fact in self.facts.items():
            if not _NAME_RE.match(str(name)):
                raise EnvelopeError(f"fact name {name!r} is not lower_snake_case")
            if not isinstance(fact, FactBlock):
                raise EnvelopeError(f"fact {name!r} must be a FactBlock")
            fact.validate(evidence_ids=evidence_ids)
        if self.status == "ok" and not self.facts:
            raise EnvelopeError("status ok requires at least one fact")

        if len(self.observations) > 2:
            raise EnvelopeError("at most two observations may be returned")
        for observation in self.observations:
            for key in OBSERVATION_KEYS:
                if key not in observation:
                    raise EnvelopeError(f"observation is missing {key!r}")
            if observation["evidence_id"] not in evidence_ids:
                raise EnvelopeError("observation references unknown evidence")

        for name, value in self.coverage.items():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise EnvelopeError(f"coverage.{name} must be a number, string or null")
        for name, values in (
            ("missing", self.missing),
            ("limitations", self.limitations),
            ("quality_flags", self.quality_flags),
        ):
            for value in values:
                if not isinstance(value, str) or not value:
                    raise EnvelopeError(f"{name} entries must be non-empty strings")

        self.privacy.validate()
        self.provenance.validate()
        if not isinstance(self.generated_at, str) or not _UTC_RE.match(self.generated_at):
            raise EnvelopeError("generated_at must be a UTC timestamp ending in Z")
        try:
            # Canonical JSON stringifies unknown objects; a transport needs a real JSON value,
            # so validate with the strict encoder as well.
            json.dumps(self.as_dict(), sort_keys=True, ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise EnvelopeError("envelope is not JSON serialisable") from exc

    def _evidence_ids(self) -> set[str]:
        if not isinstance(self.evidence, Sequence):
            raise EnvelopeError("evidence must be a sequence")
        ids: set[str] = set()
        for item in self.evidence:
            if not isinstance(item, Mapping):
                raise EnvelopeError("evidence items must be mappings")
            for key in EVIDENCE_KEYS:
                if key not in item:
                    raise EnvelopeError(f"evidence item is missing {key!r}")
            evidence_id = item["evidence_id"]
            if not isinstance(evidence_id, str) or not _EVIDENCE_ID_RE.match(evidence_id):
                raise EnvelopeError(f"invalid evidence id {evidence_id!r}")
            if evidence_id in ids:
                raise EnvelopeError(f"duplicate evidence id {evidence_id!r}")
            ids.add(evidence_id)
            window = item["window"]
            if not isinstance(window, Mapping):
                raise EnvelopeError("evidence window must be a mapping")
            _date(window.get("start"), "evidence.window.start")
            _date(window.get("end"), "evidence.window.end")
            if item["gate"] not in GATES:
                raise EnvelopeError(f"evidence gate {item['gate']!r} is not one of {GATES}")
            if item["comparability"] not in COMPARABILITY:
                raise EnvelopeError(
                    f"evidence comparability {item['comparability']!r} is not one of {COMPARABILITY}"
                )
        return ids
