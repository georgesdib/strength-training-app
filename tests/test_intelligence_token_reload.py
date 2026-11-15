"""Token changes take effect in a running server without a restart."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from strength_coach.intelligence.auth import IntelligenceAuthError
from strength_coach.intelligence.tokens import TokenStore


@pytest.fixture()
def store(tmp_path: Path) -> TokenStore:
    return TokenStore.load(tmp_path / "intelligence.local.yaml")


def test_revocation_applies_to_a_running_store(store):
    client, token = store.create("Laptop")
    # A second handle stands in for the CLI process.
    cli = TokenStore.load(store.path)
    cli.revoke(client.client_id)
    with pytest.raises(IntelligenceAuthError) as error:
        store.authenticate(token)
    assert error.value.status == 403


def test_rotation_applies_to_a_running_store(store):
    client, token = store.create("Laptop")
    cli = TokenStore.load(store.path)
    _, new_token = cli.rotate(client.client_id)
    with pytest.raises(IntelligenceAuthError):
        store.authenticate(token)
    assert store.authenticate(new_token).identity == client.client_id


def test_a_new_client_is_accepted_without_restart(store):
    cli = TokenStore.load(store.path)
    client, token = cli.create("New laptop")
    assert store.authenticate(token).identity == client.client_id


def test_an_unreadable_store_fails_closed(store, caplog):
    _, token = store.create("Laptop")
    store.path.write_text("version: 1\nclients: not-a-list\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING), pytest.raises(IntelligenceAuthError) as error:
        store.authenticate(token)
    assert error.value.status == 401
    assert "unreadable" in caplog.text
    assert token not in caplog.text


def test_concurrent_authentication_and_rotation_stay_consistent(store):
    client, old_token = store.create("Laptop")
    rotated: list[str] = []
    observed: list[object] = []
    failures: list[BaseException] = []
    stop = threading.Event()

    def authenticate() -> None:
        while not stop.is_set():
            try:
                observed.append(store.authenticate(old_token).identity)
            except IntelligenceAuthError as exc:
                observed.append(exc.status)
            except BaseException as exc:  # noqa: BLE001 - the test asserts none occur
                failures.append(exc)

    def rotate() -> None:
        cli = TokenStore.load(store.path)
        for _ in range(15):
            _, token = cli.rotate(client.client_id)
            rotated.append(token)
            time.sleep(0.002)

    reader = threading.Thread(target=authenticate)
    writer = threading.Thread(target=rotate)
    reader.start()
    writer.start()
    writer.join(timeout=30)
    stop.set()
    reader.join(timeout=30)

    assert failures == []
    assert rotated
    assert set(observed) <= {client.client_id, 401, 403}
    # The final token is the only one that still works; the first one is dead.
    assert store.authenticate(rotated[-1]).identity == client.client_id
    with pytest.raises(IntelligenceAuthError):
        store.authenticate(old_token)
