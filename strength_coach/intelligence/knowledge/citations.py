"""Extract and structurally check citations in an Explain answer."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from strength_coach.intelligence.knowledge.allowlist import KnowledgeConfig

GITHUB = {
    "backend": "https://github.com/georgesdib/strength-training-app/blob",
    "ios": "https://github.com/georgesdib/StrengthApp/blob",
    "portfolio": "https://github.com/georgesdib/strength-app/blob",
}
CITATION = re.compile(r"(?<![\w./-])([A-Za-z0-9_./-]+\.(?:py|md|swift|ya?ml|json|sh)):(\d+)(?:-(\d+))?")
QUOTE = re.compile(chr(96) + r"([^" + chr(96) + r"]{3,160})" + chr(96))


@dataclass(frozen=True)
class Citation:
    path: str
    line_start: int
    line_end: int
    source: str
    url: str | None
    verified: bool
    warning: str | None = None


def _source_for(
    config: KnowledgeConfig, path: str, source_name: str | None = None,
) -> tuple[str, Path, str] | None:
    for source in config.sources:
        if source_name is not None and source.name != source_name:
            continue
        if not source.root.is_dir():
            continue
        candidate = source.root / path
        if candidate.is_file():
            return source.name, candidate, source.name
    return None


def _index_meta(index_path: Path, path: str) -> tuple[str, str] | None:
    if not index_path.is_file():
        return None
    conn = sqlite3.connect(index_path)
    try:
        row = conn.execute(
            "SELECT source, repo_commit FROM chunks WHERE path = ? LIMIT 1", (path,)
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    return (str(row[0]), str(row[1])) if row else None


def _url(source: str, commit: str, path: str, start: int, end: int) -> str | None:
    if path.startswith("private/"):
        return None
    if path.startswith("docs/"):
        return "#docs?doc=" + quote(path)
    base = GITHUB.get(source)
    if base is None or commit in {"", "unknown"}:
        return None
    anchor = f"#L{start}" + (f"-L{end}" if end != start else "")
    return f"{base}/{commit}/{quote(path)}" + anchor


def extract(answer: str, config: KnowledgeConfig, index_path: Path) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[tuple[str, int, int]] = set()
    for match in CITATION.finditer(answer):
        path = match.group(1)
        start = int(match.group(2))
        end = int(match.group(3) or start)
        key = (path, start, end)
        if key in seen:
            continue
        seen.add(key)
        meta = _index_meta(index_path, path)
        found = _source_for(config, path, meta[0] if meta else None)
        if found is None or meta is None:
            citations.append(Citation(path, start, end, meta[0] if meta else "unknown", None, False, "path is not in the index"))
            continue
        source, absolute, _ = found
        try:
            lines = absolute.read_text(encoding="utf-8").splitlines()
        except OSError:
            citations.append(Citation(path, start, end, source, None, False, "path is unreadable"))
            continue
        if start < 1 or end < start or end > len(lines):
            citations.append(Citation(path, start, end, source, None, False, "line range is outside the file"))
            continue
        warning = None
        quoted = QUOTE.search(answer, match.end(), match.end() + 220)
        if quoted is not None:
            source_text = "\n".join(lines[start - 1:end]).lower()
            words = re.findall(r"[a-z0-9_]{4,}", quoted.group(1).lower())
            if words and not any(word in source_text for word in words):
                warning = "quoted snippet does not match the cited lines"
        citations.append(Citation(
            path, start, end, source, _url(source, meta[1], path, start, end),
            warning is None, warning,
        ))
    return citations
