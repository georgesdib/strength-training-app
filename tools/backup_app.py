#!/usr/bin/env python3
"""Create a restorable Strength Training App archive without the virtualenv or caches.

Default: source, docs, config, .git, the current SQLite database (consistent snapshot),
raw exports and private local data. Excluded: .venv, caches, build artifacts, logs and old
pre-migration database copies. The archive contains health data and possibly local API keys;
it is written mode 600, but it is not encrypted by this script.

Use --source-only for a code/docs/config backup that excludes the database, raw exports,
private files and local secret overlays.
"""

# Usage
# -----
# Full backup (source, docs, config, .git, current DB snapshot, data/raw, private/):
#   python3 tools/backup_app.py
#
# Choose the backup directory:
#   python3 tools/backup_app.py /path/to/backups
#
# Source-only backup (no database, raw exports, private data or local secrets):
#   python3 tools/backup_app.py --source-only /path/to/backups
#
# The default destination is ../<repo-name>-backups, outside the repository. The script
# writes <repo-name>-YYYYmmdd-HHMMSS.tar.gz plus a .sha256 file, both mode 600.
#
# Restore outline:
#   mkdir -p ~/restore/strength-training-app
#   tar -xzf strength-training-app-*.tar.gz -C ~/restore
#   cd ~/restore/strength-training-app
#   python3 -m venv .venv && .venv/bin/pip install -e .
#
# Full archives contain health data and possibly API keys and are NOT encrypted by this
# script. Store them encrypted and restrict access.

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_NAMES = {
    ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "node_modules", "backups", "dist", "build",
}
SKIP_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp", ".swp", ".DS_Store")


def _relative(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def _is_local_secret(name: str) -> bool:
    return (
        name == ".env"
        or name.startswith(".env.")
        or name == "llm.local.toml"
        or name.endswith(".local.yaml")
    )


def _ignore(source_only: bool):
    def ignore(directory: str, names: list[str]) -> set[str]:
        rel = _relative(Path(directory))
        skipped: set[str] = set()
        for name in names:
            path = rel / name if rel != Path(".") else Path(name)
            if name in SKIP_NAMES or name.endswith(".egg-info") or name.endswith(SKIP_SUFFIXES):
                skipped.add(name)
                continue
            if rel == Path(".") and name in {"data", "private"} and source_only:
                skipped.add(name)
                continue
            if rel == Path("config") and _is_local_secret(name):
                skipped.add(name)
                continue
            if name == ".env" or name.startswith(".env."):
                skipped.add(name)
                continue
            if rel == Path("data"):
                # The current DB is snapshotted separately; old DB/WAL files are not copied.
                if name.startswith("coach") and (".db" in name or name.endswith(".sqlite3")):
                    skipped.add(name)
                elif name.endswith(".sqlite3"):
                    skipped.add(name)
                elif source_only and name in {"raw", "export"}:
                    skipped.add(name)
            if rel == Path("private") and source_only:
                skipped.add(name)
            if rel == Path(".") and name in {"backups"}:
                skipped.add(name)
        return skipped
    return ignore


def _snapshot_database(staging: Path, source_only: bool) -> Path | None:
    source = ROOT / "data" / "coach.db"
    if source_only or not source.exists():
        return None
    destination = staging / "data" / "coach.db"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the strength-training app.")
    parser.add_argument("destination", nargs="?", help="Backup directory (default: sibling directory outside the repo)")
    parser.add_argument("--source-only", action="store_true", help="Exclude database, raw exports, private data and local secrets")
    args = parser.parse_args()

    destination = Path(args.destination).expanduser().resolve() if args.destination else ROOT.parent / f"{ROOT.name}-backups"
    try:
        destination.relative_to(ROOT)
    except ValueError:
        pass
    else:
        print(f"Refusing destination inside the repository: {destination}", file=sys.stderr)
        return 2

    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = destination / f"{ROOT.name}-{stamp}.tar.gz"
    checksum = archive.with_suffix(archive.suffix + ".sha256")

    with tempfile.TemporaryDirectory(prefix="strength-app-backup-") as temp:
        staging = Path(temp) / ROOT.name
        shutil.copytree(
            ROOT,
            staging,
            symlinks=True,
            ignore=_ignore(args.source_only),
        )
        snapshot = _snapshot_database(staging, args.source_only)
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(staging, arcname=ROOT.name)

    os.chmod(archive, 0o600)
    digest = _sha256(archive)
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    os.chmod(checksum, 0o600)

    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"Archive:  {archive}")
    print(f"Size:     {size_mb:.1f} MiB")
    print(f"SHA256:   {digest}")
    print(f"Checksum: {checksum}")
    if args.source_only:
        print("Mode:     source only (no database, raw exports, private data or local secrets)")
    else:
        print("Mode:     full (contains health data and possibly API keys; store encrypted)")
        if snapshot is None:
            print("Note:     data/coach.db was not present; database snapshot skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
