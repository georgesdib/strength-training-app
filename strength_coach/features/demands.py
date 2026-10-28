"""Companion demand catalogue: qualitative, per-dimension claims with provenance.

The catalogue exists so a substitution can compare two exercises on one named demand
dimension without inventing a fatigue score (docs/EXERCISE-DEMANDS.md, DEC-DEMAND-01).
Three properties are load-bearing:

* **unknown is the default.** An exercise with no claim is not low-demand; it is unrated, and
  any consumer that needs two ratings must abstain.
* **dimensions are independent and dimension-specific.** "high" on axial load and "high" on
  technical demand mean different things and are never added together.
* **claims are evidence, not code.** A value carries a reason, a confidence and (when
  supported or contested) at least one evidence entry with a citation and DOI/URL.

This module only loads and validates. It never changes a prescription.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from strength_coach.utils import exercises, paths

SCHEMA_VERSION = "1.0.0"

# In-scope dimensions have substantive values in Phase 1. The other two are allowed in the
# file but default to unknown until direct evidence exists.
DIMENSIONS: tuple[str, ...] = (
    "axial_spinal",
    "trunk_stability",
    "technical",
    "local_muscular",
    "systemic",
    "eccentric_damage",
)
IN_SCOPE: tuple[str, ...] = DIMENSIONS[:4]
LEVELS: tuple[str, ...] = ("unknown", "low", "moderate", "high")
CONFIDENCES: tuple[str, ...] = ("supported", "provisional", "contested")
STUDY_TYPES: tuple[str, ...] = (
    "systematic_review", "controlled", "biomechanical", "expert", "other",
)
_ROOT_KEYS = frozenset({"schema_version", "reviewed_on", "evidence", "exercises"})


class DemandError(ValueError):
    """The catalogue is malformed or makes a claim it cannot support."""


@dataclass(frozen=True)
class EvidenceEntry:
    evidence_id: str
    citation: str
    doi: str | None
    url: str | None
    study_type: str
    population: str | None
    outcome: str | None
    applicability: str | None
    confidence: str


@dataclass(frozen=True)
class DemandClaim:
    dimension: str
    level: str
    confidence: str | None = None
    reason: str | None = None
    evidence: tuple[str, ...] = ()

    @property
    def rated(self) -> bool:
        return self.level != "unknown"


@dataclass(frozen=True)
class DemandCatalogue:
    claims: Mapping[str, Mapping[str, DemandClaim]]
    evidence: Mapping[str, EvidenceEntry]
    reviewed_on: str
    digest: str
    source_path: Path

    def claim(self, exercise_id: str, dimension: str) -> DemandClaim | None:
        """The claim for one exercise/dimension, or None when nothing is recorded."""
        return self.claims.get(str(exercise_id), {}).get(dimension)

    def level(self, exercise_id: str, dimension: str) -> str:
        claim = self.claim(exercise_id, dimension)
        return "unknown" if claim is None else claim.level

    def rated(self, exercise_id: str, dimension: str) -> bool:
        claim = self.claim(exercise_id, dimension)
        return claim is not None and claim.rated

    def comparable(self, left: str, right: str, dimension: str) -> bool:
        """True only when both sides are rated on the same dimension."""
        return self.rated(left, dimension) and self.rated(right, dimension)

    def coverage(self, exercise_ids: Iterable[str]) -> dict[str, Any]:
        """Unknown rate per dimension over the ids that are actually reachable.

        The caller supplies the ids: features may not import prescribe, so the template and
        candidate walk lives with the caller (CLI/UI).
        """
        ids = tuple(dict.fromkeys(str(item) for item in exercise_ids))
        per_dimension: dict[str, dict[str, Any]] = {}
        for dimension in DIMENSIONS:
            rated = [item for item in ids if self.rated(item, dimension)]
            provisional = sum(
                1 for item in rated
                if (self.claim(item, dimension) or DemandClaim(dimension, "unknown")).confidence
                == "provisional"
            )
            supported = sum(
                1 for item in rated
                if (self.claim(item, dimension) or DemandClaim(dimension, "unknown")).confidence
                == "supported"
            )
            per_dimension[dimension] = {
                "rated": len(rated),
                "unknown": len(ids) - len(rated),
                "unknown_rate": round((len(ids) - len(rated)) / len(ids), 3) if ids else 1.0,
                "provisional": provisional,
                "supported": supported,
            }
        rated_exercises = [
            item for item in ids
            if any(self.rated(item, dimension) for dimension in DIMENSIONS)
        ]
        return {
            "total": len(ids),
            "rated_exercises": len(rated_exercises),
            "per_dimension": per_dimension,
            "digest": self.digest,
            "reviewed_on": self.reviewed_on,
        }


def _text(value: Any, where: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DemandError(f"{where} must be a non-empty string")
    return text


def _evidence(raw: Any) -> dict[str, EvidenceEntry]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise DemandError("evidence must be an object keyed by evidence id")
    out: dict[str, EvidenceEntry] = {}
    for evidence_id, entry in raw.items():
        key = _text(evidence_id, "evidence id")
        if not isinstance(entry, Mapping):
            raise DemandError(f"evidence {key}: must be an object")
        doi = entry.get("doi")
        url = entry.get("url")
        if not doi and not url:
            raise DemandError(f"evidence {key}: a doi or url is required")
        study_type = _text(entry.get("study_type"), f"evidence {key}.study_type")
        if study_type not in STUDY_TYPES:
            raise DemandError(
                f"evidence {key}: study_type {study_type!r} not one of {STUDY_TYPES}"
            )
        confidence = _text(
            entry.get("confidence", "provisional"), f"evidence {key}.confidence"
        )
        if confidence not in CONFIDENCES:
            raise DemandError(
                f"evidence {key}: confidence {confidence!r} not one of {CONFIDENCES}"
            )
        out[key] = EvidenceEntry(
            evidence_id=key,
            citation=_text(entry.get("citation"), f"evidence {key}.citation"),
            doi=str(doi).strip() if doi else None,
            url=str(url).strip() if url else None,
            study_type=study_type,
            population=(str(entry["population"]).strip()
                        if entry.get("population") else None),
            outcome=(str(entry["outcome"]).strip() if entry.get("outcome") else None),
            applicability=(str(entry["applicability"]).strip()
                           if entry.get("applicability") else None),
            confidence=confidence,
        )
    return out


def _claims(raw: Any, evidence: Mapping[str, EvidenceEntry],
            taxonomy: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, DemandClaim]]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise DemandError("exercises must be an object keyed by canonical exercise id")
    out: dict[str, dict[str, DemandClaim]] = {}
    for exercise_id, block in raw.items():
        key = _text(exercise_id, "exercise id")
        entity = taxonomy.get(key)
        if entity is None:
            raise DemandError(f"{key}: not a canonical exercise id")
        if entity.get("synthetic"):
            raise DemandError(f"{key}: synthetic ids cannot be rated")
        if not isinstance(block, Mapping):
            raise DemandError(f"{key}: must be an object keyed by dimension")
        claims: dict[str, DemandClaim] = {}
        for dimension, claim_raw in block.items():
            name = _text(dimension, f"{key} dimension")
            if name not in DIMENSIONS:
                raise DemandError(
                    f"{key}: unknown dimension {name!r}; choose from {DIMENSIONS}"
                )
            if not isinstance(claim_raw, Mapping):
                raise DemandError(f"{key}.{name}: must be an object")
            level = _text(claim_raw.get("level"), f"{key}.{name}.level")
            if level not in LEVELS:
                raise DemandError(f"{key}.{name}: level {level!r} not one of {LEVELS}")
            evidence_ids = tuple(str(item) for item in (claim_raw.get("evidence") or ()))
            unknown_ids = sorted(set(evidence_ids) - set(evidence))
            if unknown_ids:
                raise DemandError(f"{key}.{name}: unknown evidence ids {unknown_ids}")
            confidence = claim_raw.get("confidence")
            confidence = str(confidence).strip() if confidence else None
            if level == "unknown":
                claims[name] = DemandClaim(name, level, confidence, None, evidence_ids)
                continue
            if confidence is None:
                raise DemandError(f"{key}.{name}: a non-unknown level needs a confidence")
            if confidence not in CONFIDENCES:
                raise DemandError(
                    f"{key}.{name}: confidence {confidence!r} not one of {CONFIDENCES}"
                )
            reason = _text(claim_raw.get("reason"), f"{key}.{name}.reason")
            if confidence in {"supported", "contested"} and not evidence_ids:
                raise DemandError(
                    f"{key}.{name}: {confidence} needs at least one evidence id"
                )
            claims[name] = DemandClaim(name, level, confidence, reason, evidence_ids)
        if claims:
            out[key] = claims
    return out


def load(path: str | Path | None = None) -> DemandCatalogue:
    source = Path(path or paths.exercise_demands_yaml())
    if not source.is_file():
        # A missing file is "no claims", which is the same as all-unknown. It must not crash a
        # prescription; the coverage report makes the gap visible instead.
        return DemandCatalogue({}, {}, "", "", source)
    raw_bytes = source.read_bytes()
    try:
        raw = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DemandError(f"could not parse {source}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise DemandError("the catalogue must be an object")
    unknown_root = sorted(set(map(str, raw)) - _ROOT_KEYS)
    if unknown_root:
        # A "score" or any other aggregate is refused by design; there is no total demand.
        raise DemandError(f"unknown top-level keys {unknown_root}")
    if str(raw.get("schema_version") or "") != SCHEMA_VERSION:
        raise DemandError(
            f"schema_version must be {SCHEMA_VERSION!r}, got {raw.get('schema_version')!r}"
        )
    reviewed_on = _text(raw.get("reviewed_on"), "reviewed_on")
    try:
        dt.date.fromisoformat(reviewed_on)
    except ValueError as exc:
        raise DemandError(f"reviewed_on must be an ISO date, got {reviewed_on!r}") from exc

    taxonomy = exercises.taxonomy().entities
    evidence = _evidence(raw.get("evidence"))
    claims = _claims(raw.get("exercises"), evidence, taxonomy)
    digest = hashlib.sha256(raw_bytes).hexdigest()[:16]
    return DemandCatalogue(
        claims=claims,
        evidence=evidence,
        reviewed_on=reviewed_on,
        digest=digest,
        source_path=source,
    )
