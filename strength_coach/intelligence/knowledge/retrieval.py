"""FTS5 retrieval over the local knowledge index."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

EXPANSIONS = {
    "readiness": ("readiness", "score", "composite"),
    "calculated": ("calculate", "formula", "composite"),
    "deload": ("deload", "back-off", "backoff", "injury"),
    "injury": ("injury", "symptom", "deload"),
    "evidence": ("evidence", "rationale", "research"),
}


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    source: str
    path: str
    line_start: int
    line_end: int
    heading: str
    text: str
    repo_commit: str


def _terms(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]{2,}", question.lower())
    expanded: list[str] = []
    for word in words:
        expanded.append(word)
        expanded.extend(EXPANSIONS.get(word, ()))
    return list(dict.fromkeys(expanded))


def query_text(question: str) -> str:
    terms = _terms(question)
    return " OR ".join(f'"{term}"' for term in terms) if terms else ""


def search(index_path: Path, question: str, *, top_k: int, max_chars: int) -> list[RetrievedChunk]:
    match = query_text(question)
    if not match or not index_path.is_file():
        return []
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT c.* FROM chunks_fts JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id "
            "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, top_k * 3),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    found: list[RetrievedChunk] = []
    seen: set[tuple[str, int, int]] = set()
    size = 0
    for row in rows:
        key = (row["path"], row["line_start"], row["line_end"])
        if key in seen:
            continue
        seen.add(key)
        text = str(row["text"])
        if found and size + len(text) > max_chars:
            continue
        found.append(
            RetrievedChunk(
                chunk_id=row["chunk_id"], source=row["source"], path=row["path"],
                line_start=int(row["line_start"]), line_end=int(row["line_end"]),
                heading=row["heading"], text=text, repo_commit=row["repo_commit"],
            )
        )
        size += len(text)
        if len(found) >= top_k:
            break
    return found
