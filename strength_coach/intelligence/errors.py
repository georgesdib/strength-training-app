"""Typed capability failures.

A capability fails in three ways, and only the first two are expected:

* the caller's request is wrong (bad window, unknown identifier, impossible date);
* the request is valid but the state does not allow an answer (in-progress workout);
* the server is broken.

The first two become a :class:`IntelligenceError` with a stable code and a message that is safe
to show a model or a person. The third is never wrapped here on purpose: the execution service
catches it, logs the traceback and returns a fixed internal message, so an implementation detail
cannot leak through a capability boundary.
"""

from __future__ import annotations

CODES = (
    "invalid_argument",
    "not_found",
    "invalid_state",
    "unavailable",
    "insufficient_data",
    "internal",
)

#: The codes a capability may raise. `internal` is produced by the execution service, never
#: by a capability that wants to describe a caller error.
CAPABILITY_CODES = tuple(code for code in CODES if code != "internal")


class IntelligenceError(Exception):
    """An expected, caller-facing capability failure.

    The message must not contain a traceback, a database path, SQL, a token, or another
    implementation detail. The optional `field` names the request field that caused an
    `invalid_argument` failure so a transport can return a useful validation response.
    """

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        if code not in CODES:
            raise ValueError(f"unknown intelligence error code {code!r}")
        if not message:
            raise ValueError("an intelligence error needs a message")
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def as_public(self) -> dict[str, object]:
        payload: dict[str, object] = {"code": self.code, "message": self.message}
        if self.field is not None:
            payload["field"] = self.field
        return payload

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class EnvelopeError(Exception):
    """A capability produced an envelope that violates the contract.

    This is a programming error in the capability, not a caller error. The execution service
    converts it to an internal failure and logs it; it never reaches a client.
    """
