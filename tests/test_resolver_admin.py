"""Step 5 resolver administration: policy validation, backups and preview surfaces."""

from __future__ import annotations

import pytest

from strength_coach.prescribe import resolver_admin, resolver_policy
from strength_coach.utils import paths


def _body() -> str:
    return paths.template_resolver_yaml().read_text(encoding="utf-8")


def test_policy_save_creates_backups_and_prunes_to_twenty(tmp_path) -> None:
    source = tmp_path / "policy.yaml"
    backups = tmp_path / "backups"
    source.write_text(_body(), encoding="utf-8")
    for index in range(21):
        body = _body() + f"\n# revision {index}\n"
        resolver_admin.save_policy(
            body, path=source, backups=backups, keep=20
        )
    state = resolver_admin.policy_state(source, backups)
    assert len(state["backups"]) == 20
    assert len(list(backups.glob("template-resolver-*.yaml"))) == 20


def test_invalid_policy_is_not_written_or_backed_up(tmp_path) -> None:
    source = tmp_path / "policy.yaml"
    backups = tmp_path / "backups"
    original = _body()
    source.write_text(original, encoding="utf-8")
    bad = original.replace('schema_version: "1.0.0"', 'schema_version: "9.9.9"')
    with pytest.raises(resolver_policy.ResolverPolicyError):
        resolver_admin.save_policy(bad, path=source, backups=backups)
    assert source.read_text(encoding="utf-8") == original
    assert not list(backups.glob("template-resolver-*.yaml"))


def test_restore_latest_policy_backup(tmp_path) -> None:
    source = tmp_path / "policy.yaml"
    backups = tmp_path / "backups"
    source.write_text(_body(), encoding="utf-8")
    resolver_admin.save_policy(
        _body() + "\n# first\n", path=source, backups=backups
    )
    resolver_admin.save_policy(
        _body() + "\n# second\n", path=source, backups=backups
    )
    restored = resolver_admin.restore_latest(path=source, backups=backups)
    assert "# first" in restored["yaml"]
    assert "# second" not in restored["yaml"]


def test_policy_state_includes_digest_and_backup_metadata(tmp_path) -> None:
    source = tmp_path / "policy.yaml"
    backups = tmp_path / "backups"
    source.write_text(_body(), encoding="utf-8")
    state = resolver_admin.policy_state(source, backups)
    assert state["digest"]
    assert state["schema_version"] == "1.0.0"
    assert state["path"] == str(source)
