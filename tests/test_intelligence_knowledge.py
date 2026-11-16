"""Knowledge allowlist, chunking and incremental index tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from strength_coach.intelligence.knowledge.allowlist import (
    evaluate,
    load_config,
    scan,
)
from strength_coach.intelligence.knowledge.chunker import chunk_text
from strength_coach.intelligence.knowledge.index import build, source_health, status


def _config(tmp_path: Path, root: Path, index: Path) -> Path:
    data = {
        "version": 1,
        "index_path": str(index),
        "sources": [
            {
                "name": "repo",
                "root": str(root),
                "include": [r"^docs/.*\.md$", r"^src/.*\.py$", r"^tests/.*\.py$", r"^private/.*"],
                "exclude": [r"^private/eval/"],
            }
        ],
        "deny_always": [r"\.sqlite$", r"llm\.local\.toml$"],
        "deny_test_data": [r"fixtures/"],
        "secret_content_patterns": [r"\bsk-[A-Za-z0-9_-]{16,}"],
    }
    path = tmp_path / "knowledge.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "tests" / "fixtures").mkdir(parents=True)
    (root / "private" / "eval").mkdir(parents=True)
    (root / "docs" / "readiness.md").write_text(
        "# Readiness\n\nThe score is a composite.\n", encoding="utf-8"
    )
    (root / "src" / "score.py").write_text(
        "def calculate_score():\n    return 1\n", encoding="utf-8"
    )
    (root / "tests" / "test_score.py").write_text(
        "def test_score():\n    assert True\n", encoding="utf-8"
    )
    (root / "tests" / "fixtures" / "data.json").write_text("{}", encoding="utf-8")
    (root / "private" / "personal.md").write_text("# Personal\n\nNotes.\n", encoding="utf-8")
    (root / "private" / "eval" / "labels.md").write_text("# Eval\n", encoding="utf-8")
    (root / "private" / "secret.md").write_text("sk-abcdefghijklmnopqrstuvwxyz\n", encoding="utf-8")
    return root


def test_allowlist_includes_tests_and_private_but_excludes_data(tmp_path):
    root = _repo(tmp_path)
    config = load_config(_config(tmp_path, root, tmp_path / "index.sqlite"))
    listing = scan(config)
    included = {item.relative for item in listing.included}
    excluded = {item.relative for item in listing.excluded}

    assert "tests/test_score.py" in included
    assert "private/personal.md" in included
    assert "tests/fixtures/data.json" not in included
    assert "private/eval/labels.md" in excluded
    assert evaluate(config, "repo", "../escape.md") == (False, "traversal")


def test_private_duplicate_and_test_data_configuration(tmp_path):
    root = _repo(tmp_path)
    config = load_config(_config(tmp_path, root, tmp_path / "index.sqlite"))
    assert not evaluate(config, "repo", "private/eval/labels.md")[0]
    assert not evaluate(config, "repo", "tests/fixtures/data.json")[0]


def test_chunker_preserves_headings_and_python_ranges():
    markdown = chunk_text("docs/readiness.md", "# Readiness\n\nOne.\n\n## Score\n\nTwo.\n")
    assert [chunk.heading for chunk in markdown] == ["Readiness", "Readiness / Score"]
    assert markdown[1].line_start == 5

    python = chunk_text("src/score.py", "def one():\n    return 1\n\ndef two():\n    return 2\n")
    assert [chunk.heading for chunk in python] == ["one", "two"]


def test_index_is_incremental_and_fts5_searchable(tmp_path):
    root = _repo(tmp_path)
    index = tmp_path / "knowledge.sqlite"
    config = load_config(_config(tmp_path, root, index))

    first = build(config)
    assert first.included_files == 4
    assert first.chunks >= 3
    assert index.stat().st_mode & 0o777 == 0o600
    assert status(index)["chunks"] == first.chunks
    conn = sqlite3.connect(index)
    try:
        hits = conn.execute(
            "SELECT path FROM chunks_fts WHERE chunks_fts MATCH 'composite'"
        ).fetchall()
    finally:
        conn.close()
    assert ("docs/readiness.md",) in hits

    second = build(config)
    assert second.included_files == 0
    assert second.skipped == 4

    (root / "docs" / "new.md").write_text("# New\n\nAdded.\n", encoding="utf-8")
    third = build(config)
    assert third.removed == 0

    (root / "docs" / "new.md").write_text("# New\n\nChanged.\n", encoding="utf-8")
    changed = build(config)
    assert changed.included_files == 1
    assert third.included_files == 1
    assert third.removed == 0

    (root / "docs" / "new.md").unlink()
    fourth = build(config)
    assert fourth.removed == 1


def test_secret_content_is_skipped(tmp_path):
    root = _repo(tmp_path)
    config = load_config(_config(tmp_path, root, tmp_path / "knowledge.sqlite"))
    result = build(config)
    assert result.secret_skipped == 1


def test_rejected_files_remove_previous_chunks(tmp_path):
    root = _repo(tmp_path)
    target = root / "docs" / "mutable.md"
    target.write_text("# Mutable\n\nOld safe content.\n", encoding="utf-8")
    config = load_config(_config(tmp_path, root, tmp_path / "knowledge.sqlite"))
    build(config)

    def indexed() -> bool:
        conn = sqlite3.connect(config.index_path)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE path = 'docs/mutable.md'"
            ).fetchone()[0] > 0
        finally:
            conn.close()

    assert indexed()
    target.write_text("sk-" + "a" * 24, encoding="utf-8")
    build(config)
    assert not indexed()

    # Re-index clean, then make it invalid UTF-8.
    target.write_text("# Mutable\n\nSafe again.\n", encoding="utf-8")
    build(config)
    assert indexed()
    target.write_bytes(b"# Mutable\n\n\xff\xfe\x00")
    build(config)
    assert not indexed()

    # Re-index clean, then exceed the size limit.
    target.write_text("# Mutable\n\nSafe again.\n", encoding="utf-8")
    build(config)
    assert indexed()
    target.write_text("x" * (config.max_file_bytes + 1), encoding="utf-8")
    build(config)
    assert not indexed()


def test_python_classes_are_split_into_methods():
    source = "class Runner:\n    def one(self):\n        return 1\n\n    def two(self):\n        return 2\n"
    chunks = chunk_text("src/runner.py", source)
    assert [chunk.heading for chunk in chunks] == ["Runner", "Runner.one", "Runner.two"]


def test_source_health_reports_missing_roots(tmp_path):
    config = load_config(_config(tmp_path, tmp_path / "missing", tmp_path / "index.sqlite"))
    health = source_health(config)
    assert health[0]["present"] is False
    assert health[0]["commit"] is None
