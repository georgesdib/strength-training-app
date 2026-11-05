"""Repository export: include private data, exclude build/cache data."""

from __future__ import annotations

import importlib.util
import stat
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("export_repo", ROOT / "tools/export_repo.py")
assert SPEC is not None and SPEC.loader is not None
export_repo = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = export_repo
SPEC.loader.exec_module(export_repo)


def _tree(root: Path) -> None:
    for relative in (
        ".git/HEAD",
        "private/EVIDENCE.md",
        "data/coach.db",
        "data/raw/training.csv",
        "data/web.log",
        "config/llm.local.toml",
        "source.py",
        ".venv/bin/python",
        "__pycache__/source.cpython-312.pyc",
        ".pytest_cache/v/cache/nodeids",
        ".ruff_cache/0.0.1",
        "node_modules/pkg/index.js",
        "build/out.txt",
        "dist/app.tar",
        "strength_coach.egg-info/PKG-INFO",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n", encoding="utf-8")


def test_export_includes_private_data_and_git_but_excludes_build_data(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _tree(root)
    output = tmp_path / "export.tar.gz"

    stats = export_repo.export_repository(root, output)

    assert stats.files >= 7
    assert stats.excluded >= 7
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with tarfile.open(output) as archive:
        names = set(archive.getnames())

    assert "repo/private/EVIDENCE.md" in names
    assert "repo/data/coach.db" in names
    assert "repo/data/raw/training.csv" in names
    assert "repo/data/web.log" in names
    assert "repo/config/llm.local.toml" in names
    assert "repo/.git/HEAD" in names
    assert "repo/source.py" in names
    for excluded in (
        "repo/.venv",
        "repo/__pycache__",
        "repo/.pytest_cache",
        "repo/.ruff_cache",
        "repo/node_modules",
        "repo/build",
        "repo/dist",
        "repo/strength_coach.egg-info",
    ):
        assert not any(name == excluded or name.startswith(excluded + "/") for name in names), excluded


def test_no_git_omits_repository_metadata(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _tree(root)
    output = tmp_path / "export.tar"

    export_repo.export_repository(root, output, include_git=False)

    with tarfile.open(output) as archive:
        names = set(archive.getnames())
    assert "repo/source.py" in names
    assert not any(name == "repo/.git" or name.startswith("repo/.git/") for name in names)


def test_output_inside_repository_is_not_archived(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _tree(root)
    output = root / "export.tar.gz"

    export_repo.export_repository(root, output)

    with tarfile.open(output) as archive:
        names = set(archive.getnames())
    assert "repo/source.py" in names
    assert "repo/export.tar.gz" not in names
