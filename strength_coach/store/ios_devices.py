"""Per-device iOS credentials and the one-use pairing exchange.

The HTTP facade is unauthenticated everywhere else; this module is the whole credential
boundary. A pairing code is minted by the local CLI, exchanged once by the phone, and paired
with a random bearer token whose SHA-256 digest alone is stored. Revocation is local to the
server (CLI only) and works until revoked.

Validation errors carry the exact HTTP status the contract requires (400/401/410/429 for
pairing, 401/403 for authentication) so the web handler only has to serialise them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from strength_coach.store.db import transaction
from strength_coach.utils import ios_credentials as credentials

LAST_SEEN_THROTTLE_SECONDS = 60


class PairingError(Exception):
    """A rejected pairing attempt with its contract status and optional field errors."""

    def __init__(self, status: int, message: str,
                 fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.fields = fields or {}


class AuthError(Exception):
    """A missing, unknown or revoked bearer credential."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _utc_now(now: dt.datetime | None = None) -> dt.datetime:
    if now is None:
        return dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=dt.UTC)
    return now.astimezone(dt.UTC)


def _iso(at: dt.datetime) -> str:
    return at.isoformat(timespec="seconds")


def _parse_iso(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def mint_pairing_code(conn, *, ttl_seconds: int = credentials.DEFAULT_TTL_SECONDS,
                      now: dt.datetime | None = None) -> dict[str, Any]:
    """Write one code hash and return the plaintext code once.

    The plaintext exists only in this return value; it is printed by the CLI and never
    written to the database or a log.
    """
    ttl = credentials.validate_ttl(ttl_seconds)
    created = _utc_now(now)
    expires = created + dt.timedelta(seconds=ttl)
    code = credentials.generate_pairing_code()
    with transaction(conn):
        conn.execute(
            "INSERT INTO ios_pairing_code "
            "(code_hash, created_at, expires_at, attempts, used_at) "
            "VALUES (?, ?, ?, 0, NULL)",
            (credentials.hash_code(code), _iso(created), _iso(expires)),
        )
    return {
        "code": code,
        "created_at": _iso(created),
        "expires_at": _iso(expires),
        "ttl_seconds": ttl,
    }


def _charge_failed_attempt(conn, code_hash: str) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE ios_pairing_code SET attempts = attempts + 1 "
            "WHERE code_hash = ? AND attempts < ?",
            (code_hash, credentials.MAX_ATTEMPTS),
        )


def _charge_newest_active_code(conn, now_iso: str) -> None:
    """Charge an unmatched guess to the newest live code.

    The schema attributes attempts to a code row, so a wrong guess cannot name a row. Without
    this, a wrong guess would leave the five-attempt limit unenforced: an attacker could guess
    forever. The CLI normally has one live code; charging the newest one keeps the limit real
    without touching a used or expired code.
    """
    row = conn.execute(
        "SELECT code_hash FROM ios_pairing_code "
        "WHERE used_at IS NULL AND expires_at > ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (now_iso,),
    ).fetchone()
    if row is not None:
        _charge_failed_attempt(conn, row["code_hash"])


