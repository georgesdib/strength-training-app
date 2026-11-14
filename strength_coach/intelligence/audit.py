"""One structured audit record per intelligence invocation.

The record is metadata only: identity, timing, sizes and outcome. It deliberately cannot carry
arguments, payloads, notes, health values or token material, because those fields do not exist in
the schema. Argument hashing is for correlation, not redaction: the hash is of the canonical JSON
arguments and is never reversible, but the record still carries no values.

Emission is best-effort. A logging failure must never change a capability result or surface a
secret, so the helper swallows logging errors after one debug line.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from strength_coach.features.evidence import canonical_json

LOGGER = logging.getLogger("strength_coach.intelligence.audit")
AUDIT_SCHEMA = "intelligence.audit.v1"


def new_request_id() -> str:
    return "int-" + uuid.uuid4().hex[:16]


def arguments_hash(arguments: Mapping[str, object] | None) -> str:
    payload = dict(arguments or {})
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:24]


def error_code(message: str) -> str:
    """Extract the stable code from a sanitised error message, never the message itself."""
    head = message.split(":", 1)[0].strip()
    return head if head.isidentifier() else "error"


@dataclass
class PendingCall:
    kind: str
    name: str
    client_id: str
    request_id: str
    start: float
    arguments: Mapping[str, object] | None
    payload: dict[str, Any] | None = None
    status: str | None = None
    result_rows: int | None = None
    response_bytes: int = 0
    failure: str | None = None

    def record(
        self,
        payload: dict[str, Any],
        *,
        status: str | None = None,
        result_rows: int | None = None,
    ) -> None:
        self.payload = payload
        self.status = status
        self.result_rows = result_rows

    def as_dict(self, outcome: str) -> dict[str, object]:
        duration_ms = round((time.perf_counter() - self.start) * 1000, 1)
        return {
            "schema": AUDIT_SCHEMA,
            "request_id": self.request_id,
            "kind": self.kind,
            "name": self.name,
            "client_id": self.client_id,
            "arguments_hash": arguments_hash(self.arguments),
            "duration_ms": duration_ms,
            "result_rows": self.result_rows,
            "response_bytes": self.response_bytes,
            "outcome": outcome,
            "status": self.status,
        }


class AuditCall:
    """Context manager that emits exactly one record, on success or failure."""

    def __init__(self, *, kind: str, name: str, client_id: str,
                 arguments: Mapping[str, object] | None) -> None:
        self._pending = PendingCall(
            kind=kind,
            name=name,
            client_id=client_id,
            request_id=new_request_id(),
            start=time.perf_counter(),
            arguments=arguments,
        )

    @property
    def request_id(self) -> str:
        return self._pending.request_id

    def record(self, payload: dict[str, Any], *, status: str | None = None,
               result_rows: int | None = None) -> None:
        self._pending.record(payload, status=status, result_rows=result_rows)

    def __enter__(self) -> AuditCall:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        pending = self._pending
        if pending.payload is not None:
            try:
                pending.response_bytes = len(
                    canonical_json(pending.payload).encode("utf-8")
                )
            except (TypeError, ValueError):
                pending.response_bytes = 0
        if exc is not None:
            outcome = error_code(str(exc))
        elif pending.payload is None:
            outcome = "internal"
        else:
            outcome = "ok"
        try:
            LOGGER.info("%s", canonical_json(pending.as_dict(outcome)))
        except Exception:  # pragma: no cover - logging must never break a call
            LOGGER.debug("intelligence audit record could not be emitted")
        return False


def audit_call(*, kind: str, name: str, client_id: str,
               arguments: Mapping[str, object] | None) -> AuditCall:
    return AuditCall(kind=kind, name=name, client_id=client_id, arguments=arguments)
