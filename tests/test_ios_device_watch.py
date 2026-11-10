"""Phase 6.1: watch device minting, epoch rotation and per-device access."""

# The shared HTTP fixture is intentionally imported from test_ios_api.
# ruff: noqa: F401, F811

from __future__ import annotations

import pytest
from test_ios_api import _one, _paired, _request, ios  # noqa: F401

from strength_coach import ios_config
from strength_coach.store import db, ios_devices


def _phone(conn, device_id="phone-1"):
    conn.execute(
        "INSERT INTO ios_device (device_id, label, token_hash, created_at) "
        "VALUES (?, 'iPhone', ?, '2026-01-02T09:00:00+00:00')",
        (device_id, "hash-" + device_id),
    )
    conn.commit()


def _enabled(monkeypatch):
    monkeypatch.setattr(
        "strength_coach.web.server.ios_config.load_config",
        lambda: ios_config.IOSConfig(
            mutations_enabled=True,
            issued_plan_ttl_seconds=14400,
            receipt_retention_days=30,
            watch_enabled=True,
        ),
    )


def test_mint_watch_rotates_epoch_and_revokes_previous(tmp_path):
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn)
        _phone(conn)
        first = ios_devices.mint_watch(conn, parent_device_id="phone-1", label="Watch")
        assert first["device"]["kind"] == "watch"
        assert first["device"]["parent_device_id"] == "phone-1"
        assert first["device"]["credential_epoch"] == 1
        assert first["replaced_device_id"] is None
        assert ios_devices.authenticate(conn, first["token"])["kind"] == "watch"

        second = ios_devices.mint_watch(conn, parent_device_id="phone-1")
        assert second["device"]["credential_epoch"] == 2
        assert second["replaced_device_id"] == first["device"]["device_id"]
        first_row = _one(tmp_path / "coach.db", "SELECT revoked_at FROM ios_device WHERE device_id = ?", (first["device"]["device_id"],))
        assert first_row["revoked_at"] is not None
        with pytest.raises(ios_devices.AuthError):
            ios_devices.authenticate(conn, first["token"])
    finally:
        conn.close()


def test_only_a_phone_can_mint_and_only_one_active_watch(tmp_path):
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn)
        _phone(conn)
        watch = ios_devices.mint_watch(conn, parent_device_id="phone-1")
        with pytest.raises(ValueError, match="only an active phone"):
            ios_devices.mint_watch(conn, parent_device_id=watch["device"]["device_id"])
        rows = conn.execute(
            "SELECT device_id FROM ios_device WHERE kind = 'watch' AND revoked_at IS NULL"
        ).fetchall()
        assert [row["device_id"] for row in rows] == [watch["device"]["device_id"]]
    finally:
        conn.close()


def test_minting_is_disabled_by_default(ios):
    token, _ = _paired(ios)
    status, body = _request(
        ios["base"], "/api/ios/v1/devices/watch", method="POST", payload={"label": "Watch"},
        token=token,
    )
    assert status == 503


def test_phone_mints_lists_and_revokes_a_watch(ios, monkeypatch):
    _enabled(monkeypatch)
    token, _ = _paired(ios)
    status, body = _request(
        ios["base"], "/api/ios/v1/devices/watch", method="POST", payload={"label": "Watch"},
        token=token,
    )
    assert status == 201, body
    watch_token = body["token"]
    watch_id = body["device"]["device_id"]
    assert body["device"]["credential_epoch"] == 1
    assert body["replaced_device_id"] is None

    status, devices = _request(ios["base"], "/api/ios/v1/devices", token=token)
    assert status == 200
    kinds = {d["device_id"]: d["kind"] for d in devices["devices"]}
    assert kinds[watch_id] == "watch"
    assert all("token_hash" not in d for d in devices["devices"])

    status, own = _request(ios["base"], "/api/ios/v1/devices", token=watch_token)
    assert status == 200
    assert [d["device_id"] for d in own["devices"]] == [watch_id]

    status, forbidden = _request(
        ios["base"], f"/api/ios/v1/devices/{watch_id}", method="DELETE", token=watch_token,
    )
    assert status == 200

    status, revoked = _request(
        ios["base"], "/api/ios/v1/devices", token=watch_token,
    )
    assert status == 403


def test_a_watch_cannot_mint_or_revoke_the_phone(ios, monkeypatch):
    _enabled(monkeypatch)
    token, _ = _paired(ios)
    _, minted = _request(
        ios["base"], "/api/ios/v1/devices/watch", method="POST", payload={"label": "Watch"},
        token=token,
    )
    watch_token = minted["token"]
    status, _ = _request(
        ios["base"], "/api/ios/v1/devices/watch", method="POST", payload={"label": "Another"},
        token=watch_token,
    )
    assert status == 403
    status, _ = _request(
        ios["base"], "/api/ios/v1/devices/" + _one(
            ios["path"], "SELECT device_id FROM ios_device WHERE kind = 'phone'"
        )["device_id"],
        method="DELETE", token=watch_token,
    )
    assert status == 403