def pair(conn, *, code: object, label: object = None,
         now: dt.datetime | None = None) -> dict[str, Any]:
    """Exchange a live code for one device token, or raise PairingError.

    Validation order is the contract's: format (400), label (400), existence (401), used or
    expired (410), attempts (429). A failure against an existing row consumes an attempt.
    """
    try:
        clean_code = credentials.normalize_pairing_code(code)
    except ValueError as exc:
        raise PairingError(400, str(exc), {"code": str(exc)}) from None
    try:
        clean_label = credentials.normalize_label(label)
    except ValueError as exc:
        raise PairingError(400, str(exc), {"label": str(exc)}) from None

    created = _utc_now(now)
    now_iso = _iso(created)
    digest = credentials.hash_code(clean_code)
    row = conn.execute(
        "SELECT * FROM ios_pairing_code WHERE code_hash = ?", (digest,)
    ).fetchone()
    if row is None:
        _charge_newest_active_code(conn, now_iso)
        raise PairingError(401, "wrong pairing code")
    if not credentials.verify_secret(clean_code, row["code_hash"]):
        raise PairingError(401, "wrong pairing code")
    if row["used_at"] is not None:
        _charge_failed_attempt(conn, digest)
        raise PairingError(410, "pairing code already used")
    if row["expires_at"] <= now_iso:
        _charge_failed_attempt(conn, digest)
        raise PairingError(410, "pairing code expired")
    if int(row["attempts"]) >= credentials.MAX_ATTEMPTS:
        raise PairingError(429, "pairing attempts exhausted")

    token = credentials.generate_token()
    device_id = uuid.uuid4().hex
    with transaction(conn):
        # Marking the code used and creating the device are one unit: a concurrent second
        # exchange must either see used_at set or roll back with no device.
        marked = conn.execute(
            "UPDATE ios_pairing_code SET used_at = ? "
            "WHERE code_hash = ? AND used_at IS NULL",
            (now_iso, digest),
        )
        if marked.rowcount != 1:
            raise PairingError(410, "pairing code already used")
        conn.execute(
            "INSERT INTO ios_device "
            "(device_id, label, token_hash, created_at, last_seen_at, revoked_at) "
            "VALUES (?, ?, ?, ?, NULL, NULL)",
            (device_id, clean_label, credentials.hash_token(token), now_iso),
        )
    return {
        "device": {"device_id": device_id, "label": clean_label},
        "token": token,
        "created_at": now_iso,
    }


def authenticate(conn, token: object, *, now: dt.datetime | None = None) -> dict[str, Any]:
    """Look up a bearer token by digest and enforce revocation.

    The token is never compared or logged in plaintext: the digest is the lookup key and a
    constant-time digest comparison confirms it.
    """
    if (not isinstance(token, str) or not token
            or len(token) > credentials.TOKEN_MAX_LENGTH):
        raise AuthError(401, "authentication required")
    digest = credentials.hash_token(token)
    row = conn.execute(
        "SELECT * FROM ios_device WHERE token_hash = ?", (digest,)
    ).fetchone()
    if row is None or not credentials.verify_secret(token, row["token_hash"]):
        raise AuthError(401, "authentication required")
    if row["revoked_at"] is not None:
        raise AuthError(403, "device revoked")
    _touch_last_seen(conn, row, _utc_now(now))
    return {
        "device_id": row["device_id"],
        "label": row["label"],
        "kind": row["kind"],
        "parent_device_id": row["parent_device_id"],
        "credential_epoch": int(row["credential_epoch"]),
    }


def _touch_last_seen(conn, row, now: dt.datetime) -> None:
    """Update last_seen_at at most once per 60 seconds to keep the database quiet."""
    last = _parse_iso(row["last_seen_at"]) if row["last_seen_at"] else None
    if last is not None and (now - last).total_seconds() < LAST_SEEN_THROTTLE_SECONDS:
        return
    conn.execute(
        "UPDATE ios_device SET last_seen_at = ? WHERE device_id = ?",
        (_iso(now), row["device_id"]),
    )


