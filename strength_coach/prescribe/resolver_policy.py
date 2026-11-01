"""Structural resolver policy (Step 1).

The policy file owns the generator's structure: candidate source, required/allowed movement
patterns, redundancy limits and top-set eligibility. Scalar tunables live in the settings
profile. Keeping them separate avoids two competing homes for the same value.

This module only loads and validates the policy. It does not generate a session; that is
Step 2. No athlete data belongs in this file.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from strength_coach.prescribe import templates
from strength_coach.utils import exercises, paths

SUPPORTED_SCHEMA_VERSIONS = ("1.0.0",)
CANDIDATE_MODES = ("reference",)
SESSION_TYPES = templates.SESSION_TYPES


class ResolverPolicyError(ValueError):
    """The resolver policy is malformed or contradicts the blueprint/taxonomy."""


@dataclass(frozen=True)
class CandidateCatalogue:
    mode: str
    path: str


@dataclass(frozen=True)
class RedundancyPolicy:
    max_per_pattern: int
    max_per_primary_muscle: int


@dataclass(frozen=True)
class TopSetPolicy:
    eligible_lifts: tuple[str, ...]
    exceptions: Mapping[str, str]


@dataclass(frozen=True)
class ResolverPolicy:
    schema_version: str
    candidate_catalogue: CandidateCatalogue
    required_patterns: Mapping[str, tuple[str, ...]]
    allowed_patterns: Mapping[str, tuple[str, ...]]
    slot_pools: Mapping[str, Mapping[str, tuple[str, ...]]]
    redundancy: RedundancyPolicy
    top_set: TopSetPolicy
    digest: str
    source_path: Path

    @property
    def source_name(self) -> str:
        return self.source_path.name

    @classmethod
    def load(cls, path: str | Path | None = None) -> ResolverPolicy:
        source = Path(path or paths.template_resolver_yaml())
        body = source.read_text(encoding="utf-8")
        return cls.from_text(body, source_path=source)

    @classmethod
    def from_text(
        cls, body: str, *, source_path: str | Path = Path("<text>")
    ) -> ResolverPolicy:
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return _parse(body, Path(source_path), digest)


def validate_text(body: str) -> ResolverPolicy:
    """Parse an edited document without requiring it to exist on disk."""
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return _parse(body, Path("<edited>"), digest)


def _parse(body: str, source_path: Path, digest: str) -> ResolverPolicy:
    raw = yaml.safe_load(body) or {}
    if not isinstance(raw, Mapping):
        raise ResolverPolicyError(f"{source_path.name}: top level must be a mapping")
    _unknown_keys(
        raw,
        {
            "schema_version",
            "candidate_catalogue",
            "required_patterns",
            "allowed_patterns",
            "slot_pools",
            "redundancy",
            "top_set",
        },
        source_path.name,
    )

    schema_version = str(raw.get("schema_version", "unversioned"))
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ResolverPolicyError(
            f"{source_path.name}: unsupported schema {schema_version!r}; "
            f"supported: {SUPPORTED_SCHEMA_VERSIONS}"
        )

    candidate = _candidate_catalogue(raw.get("candidate_catalogue"), source_path.name)
    required = _required_patterns(raw.get("required_patterns"), source_path.name)
    allowed = _allowed_patterns(raw.get("allowed_patterns"), source_path.name)
    pools = _slot_pools(raw.get("slot_pools"), source_path.name)
    redundancy = _redundancy(raw.get("redundancy"), source_path.name)
    top_set = _top_set(raw.get("top_set"), source_path.name)

    return ResolverPolicy(
        schema_version=schema_version,
        candidate_catalogue=candidate,
        required_patterns=MappingProxyType(dict(required)),
        allowed_patterns=MappingProxyType(dict(allowed)),
        slot_pools=MappingProxyType(
            {session: MappingProxyType(dict(slots)) for session, slots in pools.items()}
        ),
        redundancy=redundancy,
        top_set=top_set,
        digest=digest,
        source_path=source_path,
    )


def _candidate_catalogue(value: Any, where: str) -> CandidateCatalogue:
    body = _mapping(value, f"{where}: candidate_catalogue")
    _unknown_keys(body, {"mode", "path"}, f"{where}: candidate_catalogue")
    mode = str(body.get("mode", "reference"))
    if mode not in CANDIDATE_MODES:
        raise ResolverPolicyError(
            f"{where}: candidate_catalogue.mode must be one of {CANDIDATE_MODES}"
        )
    path_text = _non_empty_str(body.get("path"), f"{where}: candidate_catalogue.path")
    _check_catalogue_path(path_text, where)
    return CandidateCatalogue(mode=mode, path=path_text)


def _check_catalogue_path(path_text: str, where: str) -> None:
    relative = Path(path_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ResolverPolicyError(
            f"{where}: candidate_catalogue.path must be a relative path inside the repository"
        )
    root = paths.repo_root().resolve()
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root):
        raise ResolverPolicyError(
            f"{where}: candidate_catalogue.path resolves outside the repository"
        )
    if not resolved.is_file():
        raise ResolverPolicyError(
            f"{where}: candidate_catalogue.path does not exist: {path_text}"
        )


def _required_patterns(value: Any, where: str) -> dict[str, tuple[str, ...]]:
    body = _mapping(value, f"{where}: required_patterns")
    if set(body) != set(SESSION_TYPES):
        raise ResolverPolicyError(
            f"{where}: required_patterns must define exactly {SESSION_TYPES}; "
            f"got {sorted(body)}"
        )
    known = _known_patterns()
    out: dict[str, tuple[str, ...]] = {}
    for session_type in SESSION_TYPES:
        out[session_type] = _pattern_list(
            body.get(session_type), f"{where}: required_patterns.{session_type}", known
        )
    return out


def _allowed_patterns(value: Any, where: str) -> dict[str, tuple[str, ...]]:
    body = _mapping(value, f"{where}: allowed_patterns")
    slot_ids = _slot_ids()
    known = _known_patterns()
    out: dict[str, tuple[str, ...]] = {}
    for slot_id, patterns in body.items():
        slot = str(slot_id)
        if slot not in slot_ids:
            raise ResolverPolicyError(
                f"{where}: allowed_patterns has unknown slot {slot!r}"
            )
        out[slot] = _pattern_list(
            patterns, f"{where}: allowed_patterns.{slot}", known
        )
    return out


def _slot_pools(
    value: Any, where: str
) -> dict[str, dict[str, tuple[str, ...]]]:
    body = _mapping(value, f"{where}: slot_pools")
    slots_by_session = _slots_by_session()
    entities = exercises.taxonomy().entities
    out: dict[str, dict[str, tuple[str, ...]]] = {}
    for session_type, raw_slots in body.items():
        session = str(session_type)
        if session not in SESSION_TYPES:
            raise ResolverPolicyError(
                f"{where}: slot_pools has unknown session {session!r}"
            )
        slot_body = _mapping(raw_slots, f"{where}: slot_pools.{session}")
        out[session] = {}
        for slot_id, raw_ids in slot_body.items():
            slot = str(slot_id)
            if slot not in slots_by_session[session]:
                raise ResolverPolicyError(
                    f"{where}: slot_pools.{session} has unknown slot {slot!r}"
                )
            out[session][slot] = _exercise_list(
                raw_ids, f"{where}: slot_pools.{session}.{slot}", entities
            )
    return out


def _redundancy(value: Any, where: str) -> RedundancyPolicy:
    body = _mapping(value, f"{where}: redundancy")
    _unknown_keys(
        body, {"max_per_pattern", "max_per_primary_muscle"}, f"{where}: redundancy"
    )
    return RedundancyPolicy(
        max_per_pattern=_positive_int(
            body.get("max_per_pattern", 2), f"{where}: redundancy.max_per_pattern"
        ),
        max_per_primary_muscle=_positive_int(
            body.get("max_per_primary_muscle", 2),
            f"{where}: redundancy.max_per_primary_muscle",
        ),
    )


def _top_set(value: Any, where: str) -> TopSetPolicy:
    body = _mapping(value, f"{where}: top_set")
    _unknown_keys(body, {"eligible_lifts", "exceptions"}, f"{where}: top_set")
    entities = exercises.taxonomy().entities
    eligible = _exercise_list(
        body.get("eligible_lifts", ()), f"{where}: top_set.eligible_lifts", entities
    )
    exceptions_body = _mapping(body.get("exceptions", {}), f"{where}: top_set.exceptions")
    exceptions: dict[str, str] = {}
    for exercise_id, reason in exceptions_body.items():
        exercise = str(exercise_id)
        if exercise not in entities:
            raise ResolverPolicyError(
                f"{where}: top_set.exceptions has unknown exercise {exercise!r}"
            )
        exceptions[exercise] = _non_empty_str(
            reason, f"{where}: top_set.exceptions.{exercise}"
        )
    return TopSetPolicy(
        eligible_lifts=eligible,
        exceptions=MappingProxyType(dict(exceptions)),
    )


def _pattern_list(value: Any, where: str, known: set[str]) -> tuple[str, ...]:
    if value is None:
        raise ResolverPolicyError(f"{where}: expected a non-empty list")
    if not isinstance(value, (list, tuple)):
        raise ResolverPolicyError(f"{where}: expected a list")
    if not value:
        raise ResolverPolicyError(f"{where}: expected a non-empty list")
    out: list[str] = []
    for item in value:
        pattern = _non_empty_str(item, where)
        if pattern not in known:
            raise ResolverPolicyError(f"{where}: unknown taxonomy pattern {pattern!r}")
        if pattern in out:
            raise ResolverPolicyError(f"{where}: duplicate pattern {pattern!r}")
        out.append(pattern)
    return tuple(out)


def _exercise_list(
    value: Any, where: str, entities: Mapping[str, Any]
) -> tuple[str, ...]:
    if value is None:
        value = ()
    if not isinstance(value, (list, tuple)):
        raise ResolverPolicyError(f"{where}: expected a list")
    out: list[str] = []
    for item in value:
        exercise_id = _non_empty_str(item, where)
        if exercise_id not in entities:
            raise ResolverPolicyError(f"{where}: unknown exercise {exercise_id!r}")
        if exercise_id in out:
            raise ResolverPolicyError(f"{where}: duplicate exercise {exercise_id!r}")
        out.append(exercise_id)
    return tuple(out)


def _known_patterns() -> set[str]:
    return {
        str(entity["pattern"])
        for entity in exercises.taxonomy().entities.values()
        if entity.get("pattern")
    }


def _slot_ids() -> set[str]:
    out: set[str] = set()
    for session_type in SESSION_TYPES:
        out.update(slot.id for slot in templates.SessionTemplate.load(session_type).slots)
    return out


def _slots_by_session() -> dict[str, set[str]]:
    return {
        session_type: {
            slot.id for slot in templates.SessionTemplate.load(session_type).slots
        }
        for session_type in SESSION_TYPES
    }


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ResolverPolicyError(f"{where}: expected a mapping")
    return value


def _unknown_keys(body: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ResolverPolicyError(f"{where}: unknown keys {unknown}")


def _non_empty_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResolverPolicyError(f"{where}: expected a non-empty string")
    return value.strip()


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ResolverPolicyError(f"{where}: expected a positive integer")
    return value
