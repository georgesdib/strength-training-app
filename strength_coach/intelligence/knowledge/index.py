"""Incremental SQLite FTS5 index for Explain the System."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from strength_coach.intelligence.knowledge.allowlist import (
    KnowledgeConfig,
    contains_secret,
    scan,
)
from strength_coach.intelligence.knowledge.chunker import chunk_text
from strength_coach.intelligence.knowledge.sources import git_state


@dataclass(frozen=True)
class BuildStats:
    included_files: int
    chunks: int
    skipped: int
    removed: int
    secret_skipped: int
    unreadable: int
    excluded: int
    index_path: Path
    dry_run: bool = False


SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    repo_commit TEXT NOT NULL,
    dirty INTEGER NOT NULL,
    indexed_at TEXT NOT NULL,
    PRIMARY KEY (source, path)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    heading TEXT NOT NULL,
    text TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    repo_commit TEXT NOT NULL,
    dirty INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_file ON chunks(source, path);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED, path, heading, text, tokenize='unicode61'
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _chunk_id(source: str, path: str, start: int, end: int, text: str) -> str:
    material = f"{source}\0{path}\0{start}\0{end}\0{text}".encode()
    return hashlib.sha256(material).hexdigest()


def _drop_file(conn: sqlite3.Connection, source: str, path: str) -> None:
    ids = [row["chunk_id"] for row in conn.execute(
        "SELECT chunk_id FROM chunks WHERE source = ? AND path = ?", (source, path)
    )]
    for chunk_id in ids:
        conn.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk_id,))
    conn.execute("DELETE FROM chunks WHERE source = ? AND path = ?", (source, path))


def _insert_file(
    conn: sqlite3.Connection, source: str, relative: str, path: Path,
    data: bytes, commit: str, dirty: bool, indexed_at: str,
) -> int:
    text = data.decode("utf-8")
    digest = _digest(data)
    mtime_ns = path.stat().st_mtime_ns
    conn.execute(
        "INSERT OR REPLACE INTO files "
        "(source,path,sha256,size,mtime_ns,repo_commit,dirty,indexed_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (source, relative, digest, len(data), mtime_ns, commit, int(dirty), indexed_at),
    )
    count = 0
    for chunk in chunk_text(relative, text):
        chunk_id = _chunk_id(source, relative, chunk.line_start, chunk.line_end, chunk.text)
        conn.execute(
            "INSERT OR REPLACE INTO chunks "
            "(chunk_id,source,path,line_start,line_end,heading,text,sha256,repo_commit,dirty) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (chunk_id, source, relative, chunk.line_start, chunk.line_end,
             chunk.heading, chunk.text, digest, commit, int(dirty)),
        )
        conn.execute(
            "INSERT INTO chunks_fts (chunk_id,path,heading,text) VALUES (?,?,?,?)",
            (chunk_id, relative, chunk.heading, chunk.text),
        )
        count += 1
    return count


def build(config: KnowledgeConfig, *, dry_run: bool = False) -> BuildStats:
    candidates = scan(config)
    if dry_run:
        return BuildStats(
            included_files=len(candidates.included),
            chunks=0,
            skipped=0,
            removed=0,
            secret_skipped=0,
            unreadable=0,
            excluded=len(candidates.excluded),
            index_path=config.index_path,
            dry_run=True,
        )

    conn = _connect(config.index_path)
    indexed_at = datetime.now(UTC).isoformat()
    states = {
        source.name: git_state(source.root)
        for source in config.sources
        if source.root.is_dir()
        and (not source.markers or any((source.root / marker).exists() for marker in source.markers))
    }
    existing = {
        (row["source"], row["path"]): row
        for row in conn.execute("SELECT * FROM files")
    }
    seen: set[tuple[str, str]] = set()
    included = skipped = chunks = secret_skipped = unreadable = 0
    for candidate in candidates.included:
        key = (candidate.source, candidate.relative)
        seen.add(key)
        try:
            if candidate.path.stat().st_size > config.max_file_bytes:
                unreadable += 1
                continue
            data = candidate.path.read_bytes()
        except OSError:
            unreadable += 1
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            unreadable += 1
            continue
        if contains_secret(config, text):
            secret_skipped += 1
            continue
        state = states[candidate.source]
        digest = _digest(data)
        previous = existing.get(key)
        if previous is not None and previous["sha256"] == digest:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM chunks WHERE source = ? AND path = ?", key
            ).fetchone()["n"]
            if count:
                skipped += 1
                continue
        _drop_file(conn, *key)
        chunks += _insert_file(
            conn, candidate.source, candidate.relative, candidate.path,
            data, state.commit, state.dirty, indexed_at,
        )
        included += 1

    removed = 0
    for key in existing:
        if key not in seen:
            _drop_file(conn, *key)
            conn.execute("DELETE FROM files WHERE source = ? AND path = ?", key)
            removed += 1

    for source in config.sources:
        if source.name not in states:
            conn.execute("DELETE FROM meta WHERE key = ?", (f"commit:{source.name}",))
            conn.execute("DELETE FROM meta WHERE key = ?", (f"dirty:{source.name}",))
            continue
        state = states[source.name]
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                     (f"commit:{source.name}", state.commit))
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                     (f"dirty:{source.name}", "1" if state.dirty else "0"))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)", (indexed_at,))
    conn.commit()
    conn.close()
    config.index_path.chmod(0o600)
    return BuildStats(
        included_files=included,
        chunks=chunks,
        skipped=skipped,
        removed=removed,
        secret_skipped=secret_skipped,
        unreadable=unreadable,
        excluded=len(candidates.excluded),
        index_path=config.index_path,
    )


def status(index_path: Path) -> dict[str, object]:
    if not index_path.is_file():
        return {"exists": False, "index_path": str(index_path)}
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    try:
        files = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
        chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        meta = {row["key"]: row["value"] for row in conn.execute("SELECT * FROM meta")}
    finally:
        conn.close()
    return {
        "exists": True,
        "index_path": str(index_path),
        "files": files,
        "chunks": chunks,
        "meta": meta,
    }


def list_candidates(config: KnowledgeConfig) -> dict[str, list[dict[str, str]]]:
    result = scan(config)
    return {
        "included": [
            {"source": item.source, "path": item.relative}
            for item in result.included
        ],
        "excluded": [
            {"source": item.source, "path": item.relative, "reason": item.reason}
            for item in result.excluded
        ],
    }


def _set_state(conn: sqlite3.Connection, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('state', ?)", (value,))
    conn.commit()


def start_background_index(config: KnowledgeConfig) -> threading.Thread:
    """Refresh the index on server start without blocking the web listener."""
    def run() -> None:
        try:
            if config.index_path.is_file():
                conn = _connect(config.index_path)
                _set_state(conn, "indexing")
                conn.close()
            build(config)
            conn = _connect(config.index_path)
            _set_state(conn, "ready")
            conn.close()
        except Exception:
            try:
                conn = _connect(config.index_path)
                _set_state(conn, "error")
                conn.close()
            except Exception:
                pass
    thread = threading.Thread(target=run, name="knowledge-index", daemon=True)
    thread.start()
    return thread
