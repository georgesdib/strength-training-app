#!/usr/bin/env python3
"""Export the complete repository tree to a tar archive.

This is a literal export, not the restorable backup in `tools/backup_app.py`. It includes
tracked files, ignored private files (`private/`, `data/`), local secret overlays, SQLite
files and `.git`, unless `--no-git` is given. It excludes only reproducible build, cache and
virtual-environment data. The resulting archive can contain health data and API keys; it is
unencrypted and is written mode 600.

Usage:
    python3 tools/export_repo.py
    python3 tools/export_repo.py /path/to/export.tar.gz
    python3 tools/export_repo.py --no-git /path/to/export.tar
"""

from __future__ import annotations

import argparse
import os
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Reproducible or machine-local outputs. Private data, logs and old SQLite copies are data,
# not build products, so they stay in the export.
EXCLUDED_DIR_NAMES = {
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".ipynb_checkpoints",
    "node_modules",
    "build",
    "dist",
    ".eggs",
    ".tox",
    ".nox",
    "htmlcov",
    ".hypothesis",
}
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".pyd")
EXCLUDED_FILE_NAMES = {".coverage", "coverage.xml"}


@dataclass(frozen=True)
class ExportStats:
    files: int
    directories: int
    excluded: int
    bytes: int


def _is_excluded(relative: Path, name: str, include_git: bool) -> bool:
    if not include_git and relative.parts and relative.parts[0] == ".git":
        return True
    if any(part in EXCLUDED_DIR_NAMES or part.endswith(".egg-info")
           for part in relative.parts):
        return True
    if name in EXCLUDED_FILE_NAMES or name.startswith(".coverage."):
        return True
    return name.endswith(EXCLUDED_SUFFIXES)


def _archive_mode(path: Path) -> str:
    name = path.name.lower()
    if name.endswith((".tar.gz", ".tgz")):
        return "w:gz"
    if name.endswith(".tar"):
        return "w"
    raise ValueError("output must end in .tar, .tar.gz or .tgz")


def export_repository(root: Path, output: Path, *, include_git: bool = True) -> ExportStats:
    """Write the complete working tree under *root* to *output*.

    Symlinks are stored as symlinks rather than followed. The archive contains a single
    top-level directory named after *root*. An output file inside *root* is skipped so the
    archive cannot include itself.
    """
    root = root.resolve()
    output = output.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"repository root is not a directory: {root}")
    if output == root:
        raise ValueError("output must be a file, not the repository directory")

    output.parent.mkdir(parents=True, exist_ok=True)
    files = 0
    directories = 0
    excluded = 0
    total_bytes = 0

    def visit(directory: Path) -> None:
        nonlocal files, directories, excluded, total_bytes
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise OSError(f"cannot read {directory}: {error}") from error

        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root)
            if path == output:
                excluded += 1
                continue
            if _is_excluded(relative, entry.name, include_git):
                excluded += 1
                continue

            arcname = str(Path(root.name) / relative)
            if entry.is_symlink():
                tar.add(path, arcname=arcname, recursive=False)
                files += 1
                total_bytes += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                tar.add(path, arcname=arcname, recursive=False)
                directories += 1
                visit(path)
            elif entry.is_file(follow_symlinks=False):
                tar.add(path, arcname=arcname, recursive=False)
                files += 1
                total_bytes += entry.stat(follow_symlinks=False).st_size
            else:
                # Sockets, FIFOs and devices are not portable repository content.
                excluded += 1

    try:
        mode = _archive_mode(output)
    except ValueError as error:
        raise ValueError(str(error)) from error

    with tarfile.open(output, mode) as tar:
        visit(root)

    os.chmod(output, 0o600)
    return ExportStats(files=files, directories=directories, excluded=excluded,
                       bytes=total_bytes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export the complete repository tree to an uncompressed or gzip tar.",
    )
    parser.add_argument(
        "output",
        nargs="?",
        help="archive path ending in .tar, .tar.gz or .tgz "
             "(default: sibling <repo>-export-YYYYmmdd-HHMMSS.tar.gz)",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="exclude .git (the default includes it)",
    )
    args = parser.parse_args(argv)

    output = (Path(args.output).expanduser() if args.output else
              ROOT.parent / f"{ROOT.name}-export-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz")
    try:
        stats = export_repository(ROOT, output, include_git=not args.no_git)
    except (OSError, ValueError) as error:
        print(f"export failed: {error}", file=sys.stderr)
        return 2

    size_mib = output.stat().st_size / (1024 * 1024)
    print(f"Archive:   {output}")
    print(f"Files:     {stats.files}")
    print(f"Dirs:      {stats.directories}")
    print(f"Source:    {stats.bytes / (1024 * 1024):.1f} MiB")
    print(f"Archive:   {size_mib:.1f} MiB")
    print(f"Excluded:  {stats.excluded} build/cache/output entries")
    print(f"Git:       {'included' if not args.no_git else 'excluded'}")
    print("Warning:   contains private data and possibly API keys; not encrypted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
