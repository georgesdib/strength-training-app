"""FTS5 retrieval over the local knowledge index."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

EXPLICIT_FILE = re.compile(r"([A-Za-z0-9_.-]+\.(?:md|py|swift|ya?ml))", re.IGNORECASE)

EXPANSIONS = {
    "readiness": ("readiness", "score", "composite"),
    "calculated": ("calculate", "formula", "composite"),
    "deload": ("deload", "reactive", "flare", "flares", "back-off", "backoff", "injury"),
    "injury": ("injury", "symptom", "flare", "flares", "deload"),
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


def query_kind(question: str) -> str:
    text = question.lower()
    if any(term in text for term in ("where in the code", "source code", "implementation", "function", "module", "class ")):
        return "code"
    if any(term in text for term in ("test suite", "tests expect", "test expectation", "assert")):
        return "test"
    if any(term in text for term in ("my private", "athlete state", "my back", "my velocity", "private note")):
        return "private"
    return "docs"


def _bucket(chunk: RetrievedChunk) -> str:
    path = chunk.path.lower()
    if path.startswith("private/"):
        return "private"
    if "/tests/" in path or path.startswith("tests/") or "/strengthapptests/" in path or "/tests/" in path:
        return "test"
    if path.endswith((".py", ".swift")):
        return "code"
    return "docs"


def _rerank(candidates: list[RetrievedChunk], question: str) -> list[RetrievedChunk]:
    kind = query_kind(question)
    terms = _terms(question)
    preferred = {"docs": "docs", "code": "code", "test": "test", "private": "private"}[kind]
    explicit_names = [name.lower() for name in EXPLICIT_FILE.findall(question)]
    ranked = []
    for index, chunk in enumerate(candidates):
        bucket = _bucket(chunk)
        score = 1000 - index
        if bucket == preferred:
            score += 1500
        elif kind == "docs" and bucket == "private":
            score += 900
        elif kind == "docs" and bucket == "code":
            score += 50
        elif kind == "docs" and bucket == "test":
            score -= 400
        elif kind == "code" and bucket == "docs":
            score += 80
        elif kind == "private" and bucket == "docs":
            score += 100
        path_text = chunk.path.lower()
        heading = chunk.heading.lower()
        if any(name in path_text for name in explicit_names):
            score += 3000
        if "load" in question.lower() and path_text == "strength_coach/prescribe/engine.py":
            score += 2000
        if "load" in question.lower() and path_text in {
            "strength_coach/prescribe/loads.py",
            "strength_coach/prescribe/models.py",
        }:
            score += 500
        if path_text.startswith("config/") or "/config/" in path_text:
            score += 700
        key_terms = {
            "injury", "deload", "volume", "performance", "readiness", "agents",
            "srpe", "vbt", "calibration", "prescription", "programme", "block",
        }
        for term in terms:
            if term in path_text:
                score += 800 if term in key_terms else 100
            if term in heading:
                score += 200 if term in key_terms else 80
        ranked.append((score, index, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked]


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
            (match, top_k * 8),
        ).fetchall()
        extra = []
        for name in EXPLICIT_FILE.findall(question):
            extra.extend(conn.execute(
                "SELECT c.* FROM chunks c WHERE lower(c.path) = lower(?) "
                "OR lower(c.path) LIKE lower(?) ORDER BY c.path, c.line_start LIMIT 20",
                (name, "%/" + name),
            ).fetchall())
        if "load" in question.lower():
            for target in (
                "strength_coach/prescribe/engine.py",
                "strength_coach/prescribe/loads.py",
                "strength_coach/prescribe/models.py",
            ):
                extra.extend(conn.execute(
                    "SELECT c.* FROM chunks c WHERE c.path = ? ORDER BY c.line_start LIMIT 12",
                    (target,),
                ).fetchall())
        for term in [item for item in _terms(question) if len(item) >= 5][:8]:
            extra.extend(conn.execute(
                "SELECT c.* FROM chunks c WHERE lower(c.path) LIKE ? "
                "ORDER BY c.line_start LIMIT 8",
                ("%" + term + "%",),
            ).fetchall())
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    candidates: list[RetrievedChunk] = []
    seen: set[tuple[str, int, int]] = set()
    for row in [*rows, *extra]:
        key = (row["path"], row["line_start"], row["line_end"])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            RetrievedChunk(
                chunk_id=row["chunk_id"], source=row["source"], path=row["path"],
                line_start=int(row["line_start"]), line_end=int(row["line_end"]),
                heading=row["heading"], text=str(row["text"]), repo_commit=row["repo_commit"],
            )
        )
    ranked = _rerank(candidates, question)
    found: list[RetrievedChunk] = []
    path_counts: dict[str, int] = {}
    size = 0
    for chunk in ranked:
        if path_counts.get(chunk.path, 0) >= 3:
            continue
        if found and size + len(chunk.text) > max_chars:
            continue
        found.append(chunk)
        path_counts[chunk.path] = path_counts.get(chunk.path, 0) + 1
        size += len(chunk.text)
        if len(found) >= top_k:
            break
    return found
