"""Capability registration.

A capability is one deterministic question with a typed request, a version and one handler that
returns the canonical envelope. The registry is a plain dictionary with validation, not a plugin
framework: there is no discovery, no dynamic loading and no per-request resolution beyond a name
lookup.

Two rules are enforced at registration because they are contract requirements, not runtime
accidents:

* every capability is read-only, so a name that could imply a mutation is rejected outright;
* every capability has a version, so a changed meaning requires a new version rather than a
  silent redefinition.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import Envelope
from strength_coach.intelligence.errors import IntelligenceError

#: Contract §7.4: read capabilities use get_ or compare_.
NAME_PREFIXES = ("get_", "compare_")
_NAME_RE = re.compile(r"^(get|compare)_[a-z][a-z0-9_]{1,62}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class CapabilityRequest(ABC):
    """A typed, validated capability request.

    Parsing is the only place a transport payload becomes a capability argument. A parser rejects
    unknown fields, wrong types and out-of-range values with IntelligenceError('invalid_argument')
    and names the offending field.
    """

    @classmethod
    @abstractmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> CapabilityRequest:
        raise NotImplementedError

    @abstractmethod
    def to_mapping(self) -> dict[str, object]:
        raise NotImplementedError


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    version: str
    summary: str
    request_type: type[CapabilityRequest]
    handler: Callable[[sqlite3.Connection, Any], Envelope]
    read_only: bool = True

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "summary": self.summary,
            "read_only": self.read_only,
        }


class CapabilityRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> CapabilitySpec:
        if not isinstance(spec, CapabilitySpec):
            raise TypeError("register() needs a CapabilitySpec")
        if not _NAME_RE.match(spec.name):
            raise ValueError(
                f"capability name {spec.name!r} must start with one of {NAME_PREFIXES} "
                "and be lower_snake_case"
            )
        if not _VERSION_RE.match(spec.version):
            raise ValueError(f"capability version {spec.version!r} must be MAJOR.MINOR.PATCH")
        if not spec.summary:
            raise ValueError("capability summary must not be empty")
        if not isinstance(spec.request_type, type) or not issubclass(
            spec.request_type, CapabilityRequest
        ):
            raise ValueError("capability request_type must subclass CapabilityRequest")
        if not callable(spec.handler):
            raise ValueError("capability handler must be callable")
        if spec.read_only is not True:
            raise ValueError("every intelligence capability is read-only")
        if spec.name in self._specs:
            raise ValueError(f"capability {spec.name!r} is already registered")
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str) -> CapabilitySpec:
        spec = self._specs.get(name)
        if spec is None:
            raise IntelligenceError("not_found", f"unknown capability {name!r}")
        return spec

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def describe(self) -> list[dict[str, object]]:
        return [self._specs[name].describe() for name in self.names()]


#: The process-wide registry. Capability modules register on import.
CAPABILITIES = CapabilityRegistry()


def payload_mapping(payload: object) -> Mapping[str, object]:
    """Reject anything that is not a string-keyed mapping before a parser touches it."""
    if not isinstance(payload, Mapping):
        raise IntelligenceError("invalid_argument", "arguments must be an object")
    for key in payload:
        if not isinstance(key, str):
            raise IntelligenceError("invalid_argument", "argument names must be strings")
    return payload


def reject_unknown(payload: Mapping[str, object], allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise IntelligenceError(
            "invalid_argument",
            "unknown argument(s): " + ", ".join(unknown),
            field=unknown[0],
        )


def require_int(
    value: object, field: str, *, minimum: int, maximum: int
) -> int:
    """Strict integer validation: bool is not an integer here, and ranges are inclusive."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntelligenceError(
            "invalid_argument",
            f"{field} must be an integer from {minimum} to {maximum}",
            field=field,
        )
    if not minimum <= value <= maximum:
        raise IntelligenceError(
            "invalid_argument",
            f"{field} must be an integer from {minimum} to {maximum}",
            field=field,
        )
    return value


def require_date(value: object, field: str) -> dt.date:
    if not isinstance(value, str):
        raise IntelligenceError("invalid_argument", f"{field} must be YYYY-MM-DD", field=field)
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise IntelligenceError(
            "invalid_argument", f"{field} must be YYYY-MM-DD", field=field
        ) from exc
