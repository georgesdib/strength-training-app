"""Dedicated MCP client tokens.

MCP clients are not iOS devices: conflating them would give a desktop client the phone's
credential. This module owns a small, separate credential store in the git-ignored
config/intelligence.local.yaml:

    version: 1
    clients:
      - client_id: mcp-1a2b3c4d
        label: Claude Desktop
        token_sha256: <64 hex>
        created_at: 2026-11-14T09:00:00Z
        revoked_at: null
        rotated_at: null

Only the SHA-256 digest is persisted; the plaintext token is returned once by create/rotate and
never written or logged. The file is mode 0600 and is never committed. Rotation replaces the
digest in place, so the previous token stops working immediately.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from strength_coach.intelligence.auth import IntelligenceAuthError, Principal
from strength_coach.utils import ios_credentials as credentials

LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
CLIENT_PREFIX = "mcp-"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^mcp-[0-9a-f]{8}$")
MAX_LABEL = 40
_CLIENT_FIELDS = (
    "client_id",
    "label",
    "token_sha256",
    "created_at",
    "revoked_at",
    "rotated_at",
)


class TokenStoreError(ValueError):
    """The token file is missing where it must exist, or is malformed."""


def _now_iso(now: dt.datetime | None = None) -> str:
    moment = now or dt.datetime.now(dt.UTC)
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_label(label: object) -> str:
    if not isinstance(label, str):
        raise ValueError("label must be a string")
    clean = " ".join(label.split())
    if not clean or len(clean) > MAX_LABEL:
        raise ValueError(f"label must be 1-{MAX_LABEL} characters")
    return clean


@dataclass(frozen=True)
class Client:
    client_id: str
    label: str
    token_sha256: str
    created_at: str
    revoked_at: str | None = None
    rotated_at: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def as_public(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "label": self.label,
            "created_at": self.created_at,
            "revoked_at": self.revoked_at,
            "rotated_at": self.rotated_at,
            "active": self.active,
        }


@dataclass
class TokenStore:
    path: Path
    clients: tuple[Client, ...] = ()

    @classmethod
    def load(cls, path: Path) -> TokenStore:
        """Load the store; a missing file is an empty store, not an error."""
        target = Path(path)
        if not target.exists():
            return cls(path=target)
        try:
            data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise TokenStoreError(f"invalid intelligence.local.yaml: {exc}") from exc
        return cls(path=target, clients=tuple(_parse_clients(data)))

    def save(self) -> TokenStore:
        payload = {
            "version": STORE_VERSION,
            "clients": [
                {
                    "client_id": client.client_id,
                    "label": client.label,
                    "token_sha256": client.token_sha256,
                    "created_at": client.created_at,
                    "revoked_at": client.revoked_at,
                    "rotated_at": client.rotated_at,
                }
                for client in self.clients
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
        descriptor, temporary = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".intelligence-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        os.chmod(self.path, 0o600)
        return self

    def create(self, label: object, *, now: dt.datetime | None = None) -> tuple[Client, str]:
        clean = _clean_label(label)
        existing = {client.client_id for client in self.clients}
        token = credentials.generate_token()
        client_id = CLIENT_PREFIX + secrets.token_hex(4)
        while client_id in existing:
            client_id = CLIENT_PREFIX + secrets.token_hex(4)
        client = Client(
            client_id=client_id,
            label=clean,
            token_sha256=credentials.hash_token(token),
            created_at=_now_iso(now),
        )
        self.clients = (*self.clients, client)
        self.save()
        return client, token

    def rotate(
        self, client_id: str, *, now: dt.datetime | None = None
    ) -> tuple[Client, str]:
        client = self._require(client_id)
        if not client.active:
            raise TokenStoreError(f"{client_id} is revoked; create a new client instead")
        token = credentials.generate_token()
        rotated = replace(
            client,
            token_sha256=credentials.hash_token(token),
            rotated_at=_now_iso(now),
        )
        self._replace(rotated)
        self.save()
        return rotated, token

    def revoke(self, client_id: str, *, now: dt.datetime | None = None) -> Client:
        client = self._require(client_id)
        if not client.active:
            return client
        revoked = replace(client, revoked_at=_now_iso(now))
        self._replace(revoked)
        self.save()
        return revoked

    def authenticate(self, token: object, *, now: dt.datetime | None = None) -> Principal:
        """Verify a bearer token against the current file contents.

        The store is reloaded on every call, so a CLI create/rotate/revoke takes effect on the
        next request without restarting the MCP server. Writers replace the file atomically, so a
        reader sees either the old or the new complete document, never a partial one. A file that
        cannot be parsed denies every request (fail closed) rather than falling back to stale
        credentials.
        """
        if (
            not isinstance(token, str)
            or not token
            or len(token) > credentials.TOKEN_MAX_LENGTH
        ):
            raise IntelligenceAuthError(401, "authentication required")
        matched: Client | None = None
        for client in self._current_clients():
            if credentials.verify_secret(token, client.token_sha256):
                matched = client
                break
        if matched is None:
            raise IntelligenceAuthError(401, "authentication required")
        if not matched.active:
            raise IntelligenceAuthError(403, "client revoked")
        return Principal(identity=matched.client_id, kind="mcp")

    def _current_clients(self) -> tuple[Client, ...]:
        try:
            return TokenStore.load(self.path).clients
        except TokenStoreError:
            LOGGER.warning(
                "intelligence token store is unreadable; denying authentication"
            )
            raise IntelligenceAuthError(401, "authentication required") from None

    def _require(self, client_id: str) -> Client:
        for client in self.clients:
            if client.client_id == client_id:
                return client
        raise TokenStoreError(f"unknown client {client_id}")

    def _replace(self, updated: Client) -> None:
        self.clients = tuple(
            updated if client.client_id == updated.client_id else client
            for client in self.clients
        )


def _parse_clients(data: object) -> list[Client]:
    if not isinstance(data, dict):
        raise TokenStoreError("intelligence.local.yaml must contain a mapping")
    if data.get("version") != STORE_VERSION:
        raise TokenStoreError(f"intelligence.local.yaml version must be {STORE_VERSION}")
    raw_clients = data.get("clients") or []
    if not isinstance(raw_clients, list):
        raise TokenStoreError("clients must be a list")
    clients: list[Client] = []
    seen: set[str] = set()
    for entry in raw_clients:
        if not isinstance(entry, dict):
            raise TokenStoreError("each client must be a mapping")
        unknown = sorted(set(entry) - set(_CLIENT_FIELDS))
        if unknown:
            raise TokenStoreError(f"unknown client key(s): {', '.join(unknown)}")
        client_id = entry.get("client_id")
        if not isinstance(client_id, str) or not _ID_RE.match(client_id):
            raise TokenStoreError("client_id must look like mcp-1234abcd")
        if client_id in seen:
            raise TokenStoreError(f"duplicate client_id {client_id}")
        digest = entry.get("token_sha256")
        if not isinstance(digest, str) or not HASH_RE.match(digest):
            raise TokenStoreError(f"{client_id} has an invalid token hash")
        label = entry.get("label")
        if not isinstance(label, str) or not label:
            raise TokenStoreError(f"{client_id} needs a label")
        created_at = entry.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            raise TokenStoreError(f"{client_id} needs created_at")
        seen.add(client_id)
        clients.append(
            Client(
                client_id=client_id,
                label=label,
                token_sha256=digest,
                created_at=created_at,
                revoked_at=entry.get("revoked_at"),
                rotated_at=entry.get("rotated_at"),
            )
        )
    return clients
