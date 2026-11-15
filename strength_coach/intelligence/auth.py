"""Bearer authentication for intelligence access.

The project already has exactly one credential system: a per-device opaque bearer token whose
SHA-256 digest is stored in the ios_device table. Intelligence reuses that system rather than
inventing a second one. The token format, digest lookup and constant-time verification are the
existing utils.ios_credentials helpers.

Why this module does not call store.ios_devices.authenticate: that function updates the
last_seen_at column on every request. An intelligence capability must be strictly read-only,
including on a connection opened in mode=ro. Authentication therefore verifies the same
credential without the bookkeeping write. The iOS facade keeps its last-seen behaviour; this
boundary does not.

There is no user, tenant or model identity here: the deployment serves one athlete, and
authorization means "a valid active device of this athlete may read intelligence". A future MCP
transport with its own client tokens is described in ADR-INT-004 and is not part of INT-1.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from strength_coach.utils import ios_credentials as credentials

DEVICE_KINDS = ("phone", "watch")
MCP_KIND = "mcp"
INTERNAL_KIND = "internal"


class IntelligenceAuthError(Exception):
    """An authentication or authorization failure, with the status a transport would use."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message

    def as_public(self) -> dict[str, object]:
        return {"status": self.status, "message": self.message}


@dataclass(frozen=True)
class Principal:
    """The authenticated caller. Never constructed from request input.

    A transport obtains a principal from authenticate_bearer; in-process server code uses
    INTERNAL_PRINCIPAL. Nothing in a capability request may set or override it.
    """

    identity: str
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in (*DEVICE_KINDS, MCP_KIND, INTERNAL_KIND):
            raise ValueError(f"unknown principal kind {self.kind!r}")
        if not isinstance(self.identity, str) or not self.identity:
            raise ValueError("a principal needs an identity")

    @property
    def is_internal(self) -> bool:
        return self.kind == INTERNAL_KIND


#: The server's own read-only identity, used by in-process callers such as the future agent.
INTERNAL_PRINCIPAL = Principal(identity="internal", kind=INTERNAL_KIND)


def parse_bearer(header: object) -> str:
    """Extract a bearer token from an Authorization header value."""
    if not isinstance(header, str):
        raise IntelligenceAuthError(401, "authentication required")
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise IntelligenceAuthError(401, "authentication required")
    token = parts[1].strip()
    if not token or len(token) > credentials.TOKEN_MAX_LENGTH:
        raise IntelligenceAuthError(401, "authentication required")
    return token


def authenticate_bearer(conn: sqlite3.Connection, header: object) -> Principal:
    """Verify an Authorization header and return the caller.

    The token is never logged and never compared in plaintext: the digest is the lookup key and
    a constant-time digest comparison confirms the match.
    """
    token = parse_bearer(header)
    digest = credentials.hash_token(token)
    row = conn.execute(
        "SELECT device_id, kind, revoked_at, token_hash FROM ios_device WHERE token_hash = ?",
        (digest,),
    ).fetchone()
    if row is None or not credentials.verify_secret(token, row["token_hash"]):
        raise IntelligenceAuthError(401, "authentication required")
    if row["revoked_at"] is not None:
        raise IntelligenceAuthError(403, "device revoked")
    return Principal(identity=str(row["device_id"]), kind=str(row["kind"]))
