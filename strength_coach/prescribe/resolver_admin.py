"""Shared resolver administration: policy file editing, backups and preview helpers.

The policy remains a versioned YAML file under config/. This module is the only write path:
it validates the complete edited document, keeps the current file as a timestamped backup,
writes atomically and prunes backups to the configured retention count. Resolver settings
remain append-only profile values.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import tempfile
from pathlib import Path

from strength_coach.prescribe import resolver_policy
from strength_coach.utils import paths

BACKUP_KEEP = 20


def policy_path(path: str | Path | None = None) -> Path:
    return Path(path or paths.template_resolver_yaml())


def backup_directory(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return paths.data_dir("resolver-policy-backups")


def _backup_files(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.glob("template-resolver-*.yaml")
        if "prerestore" not in path.name
    )


def _prerestore_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("template-resolver-prerestore-*.yaml"))


def _prune(directory: Path, keep: int = BACKUP_KEEP) -> None:
    for old in _backup_files(directory)[:-keep]:
        old.unlink(missing_ok=True)
    for old in _prerestore_files(directory)[:-keep]:
        old.unlink(missing_ok=True)


def _backup(
    source: Path,
    directory: Path,
    keep: int = BACKUP_KEEP,
    *,
    prefix: str = "template-resolver",
) -> Path:
    """Create a complete backup atomically; never leave a partial final file."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = directory / f"{prefix}-{stamp}.yaml"
    body = source.read_bytes()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=directory,
            prefix=f".{prefix}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    _prune(directory, keep)
    return target


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _backup_rows(directory: Path) -> list[dict]:
    rows = []
    for path in reversed(_backup_files(directory)):
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        rows.append({
            "name": path.name,
            "path": str(path),
            "digest": digest,
            "size": path.stat().st_size,
        })
    return rows


def policy_state(path: str | Path | None = None, backups: str | Path | None = None) -> dict:
    source = policy_path(path)
    directory = backup_directory(backups)
    try:
        body = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise resolver_policy.ResolverPolicyError(
            f"resolver policy: cannot read {source}: {exc}"
        ) from exc
    policy = resolver_policy.ResolverPolicy.from_text(body, source_path=source)
    return {
        "path": str(source),
        "yaml": body,
        "digest": policy.digest,
        "schema_version": policy.schema_version,
        "candidate_catalogue": {
            "mode": policy.candidate_catalogue.mode,
            "path": policy.candidate_catalogue.path,
        },
        "backups": _backup_rows(directory),
        "pre_restore_backups": [
            {
                "name": path.name,
                "path": str(path),
                "size": path.stat().st_size,
            }
            for path in reversed(_prerestore_files(directory))
        ],
        "backup_keep": BACKUP_KEEP,
    }


def save_policy(
    body: str,
    *,
    path: str | Path | None = None,
    backups: str | Path | None = None,
    keep: int = BACKUP_KEEP,
) -> dict:
    """Validate, back up the current file, atomically replace it and prune backups."""
    source = policy_path(path)
    directory = backup_directory(backups)
    resolver_policy.validate_text(body)
    if source.exists():
        _backup(source, directory, keep)
    _atomic_write(source, body)
    _prune(directory, keep)
    return policy_state(source, directory)


def restore_latest(
    *,
    path: str | Path | None = None,
    backups: str | Path | None = None,
    keep: int = BACKUP_KEEP,
) -> dict:
    source = policy_path(path)
    directory = backup_directory(backups)
    files = _backup_files(directory)
    if not files:
        raise resolver_policy.ResolverPolicyError("no resolver policy backups exist")
    selected = files[-1]
    body = selected.read_text(encoding="utf-8")
    # Validate the selected backup before touching either the active policy or the current state.
    resolver_policy.validate_text(body)
    pre_restore = (
        _backup(
            source,
            directory,
            keep,
            prefix="template-resolver-prerestore",
        )
        if source.exists()
        else None
    )
    _atomic_write(source, body)
    _prune(directory, keep)
    state = policy_state(source, directory)
    state["restored_from"] = {
        "name": selected.name,
        "path": str(selected),
    }
    state["pre_restore_backup"] = (
        {"name": pre_restore.name, "path": str(pre_restore)}
        if pre_restore is not None else None
    )
    return state
