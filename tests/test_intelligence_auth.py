"""Intelligence bearer authentication: success, failure, revocation and read-only behaviour."""

from __future__ import annotations

import logging

import pytest

from strength_coach.intelligence.auth import (
    INTERNAL_PRINCIPAL,
    IntelligenceAuthError,
    Principal,
    authenticate_bearer,
    parse_bearer,
)
from strength_coach.store import db, ios_devices


@pytest.fixture()
def paired():
    store = db.Store(":memory:")
    code = ios_devices.mint_pairing_code(store.connection)["code"]
    paired_device = ios_devices.pair(store.connection, code=code, label="iPhone")
    try:
        yield store.connection, paired_device
    finally:
        store.close()


def test_valid_token_returns_the_device_principal(paired):
    conn, device = paired
    principal = authenticate_bearer(conn, f"Bearer {device['token']}")
    assert principal.identity == device["device"]["device_id"]
    assert principal.kind == "phone"
    assert principal.is_internal is False


def test_scheme_is_case_insensitive(paired):
    conn, device = paired
    principal = authenticate_bearer(conn, f"bearer {device['token']}")
    assert principal.identity == device["device"]["device_id"]


@pytest.mark.parametrize(
    "header",
    [None, "", "Basic abc", "Bearer", "Bearer   ", "Token abc", 42],
)
def test_missing_or_malformed_headers_are_rejected(paired, header):
    conn, _ = paired
    with pytest.raises(IntelligenceAuthError) as error:
        authenticate_bearer(conn, header)
    assert error.value.status == 401


def test_unknown_token_is_rejected(paired):
    conn, _ = paired
    with pytest.raises(IntelligenceAuthError) as error:
        authenticate_bearer(conn, "Bearer " + "x" * 43)
    assert error.value.status == 401


def test_overlong_token_is_rejected(paired):
    conn, _ = paired
    with pytest.raises(IntelligenceAuthError) as error:
        authenticate_bearer(conn, "Bearer " + "x" * 500)
    assert error.value.status == 401


def test_revoked_device_is_forbidden(paired):
    conn, device = paired
    ios_devices.revoke_device(conn, device["device"]["device_id"])
    with pytest.raises(IntelligenceAuthError) as error:
        authenticate_bearer(conn, f"Bearer {device['token']}")
    assert error.value.status == 403
    assert error.value.message == "device revoked"


def test_authentication_does_not_touch_last_seen(paired):
    conn, device = paired
    before = conn.execute(
        "SELECT last_seen_at FROM ios_device WHERE device_id = ?",
        (device["device"]["device_id"],),
    ).fetchone()["last_seen_at"]
    changes_before = conn.total_changes
    authenticate_bearer(conn, f"Bearer {device['token']}")
    after = conn.execute(
        "SELECT last_seen_at FROM ios_device WHERE device_id = ?",
        (device["device"]["device_id"],),
    ).fetchone()["last_seen_at"]
    assert after == before
    assert conn.total_changes == changes_before, "authentication must not write"


def test_token_is_never_logged(paired, caplog):
    conn, device = paired
    with caplog.at_level(logging.INFO):
        authenticate_bearer(conn, f"Bearer {device['token']}")
    assert device["token"] not in caplog.text


def test_watch_tokens_authenticate(paired):
    conn, device = paired
    conn.execute(
        "UPDATE ios_device SET kind = 'watch' WHERE device_id = ?",
        (device["device"]["device_id"],),
    )
    principal = authenticate_bearer(conn, f"Bearer {device['token']}")
    assert principal.kind == "watch"


def test_principal_rejects_an_unknown_kind():
    with pytest.raises(ValueError):
        Principal(identity="x", kind="admin")


def test_principal_requires_an_identity():
    with pytest.raises(ValueError):
        Principal(identity="", kind="phone")


def test_internal_principal_is_marked_internal():
    assert INTERNAL_PRINCIPAL.is_internal is True
    assert INTERNAL_PRINCIPAL.identity == "internal"


def test_parse_bearer_returns_the_raw_token():
    assert parse_bearer("Bearer abc123") == "abc123"
