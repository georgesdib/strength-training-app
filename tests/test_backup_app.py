"""Full backups carry non-secret local config; secrets are excluded in every mode."""

from __future__ import annotations

import sqlite3
import sys
import tarfile

from tools import backup_app


def _prepare_repo(tmp_path):
    repo = tmp_path / "repo"
    config = repo / "config"
    (config / "exercises").mkdir(parents=True)
    (config / "volume.v1.yaml").write_text("base: true\n", encoding="utf-8")
    (config / "volume.local.yaml").write_text("local: true\n", encoding="utf-8")
    (config / "exercises" / "demands.local.yaml").write_text("ratings: {}\n", encoding="utf-8")
    (config / "llm.local.toml").write_text("api_key = 'secret'\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (repo / "data").mkdir()
    with sqlite3.connect(repo / "data" / "coach.db") as conn:
        conn.execute("CREATE TABLE probe (value TEXT)")
        conn.execute("INSERT INTO probe (value) VALUES ('x')")
    return repo


def _run(monkeypatch, repo, destination, *args):
    monkeypatch.setattr(backup_app, "ROOT", repo)
    monkeypatch.setattr(sys, "argv", ["backup_app.py", str(destination), *args])
    assert backup_app.main() == 0
    archives = list(destination.glob("*.tar.gz"))
    assert len(archives) == 1
    return archives[0]


def _members(archive):
    with tarfile.open(archive, "r:gz") as tar:
        return {
            name
            for name in tar.getnames()
            if not name.endswith("/")
        }


def test_full_backup_includes_non_secret_local_config_not_secrets(tmp_path, monkeypatch):
    repo = _prepare_repo(tmp_path)
    archive = _run(monkeypatch, repo, tmp_path / "backups")
    members = _members(archive)

    assert "repo/config/volume.local.yaml" in members
    assert "repo/config/exercises/demands.local.yaml" in members
    assert "repo/config/volume.v1.yaml" in members
    assert "repo/data/coach.db" in members
    assert "repo/config/llm.local.toml" not in members
    assert "repo/.env" not in members


def test_source_only_excludes_local_config_and_secrets(tmp_path, monkeypatch):
    repo = _prepare_repo(tmp_path)
    archive = _run(monkeypatch, repo, tmp_path / "backups", "--source-only")
    members = _members(archive)

    assert "repo/config/volume.v1.yaml" in members
    assert "repo/config/volume.local.yaml" not in members
    assert "repo/config/exercises/demands.local.yaml" not in members
    assert "repo/config/llm.local.toml" not in members
    assert "repo/.env" not in members
    assert "repo/data/coach.db" not in members
