"""Pure helpers for iOS pairing codes and bearer tokens.

The CLI mints a code, the HTTP facade consumes it and every iOS read request presents a
token. Hashing and constant-time comparison live here so they can be unit-tested without a
database and cannot be re-implemented differently in the two call sites.

Only SHA-256 hex digests are ever persisted. The plaintext code and token are returned once
and never written to the database, the application log or an error body.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

CODE_DIGITS = 8
MAX_ATTEMPTS = 5
DEFAULT_TTL_SECONDS = 300
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 3600

TOKEN_BYTES = 32
TOKEN_MAX_LENGTH = 256

DEFAULT_LABEL = "iPhone"
MAX_LABEL_LENGTH = 40


def generate_pairing_code() -> str:
    """Return an 8-digit code, zero-padded so a leading zero is still 8 digits."""
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def normalize_pairing_code(value: object) -> str:
    """Strip the cosmetic spaces/hyphens the CLI prints, then require exactly 8 digits."""
    text = "" if value is None else str(value)
    cleaned = text.replace(" ", "").replace("-", "")
    if not cleaned.isascii() or not cleaned.isdigit() or len(cleaned) != CODE_DIGITS:
        raise ValueError(f"pairing code must be {CODE_DIGITS} digits")
    return cleaned


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_code(code: str) -> str:
    """Hex digest stored in ios_pairing_code.code_hash."""
    return _sha256_hex(code)


def generate_token() -> str:
    """Return a URL-safe token carrying 32 random bytes (43 characters)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Hex digest stored in ios_device.token_hash."""
    return _sha256_hex(token)


def verify_secret(secret: str, stored_hash: str | None) -> bool:
    """Compare a submitted secret with a stored digest in constant time.

    The store looks the row up by digest; this second comparison keeps the equality check
    itself constant-time and makes the property directly testable.
    """
    if not stored_hash:
        return False
    return hmac.compare_digest(_sha256_hex(secret), stored_hash)


def normalize_label(value: object) -> str:
    """Trim a device label; omitted means "iPhone", which must stay 1-40 characters."""
    if value is None:
        return DEFAULT_LABEL
    if not isinstance(value, str):
        raise ValueError(f"label must be a string of 1-{MAX_LABEL_LENGTH} characters")
    label = value.strip()
    if not 1 <= len(label) <= MAX_LABEL_LENGTH:
        raise ValueError(f"label must be 1-{MAX_LABEL_LENGTH} characters")
    return label


def validate_ttl(seconds: object) -> int:
    """Pairing-code lifetime must stay inside the approved 60-3600 second window."""
    try:
        ttl = int(seconds)
    except (TypeError, ValueError):
        raise ValueError("ttl must be an integer number of seconds") from None
    if not MIN_TTL_SECONDS <= ttl <= MAX_TTL_SECONDS:
        raise ValueError(
            f"ttl must be between {MIN_TTL_SECONDS} and {MAX_TTL_SECONDS} seconds"
        )
    return ttl
