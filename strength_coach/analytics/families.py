"""Analytical family identity and dependency fingerprints.

Phase 1 registers **no production family**: the coordinator is exercised by tests and by an
explicit `FamilySpec` supplied by a caller. Later phases register the families they materialise.
A fingerprint is a deterministic digest over the ordered dependency versions and configuration
digests that the family reads.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

_FAMILY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class FamilySpec:
    family: str
    method_version: str
    dependencies: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _FAMILY_PATTERN.match(self.family):
            raise ValueError(f"invalid analytics family name: {self.family!r}")
        if not self.method_version:
            raise ValueError("method_version must not be empty")

    def fingerprint(self) -> str:
        payload = json.dumps(
            dict(sorted(self.dependencies.items())), separators=(",", ":"), sort_keys=True
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"deps1:{digest}"


# Phase 1 ships no production families. Tests and later phases supply their own specs.
REGISTRY: dict[str, FamilySpec] = {}


def spec_for(family: str) -> FamilySpec | None:
    return REGISTRY.get(family)
