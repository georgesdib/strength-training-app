"""Chunk source files for the knowledge index."""

from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass

MAX_CHUNK_CHARS = 6000


@dataclass(frozen=True)
class Chunk:
    line_start: int
    line_end: int
    heading: str
    text: str


def _split_long(text: str, start: int) -> list[Chunk]:
    lines = text.splitlines(keepends=True)
    chunks: list[Chunk] = []
    current: list[str] = []
    current_start = start
    size = 0
    for offset, line in enumerate(lines, start):
        if current and size + len(line) > MAX_CHUNK_CHARS:
            chunks.append(Chunk(current_start, offset - 1, "", "".join(current).strip()))
            current = []
            current_start = offset
            size = 0
        current.append(line)
        size += len(line)
    if current and "".join(current).strip():
        chunks.append(Chunk(current_start, start + len(lines) - 1, "", "".join(current).strip()))
    return chunks


def _markdown(lines: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    headings: list[str] = []
    start = 1
    body: list[str] = []
    current_heading = ""

    def flush(end: int) -> None:
        nonlocal body
        text = "".join(body).strip()
        if text:
            chunks.extend(_split_long(text, start) if len(text) > MAX_CHUNK_CHARS
                          else [Chunk(start, end, current_heading, text)])
        body = []

    for number, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line.rstrip("\n"))
        if match:
            flush(number - 1)
            level = len(match.group(1))
            headings = headings[: level - 1] + [match.group(2).strip()]
            current_heading = " / ".join(headings)
            start = number
        body.append(line)
    flush(len(lines))
    return [chunk for chunk in chunks if chunk.text]


def _python(text: str, lines: list[str]) -> list[Chunk]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(text)
    except SyntaxError:
        return []
    chunks: list[Chunk] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            chunk_text = "".join(lines[start - 1:end]).strip()
            if chunk_text:
                chunks.append(Chunk(start, end, getattr(node, "name", ""), chunk_text))
    if not chunks:
        return []
    first = min(chunk.line_start for chunk in chunks)
    preamble = "".join(lines[: first - 1]).strip()
    if preamble:
        chunks.insert(0, Chunk(1, first - 1, "module", preamble))
    return chunks


def _swift(lines: list[str]) -> list[Chunk]:
    pattern = re.compile(
        r"^\s*(?:(?:public|private|internal|fileprivate|open|final|@MainActor)\s+)*"
        r"(?:struct|class|enum|actor|protocol|extension|func|init)\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    starts: list[tuple[int, str]] = []
    for number, line in enumerate(lines, 1):
        match = pattern.match(line)
        if match:
            starts.append((number, match.group(1)))
    if not starts:
        return []
    chunks: list[Chunk] = []
    for index, (start, name) in enumerate(starts):
        end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
        text = "".join(lines[start - 1:end]).strip()
        if text:
            chunks.append(Chunk(start, end, name, text))
    preamble = "".join(lines[: starts[0][0] - 1]).strip()
    if preamble:
        chunks.insert(0, Chunk(1, starts[0][0] - 1, "module", preamble))
    return chunks


def chunk_text(path: str, text: str) -> list[Chunk]:
    lines = text.splitlines(keepends=True)
    suffix = path.rsplit(".", 1)[-1].lower()
    if suffix == "md":
        return _markdown(lines)
    if suffix == "py":
        return _python(text, lines) or _split_long(text, 1)
    if suffix == "swift":
        return _swift(lines) or _split_long(text, 1)
    return _split_long(text, 1)