def mint_watch(conn, *, parent_device_id: str, label: object = None,
               now: dt.datetime | None = None) -> dict[str, Any]:
    """Mint one watch device for a phone, replacing the parent's active watch.

    One active watch per parent is enforced by a partial unique index. The epoch is
    monotonic across revoked watches, so a delayed credential cannot roll the watch back.
    The plaintext token exists only in the return value and is never stored.
    """
    try:
        clean_label = credentials.normalize_label(label if label is not None else "Apple Watch")
    except ValueError as exc:
        raise ValueError(str(exc)) from None
    created = _utc_now(now)
    now_iso = _iso(created)
    token = credentials.generate_token()
    device_id = uuid.uuid4().hex
    with transaction(conn):
        parent = conn.execute(
            "SELECT kind, revoked_at FROM ios_device WHERE device_id = ?",
            (parent_device_id,),
        ).fetchone()
        if parent is None:
            raise ValueError("parent device not found")
        if parent["kind"] != "phone" or parent["revoked_at"] is not None:
            raise ValueError("only an active phone can mint a watch")
        active = conn.execute(
            "SELECT device_id FROM ios_device "
            "WHERE kind = 'watch' AND parent_device_id = ? AND revoked_at IS NULL",
            (parent_device_id,),
        ).fetchone()
        replaced = active["device_id"] if active is not None else None
        if replaced is not None:
            conn.execute(
                "UPDATE ios_device SET revoked_at = ? "
                "WHERE device_id = ? AND revoked_at IS NULL",
                (now_iso, replaced),
            )
        epoch_row = conn.execute(
            "SELECT COALESCE(MAX(credential_epoch), 0) + 1 AS next_epoch "
            "FROM ios_device WHERE parent_device_id = ?",
            (parent_device_id,),
        ).fetchone()
        epoch = int(epoch_row["next_epoch"])
        conn.execute(
            "INSERT INTO ios_device "
            "(device_id, label, token_hash, created_at, last_seen_at, revoked_at, "
            " kind, parent_device_id, credential_epoch) "
            "VALUES (?, ?, ?, ?, NULL, NULL, 'watch', ?, ?)",
            (device_id, clean_label, credentials.hash_token(token), now_iso,
             parent_device_id, epoch),
        )
    return {
        "device": {
            "device_id": device_id,
            "label": clean_label,
            "kind": "watch",
            "parent_device_id": parent_device_id,
            "credential_epoch": epoch,
        },
        "token": token,
        "created_at": now_iso,
        "replaced_device_id": replaced,
    }


def list_devices(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT device_id, label, kind, parent_device_id, credential_epoch, "
        "created_at, last_seen_at, revoked_at "
        "FROM ios_device ORDER BY created_at, device_id"
    ).fetchall()
    return [dict(row) for row in rows]


def revoke_device(conn, device_id: str,
                  now: dt.datetime | None = None) -> dict[str, Any] | None:
    """Set revoked_at once; revoking a phone also revokes its active child watch.

    A watch bearer token is independent of the phone token, so without the cascade a
    forgotten or replaced phone would leave its watch able to call the API forever. The
    whole revocation is one transaction; an unknown id returns None and a repeat is a
    no-op apart from repairing any legacy child watch that is still active.
    """
    target = str(device_id)
    at = _iso(_utc_now(now))
    with transaction(conn):
        row = conn.execute(
            "SELECT revoked_at, kind FROM ios_device WHERE device_id = ?", (target,)
        ).fetchone()
        if row is None:
            return None
        revoked_watch_ids: list[str] = []
        if row["kind"] == "phone":
            children = conn.execute(
                "SELECT device_id FROM ios_device "
                "WHERE kind = 'watch' AND parent_device_id = ? AND revoked_at IS NULL "
                "ORDER BY created_at, device_id",
                (target,),
            ).fetchall()
            revoked_watch_ids = [child["device_id"] for child in children]
            if revoked_watch_ids:
                conn.execute(
                    "UPDATE ios_device SET revoked_at = ? "
                    "WHERE kind = 'watch' AND parent_device_id = ? AND revoked_at IS NULL",
                    (at, target),
                )
        if row["revoked_at"] is not None:
            return {"device_id": target, "revoked_at": row["revoked_at"],
                    "already_revoked": True, "revoked_watch_ids": revoked_watch_ids}
        conn.execute(
            "UPDATE ios_device SET revoked_at = ? "
            "WHERE device_id = ? AND revoked_at IS NULL",
            (at, target),
        )
    return {"device_id": target, "revoked_at": at, "already_revoked": False,
            "revoked_watch_ids": revoked_watch_ids}
