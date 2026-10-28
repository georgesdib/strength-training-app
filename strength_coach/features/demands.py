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
import os
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
    overlay_path: Path | None = None

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


def _read(source: Path) -> tuple[dict[str, Any], bytes]:
    if not source.is_file():
        return {}, b""
    raw_bytes = source.read_bytes()
    try:
        raw = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise DemandError(f"could not parse {source}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise DemandError(f"{source}: the catalogue must be an object")
    return dict(raw), raw_bytes


def _merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay wins per exercise/dimension; evidence entries merge by id."""
    merged: dict[str, Any] = {**base}
    merged["schema_version"] = overlay.get("schema_version") or base.get("schema_version")
    merged["reviewed_on"] = overlay.get("reviewed_on") or base.get("reviewed_on")
    merged["evidence"] = {
        **(base.get("evidence") or {}), **(overlay.get("evidence") or {})
    }
    base_exercises = base.get("exercises") or {}
    overlay_exercises = overlay.get("exercises") or {}
    merged["exercises"] = {
        exercise_id: {
            **(base_exercises.get(exercise_id) or {}),
            **(overlay_exercises.get(exercise_id) or {}),
        }
        for exercise_id in set(base_exercises) | set(overlay_exercises)
    }
    return merged


def load(path: str | Path | None = None, *,
         overlay: str | Path | None = None) -> DemandCatalogue:
    """Load the shipped catalogue merged with the local overlay.

    The overlay (`config/exercises/demands.local.yaml`) is git-ignored, so the athlete can rate
    or correct a dimension without editing the reviewed file. It wins per dimension and never
    invents evidence: `supported` still has to cite an evidence id that exists.
    """
    source = Path(path or paths.exercise_demands_yaml())
    overlay_path = Path(overlay) if overlay is not None else source.with_name(
        "demands.local.yaml"
    )
    base_raw, base_bytes = _read(source)
    overlay_raw, overlay_bytes = _read(overlay_path)
    if not base_raw and not overlay_raw:
        # A missing file is "no claims", which is the same as all-unknown. It must not crash a
        # prescription; the coverage report makes the gap visible instead.
        return DemandCatalogue({}, {}, "", "", source)
    raw = _merge(base_raw, overlay_raw)
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
    digest = hashlib.sha256(base_bytes + b"\0" + overlay_bytes).hexdigest()[:16]
    return DemandCatalogue(
        claims=claims,
        evidence=evidence,
        reviewed_on=reviewed_on,
        digest=digest,
        source_path=source,
        overlay_path=overlay_path if overlay_path.is_file() else None,
    )


def missing(exercise_ids: Iterable[str],
            dimensions: Iterable[str] = IN_SCOPE) -> dict[str, tuple[str, ...]]:
    """Dimensions with no non-unknown claim, per exercise. Empty when fully rated."""
    out: dict[str, tuple[str, ...]] = {}
    catalogue = load()
    for exercise_id in exercise_ids:
        gaps = tuple(
            dimension for dimension in dimensions
            if not catalogue.rated(str(exercise_id), dimension)
        )
        if gaps:
            out[str(exercise_id)] = gaps
    return out


def _overlay_template(base: DemandCatalogue, reviewed_on: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "reviewed_on": reviewed_on or base.reviewed_on
        or dt.date.today().isoformat(),
        "evidence": {},
        "exercises": {},
    }


def set_claim(exercise_id: str, dimension: str, level: str, *,
              confidence: str | None = None, reason: str | None = None,
              evidence: Iterable[str] = (), reviewed_on: str | None = None,
              path: str | Path | None = None,
              overlay: str | Path | None = None) -> DemandCatalogue:
    """Write one rating to the local overlay and return the merged catalogue.

    The shipped file stays untouched: the overlay is git-ignored local state, so a rating the
    athlete adds is visible to the app without looking like a reviewed claim in the repo.
    Writing 'unknown' clears a local rating while leaving the base claim intact.
    """
    if dimension not in DIMENSIONS:
        raise DemandError(f"unknown dimension {dimension!r}; choose from {DIMENSIONS}")
    if level not in LEVELS:
        raise DemandError(f"level {level!r} not one of {LEVELS}")
    if level != "unknown":
        if not str(reason or "").strip():
            raise DemandError("a rated dimension needs a reason")
        confidence = str(confidence or "provisional").strip()
        if confidence not in CONFIDENCES:
            raise DemandError(f"confidence {confidence!r} not one of {CONFIDENCES}")

    source = Path(path or paths.exercise_demands_yaml())
    overlay_path = Path(overlay) if overlay is not None else source.with_name(
        "demands.local.yaml"
    )
    base = load(source, overlay=overlay_path)
    taxonomy = exercises.taxonomy().entities
    if exercise_id not in taxonomy:
        raise DemandError(f"{exercise_id}: not a canonical exercise id")
    if taxonomy[exercise_id].get("synthetic"):
        raise DemandError(f"{exercise_id}: synthetic ids cannot be rated")
    evidence_ids = tuple(str(item) for item in evidence if str(item).strip())
    unknown_ids = sorted(set(evidence_ids) - set(base.evidence))
    if unknown_ids:
        raise DemandError(f"{exercise_id}.{dimension}: unknown evidence ids {unknown_ids}")

    raw, _old_bytes = _read(overlay_path)
    raw = raw or _overlay_template(base, reviewed_on)
    raw.setdefault("schema_version", SCHEMA_VERSION)
    raw.setdefault("reviewed_on", reviewed_on or base.reviewed_on
                   or dt.date.today().isoformat())
    raw.setdefault("evidence", {})
    raw.setdefault("exercises", {})
    claim: dict[str, Any] = {"level": level}
    if level != "unknown":
        claim["confidence"] = confidence
        claim["reason"] = str(reason).strip()
        if evidence_ids:
            claim["evidence"] = list(evidence_ids)
    raw["exercises"].setdefault(exercise_id, {})[dimension] = claim

    previous = overlay_path.read_bytes() if overlay_path.is_file() else None
    return _write_overlay(overlay_path, raw, source, previous)


def _write_overlay(overlay_path: Path, raw: Mapping[str, Any], source: Path,
                   previous: bytes | None) -> DemandCatalogue:
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = overlay_path.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    os.replace(tmp, overlay_path)
    try:
        return load(source, overlay=overlay_path)
    except Exception:
        # A rejected write must leave the previous overlay (or none) in place.
        if previous is None:
            overlay_path.unlink(missing_ok=True)
        else:
            overlay_path.write_bytes(previous)
        raise


def clear_claim(exercise_id: str, dimension: str, *,
                path: str | Path | None = None,
                overlay: str | Path | None = None) -> DemandCatalogue:
    """Remove a local override so the shipped claim (if any) applies again.

    To force a dimension to unknown even when the shipped file rates it, set the level to
    unknown instead; that writes an explicit tombstone.
    """
    source = Path(path or paths.exercise_demands_yaml())
    overlay_path = Path(overlay) if overlay is not None else source.with_name(
        "demands.local.yaml"
    )
    raw, _old = _read(overlay_path)
    if not raw:
        return load(source, overlay=overlay_path)
    exercises_raw = dict(raw.get("exercises") or {})
    entry = dict(exercises_raw.get(exercise_id) or {})
    entry.pop(dimension, None)
    if entry:
        exercises_raw[exercise_id] = entry
    else:
        exercises_raw.pop(exercise_id, None)
    raw["exercises"] = exercises_raw
    previous = overlay_path.read_bytes() if overlay_path.is_file() else None
    return _write_overlay(overlay_path, raw, source, previous)
