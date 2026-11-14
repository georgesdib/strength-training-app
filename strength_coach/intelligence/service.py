"""Capability execution: validate, run inside a read snapshot, validate the result.

The service is the only place that knows how a request becomes an envelope. It knows nothing about
HTTP, MCP, models or the web UI, so a transport adapter is a thin mapping over execute() and the
capability layer can be tested with a plain connection.

Failure policy:

* expected failures are IntelligenceError values and are returned as a typed result;
* a capability that raises anything else, or returns an envelope that violates the contract, is a
  programming error: the traceback is logged and the caller gets a fixed internal message. No
  internal detail crosses the boundary.

Read-only policy: each execution runs inside a deferred read transaction that is rolled back, never
committed. A capability that accidentally writes therefore changes nothing, and the no-mutation
tests can assert it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import logging
import sqlite3
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

import strength_coach
from strength_coach.features.evidence import canonical_json
from strength_coach.intelligence import context as context_mod
from strength_coach.intelligence.auth import Principal
from strength_coach.intelligence.config import IntelligenceConfig, load_config
from strength_coach.intelligence.envelope import Envelope, Provenance
from strength_coach.intelligence.errors import EnvelopeError, IntelligenceError
from strength_coach.intelligence.registry import CAPABILITIES, CapabilityRegistry

LOGGER = logging.getLogger(__name__)

INTERNAL_FAILURE = "intelligence capability failed"


class Clock:
    """The two time facts a capability may use, injectable for deterministic tests."""

    def today(self) -> dt.date:
        return dt.date.today()

    def now_utc(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC)


SYSTEM_CLOCK = Clock()


def format_utc(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_timezone_name() -> str:
    """The server's local zone name.

    The authoritative training date is the server's local calendar date. A stored IANA profile
    timezone is part of the auth/per-user backlog (ROADMAP §4.19), so the envelope reports the
    platform's current zone name rather than inventing one.
    """
    return dt.datetime.now().astimezone().tzname() or "local"


@contextlib.contextmanager
def read_snapshot(conn: sqlite3.Connection) -> Iterator[None]:
    """Run reads inside one consistent snapshot and discard anything that writes.

    A caller that already opened a transaction owns it and is left alone. Otherwise a deferred
    BEGIN is used (never BEGIN IMMEDIATE: this must not take a write lock) and rolled back at the
    end, which releases the read lock and makes an accidental write inert.
    """
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN")
    try:
        yield
    finally:
        conn.rollback()


@dataclass(frozen=True)
class ExecutionContext:
    config: IntelligenceConfig
    stamp: context_mod.ContextStamp
    generated_at: str
    timezone: str

    def provenance(
        self,
        *,
        capability: str,
        version: str,
        arguments: Mapping[str, object],
        modules: Sequence[str],
    ) -> Provenance:
        return Provenance(
            services=tuple((module, strength_coach.__version__) for module in modules),
            config_revision=self.stamp.config_revision,
            database_revision=self.stamp.database_revision,
            builder_version=self.stamp.builder_version,
            context_hash=self.stamp.context_hash(
                capability=capability, version=version, arguments=arguments
            ),
        )


def execution_context(
    conn: sqlite3.Connection,
    config: IntelligenceConfig,
    *,
    clock: Clock | None = None,
) -> ExecutionContext:
    """Build the context identity for one read, inside the caller's snapshot."""
    source = clock if clock is not None else SYSTEM_CLOCK
    return ExecutionContext(
        config=config,
        stamp=context_mod.stamp(conn, config.as_mapping()),
        generated_at=format_utc(source.now_utc()),
        timezone=local_timezone_name(),
    )


@dataclass(frozen=True)
class CapabilityResult:
    envelope: Envelope | None = None
    error: IntelligenceError | None = None

    def __post_init__(self) -> None:
        if (self.envelope is None) == (self.error is None):
            raise ValueError("a capability result is either a success or a failure")

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, envelope: Envelope) -> CapabilityResult:
        return cls(envelope=envelope)

    @classmethod
    def failure(cls, error: IntelligenceError) -> CapabilityResult:
        return cls(error=error)

    def as_public(self) -> dict[str, object]:
        if self.envelope is not None:
            return {"ok": True, "envelope": self.envelope.as_dict()}
        assert self.error is not None
        return {"ok": False, "error": self.error.as_public()}


def _arguments_hash(arguments: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(dict(arguments)).encode("utf-8")).hexdigest()[:12]


class IntelligenceService:
    """Execute deterministic capabilities against one read-only database connection."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        config: IntelligenceConfig | None = None,
        clock: Clock | None = None,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        self._conn = conn
        self._config = config if config is not None else load_config()
        self._clock = clock if clock is not None else SYSTEM_CLOCK
        self._registry = registry if registry is not None else CAPABILITIES

    @property
    def config(self) -> IntelligenceConfig:
        return self._config

    def describe(self) -> list[dict[str, object]]:
        return self._registry.describe()

    def execute(
        self, principal: Principal, name: str, payload: object
    ) -> CapabilityResult:
        if not isinstance(principal, Principal):
            raise TypeError("execute() needs an authenticated Principal")

        if not self._config.enabled:
            return self._log(
                name,
                principal,
                None,
                0.0,
                CapabilityResult.failure(
                    IntelligenceError(
                        "unavailable", "intelligence capabilities are disabled"
                    )
                ),
            )

        started = time.perf_counter()
        try:
            spec = self._registry.get(name)
            request = spec.request_type.parse(
                payload, config=self._config, today=self._clock.today()
            )
            arguments = request.to_mapping()
        except IntelligenceError as exc:
            return self._log(name, principal, None, started, CapabilityResult.failure(exc))
        except Exception:
            LOGGER.exception("intelligence capability %s failed to prepare", name)
            return self._log(
                name,
                principal,
                None,
                started,
                CapabilityResult.failure(IntelligenceError("internal", INTERNAL_FAILURE)),
            )

        try:
            with read_snapshot(self._conn):
                execution = execution_context(
                    self._conn, self._config, clock=self._clock
                )
                envelope = spec.handler(self._conn, request, execution)
                envelope.validate()
        except IntelligenceError as exc:
            return self._log(name, principal, arguments, started, CapabilityResult.failure(exc))
        except EnvelopeError:
            LOGGER.exception(
                "intelligence capability %s returned an invalid envelope", name
            )
            return self._log(
                name,
                principal,
                arguments,
                started,
                CapabilityResult.failure(IntelligenceError("internal", INTERNAL_FAILURE)),
            )
        except Exception:
            LOGGER.exception("intelligence capability %s raised", name)
            return self._log(
                name,
                principal,
                arguments,
                started,
                CapabilityResult.failure(IntelligenceError("internal", INTERNAL_FAILURE)),
            )

        return self._log(
            name, principal, arguments, started, CapabilityResult.success(envelope)
        )

    def _log(
        self,
        name: str,
        principal: Principal,
        arguments: Mapping[str, object] | None,
        started: float,
        result: CapabilityResult,
    ) -> CapabilityResult:
        duration_ms = (time.perf_counter() - started) * 1000
        outcome = "ok" if result.ok else (result.error.code if result.error else "internal")
        LOGGER.info(
            "intelligence capability=%s outcome=%s duration_ms=%.1f principal=%s args=%s",
            name,
            outcome,
            duration_ms,
            principal.kind,
            _arguments_hash(arguments) if arguments is not None else "-",
        )
        return result
