"""Locate: answer "where in the UI" with the model, grounded on a fixed target list.

The search index owns navigation; this module only phrases an answer over targets the server has
already resolved. Nothing the model writes becomes a link, and an answer that names a place
outside the supplied targets is marked unverified rather than trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

SYSTEM = (
    "You help someone find a screen in a training application. Use only the TARGETS list. "
    "Name the navigation path exactly as written, for example 'Settings → Resolver'. "
    "Never invent a view, panel, field, document or link; never write markdown links or URLs. "
    "Keep the answer under 60 words. If no target fits, say you could not find it."
)

_ARROWS = r"→|->|›|»"
LINK = re.compile(r"\]\(|https?://|#docs\?|#view|#search")
DOC = re.compile(r"[A-Za-z0-9_./\-]+\.(?:md|py)")
_SPLIT_VALUE = re.compile(r"·|—|/|,")
_SPLIT_LINE = re.compile(r"[\n.;]")
MIN_LABEL = 3


class LocateClient(Protocol):
    """The one model call this module needs; the web layer passes its concrete client."""

    def complete(self, prompt: str, *, system: str | None = None) -> Any: ...


@dataclass(frozen=True)
class LocateResult:
    answer: str
    verified: bool
    warning: str | None
    tokens: int | None
    sources: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _labels(targets: list[dict[str, Any]]) -> set[str]:
    labels: set[str] = set()
    for target in targets:
        for value in (str(target.get("title", "")), str(target.get("subtitle", ""))):
            for part in _SPLIT_VALUE.split(value):
                part = part.strip().lower()
                if len(part) >= MIN_LABEL:
                    labels.add(part)
    return labels


def _allowed_docs(targets: list[dict[str, Any]]) -> set[str]:
    return {str(target.get("doc", "")).lower() for target in targets if target.get("doc")}


def _chains(answer: str) -> list[list[str]]:
    chains = []
    for line in _SPLIT_LINE.split(answer):
        if not re.search(_ARROWS, line):
            continue
        parts = [part.strip(" \t*'\"()[]") for part in re.split(_ARROWS, line)]
        parts = [part for part in parts if part]
        if parts:
            chains.append(parts)
    return chains


def _known(part: str, labels: set[str]) -> bool:
    text = part.strip().lower()
    if len(text) < MIN_LABEL:
        return True
    return any(label in text or text in label for label in labels)


def verify(answer: str, targets: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Check the prose against the supplied targets. The first problem wins."""
    if LINK.search(answer):
        return False, "the answer tried to add a link"
    labels = _labels(targets)
    for chain in _chains(answer):
        for part in chain:
            if not _known(part, labels):
                return False, f"unknown place: {part[:40]}"
    allowed = _allowed_docs(targets)
    for name in DOC.findall(answer):
        if name.lower() not in allowed:
            return False, f"unknown document: {name}"
    return True, None


def _target_line(index: int, target: dict[str, Any]) -> str:
    kind = str(target.get("kind", ""))
    title = str(target.get("title", ""))
    subtitle = str(target.get("subtitle", ""))
    doc = str(target.get("doc", ""))
    line = f'{index}. [{kind}] "{title}"'
    if subtitle:
        line += " — " + subtitle
    if doc:
        line += " (" + doc + ")"
    return line


def _prompt(query: str, targets: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> str:
    target_text = "\n".join(
        _target_line(index, target) for index, target in enumerate(targets, start=1)
    ) or "(no target matched)"
    source_text = "\n\n".join(
        "[{path}:{start}-{end}] {text}".format(
            path=chunk["path"],
            start=chunk["line_start"],
            end=chunk["line_end"],
            text=str(chunk.get("text", ""))[:400],
        )
        for chunk in chunks
    ) or "(no project source matched)"
    return (
        "QUESTION:\n" + query + "\n\n"
        "TARGETS (the only places that exist):\n" + target_text + "\n\n"
        "PROJECT SOURCES:\n" + source_text + "\n\n"
        "Answer with the navigation path. Do not add links."
    )


def run_locate(
    client: LocateClient,
    query: str,
    targets: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> LocateResult:
    """Ask the model where the query's answer lives, then check it against the targets."""
    response = client.complete(_prompt(query, targets, chunks), system=SYSTEM)
    answer = str(response.text).strip()
    verified, warning = verify(answer, targets)
    sources = tuple(
        {
            "path": chunk["path"],
            "heading": chunk.get("heading", ""),
            "line_start": chunk["line_start"],
            "line_end": chunk["line_end"],
        }
        for chunk in chunks
    )
    return LocateResult(answer, verified, warning, response.tokens, sources)
