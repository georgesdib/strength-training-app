"""Dedicated MCP client tokens: provision, authenticate, rotate, revoke."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from strength_coach import cli
from strength_coach.intelligence.auth import IntelligenceAuthError
from strength_coach.intelligence.config import local_config_path
from strength_coach.intelligence.mcp.run import serve
from strength_coach.intelligence.tokens import TokenStore, TokenStoreError


@pytest.fixture()
def store(tmp_path: Path) -> TokenStore:
    return TokenStore.load(tmp_path / "intelligence.local.yaml")


def test_create_returns_the_token_once_and_persists_only_a_hash(store):
    client, token = store.create("Claude Desktop")
    assert client.client_id.startswith("mcp-")
    assert client.label == "Claude Desktop"
    text = store.path.read_text(encoding="utf-8")
    assert token not in text
    assert client.token_sha256 in text
    assert "token_sha256" in text
    assert "token:" not in text
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_authenticate_accepts_the_token_and_returns_a_mcp_principal(store):
    client, token = store.create("Laptop")
    principal = store.authenticate(token)
    assert principal.identity == client.client_id
    assert principal.kind == "mcp"


@pytest.mark.parametrize("token", [None, "", "wrong", 42])
def test_authenticate_rejects_invalid_tokens(store, token):
    store.create("Laptop")
    with pytest.raises(IntelligenceAuthError) as error:
        store.authenticate(token)
    assert error.value.status == 401


def test_revoked_client_is_forbidden(store):
    client, token = store.create("Laptop")
    store.revoke(client.client_id)
    with pytest.raises(IntelligenceAuthError) as error:
        store.authenticate(token)
    assert error.value.status == 403


def test_rotation_invalidates_the_previous_token(store):
    client, first = store.create("Laptop")
    rotated, second = store.rotate(client.client_id)
    assert rotated.client_id == client.client_id
    assert rotated.rotated_at is not None
    with pytest.raises(IntelligenceAuthError):
        store.authenticate(first)
    assert store.authenticate(second).identity == client.client_id


def test_rotating_a_revoked_client_is_rejected(store):
    client, _ = store.create("Laptop")
    store.revoke(client.client_id)
    with pytest.raises(TokenStoreError):
        store.rotate(client.client_id)


def test_revoke_is_idempotent(store):
    client, token = store.create("Laptop")
    first = store.revoke(client.client_id)
    second = store.revoke(client.client_id)
    assert first.revoked_at == second.revoked_at
    with pytest.raises(IntelligenceAuthError):
        store.authenticate(token)


def test_unknown_client_is_rejected(store):
    with pytest.raises(TokenStoreError, match="unknown client"):
        store.revoke("mcp-deadbeef")


def test_public_view_never_exposes_the_hash(store):
    client, _ = store.create("Laptop")
    public = client.as_public()
    assert "token_sha256" not in public
    assert public["active"] is True


def test_store_reloads_from_disk(store):
    client, token = store.create("Laptop")
    reloaded = TokenStore.load(store.path)
    assert reloaded.authenticate(token).identity == client.client_id


def test_malformed_store_is_reported(tmp_path: Path):
    path = tmp_path / "intelligence.local.yaml"
    path.write_text("version: 1\nclients:\n  - client_id: nope\n", encoding="utf-8")
    with pytest.raises(TokenStoreError):
        TokenStore.load(path)


def test_missing_store_is_empty_not_an_error(tmp_path: Path):
    empty = TokenStore.load(tmp_path / "absent.yaml")
    assert empty.clients == ()
    with pytest.raises(IntelligenceAuthError):
        empty.authenticate("anything")


def test_file_permissions_are_restricted_on_rewrite(store):
    client, _ = store.create("Laptop")
    store.rotate(client.client_id)
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_cli_token_lifecycle(tmp_path: Path, capsys):
    path = str(tmp_path / "intelligence.local.yaml")
    assert cli.main(["intelligence", "token", "create", "--label", "Phone", "--tokens", path]) == 0
    created = capsys.readouterr().out
    assert "token:" in created
    token = created.split("token:")[1].splitlines()[0].strip()

    assert cli.main(["intelligence", "token", "list", "--tokens", path]) == 0
    listed = capsys.readouterr().out
    assert "active" in listed and "Phone" in listed
    assert token not in listed

    client_id = listed.splitlines()[1].split()[0]
    assert cli.main(["intelligence", "token", "rotate", client_id, "--tokens", path]) == 0
    rotated = capsys.readouterr().out
    new_token = rotated.split("token:")[1].splitlines()[0].strip()
    assert new_token != token

    assert cli.main(["intelligence", "token", "revoke", client_id, "--tokens", path]) == 0
    assert "revoked" in capsys.readouterr().out
    with pytest.raises(IntelligenceAuthError) as error:
        TokenStore.load(Path(path)).authenticate(new_token)
    assert error.value.status == 403
    with pytest.raises(IntelligenceAuthError):
        TokenStore.load(Path(path)).authenticate(token)


def test_serve_refuses_when_disabled(tmp_path: Path, capsys):
    config = tmp_path / "intelligence.v1.yaml"
    config.write_text("version: 1\nenabled: false\n", encoding="utf-8")
    assert serve(config_path=config) == 2
    assert "disabled" in capsys.readouterr().err


def test_serve_refuses_without_a_database(tmp_path: Path, capsys):
    config = tmp_path / "intelligence.v1.yaml"
    config.write_text("version: 1\nenabled: true\n", encoding="utf-8")
    assert serve(config_path=config, db_path=tmp_path / "absent.db") == 2
    assert "database not found" in capsys.readouterr().err


def test_serve_refuses_without_active_tokens(tmp_path: Path, capsys):
    config = tmp_path / "intelligence.v1.yaml"
    config.write_text("version: 1\nenabled: true\n", encoding="utf-8")
    database = tmp_path / "coach.db"
    from strength_coach.store import db

    store = db.Store(database)
    store.close()
    assert serve(config_path=config, db_path=database,
                 tokens_path=tmp_path / "absent.yaml") == 2
    assert "no active MCP client tokens" in capsys.readouterr().err


def test_local_token_path_is_the_git_ignored_file():
    assert str(local_config_path()).endswith("config/intelligence.local.yaml")
    assert not os.path.exists(local_config_path()) or os.stat(local_config_path()).st_mode
