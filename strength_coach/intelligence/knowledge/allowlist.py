"""Allowlist and exclusion rules for the local knowledge index."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config" / "knowledge.v1.yaml"


class KnowledgeConfigError(ValueError):
    """The knowledge allowlist is missing or malformed."""


@dataclass(frozen=True)
class SourceRule:
    name: str
    root: Path
    include: tuple[re.Pattern[str], ...]
    exclude: tuple[re.Pattern[str], ...]
    markers: tuple[str, ...] = ()

    def allows(self, relative: str) -> tuple[bool, str]:
        if not any(pattern.match(relative) for pattern in self.include):
            return False, "not-included"
        if any(pattern.match(relative) for pattern in self.exclude):
            return False, "source-excluded"
        return True, "included"


@dataclass(frozen=True)
class KnowledgeConfig:
    path: Path
    index_path: Path
    max_file_bytes: int
    top_k: int
    max_context_chars: int
    max_answer_words: int
    sources: tuple[SourceRule, ...]
    deny_always: tuple[re.Pattern[str], ...]
    deny_test_data: tuple[re.Pattern[str], ...]
    secret_patterns: tuple[re.Pattern[str], ...]

    def source(self, name: str) -> SourceRule:
        for source in self.sources:
            if source.name == name:
                return source
        raise KeyError(name)


def _compile(values: object, field: str) -> tuple[re.Pattern[str], ...]:
    if values is None:
        return ()
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise KnowledgeConfigError(f"{field} must be a list of regex strings")
    try:
        return tuple(re.compile(value) for value in values)
    except re.error as exc:
        raise KnowledgeConfigError(f"invalid regex in {field}: {exc}") from exc


def _root(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise KnowledgeConfigError(f"{field} must be a path string")
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def load_config(path: str | Path | None = None) -> KnowledgeConfig:
    target = Path(path) if path else DEFAULT_CONFIG
    if not target.is_file():
        raise KnowledgeConfigError(f"knowledge config not found: {target}")
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise KnowledgeConfigError(f"invalid knowledge config: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise KnowledgeConfigError("knowledge config must be version 1")
    sources = []
    for item in raw.get("sources") or []:
        if not isinstance(item, dict) or not item.get("name"):
            raise KnowledgeConfigError("each source needs a name")
        sources.append(
            SourceRule(
                name=str(item["name"]),
                root=_root(item.get("root"), f"source {item['name']} root"),
                include=_compile(item.get("include"), f"source {item['name']} include"),
                exclude=_compile(item.get("exclude"), f"source {item['name']} exclude"),
                markers=tuple(str(value) for value in (item.get("markers") or [])),
            )
        )
    if not sources:
        raise KnowledgeConfigError("at least one knowledge source is required")
    index_path = _root(raw.get("index_path", "data/knowledge-index.sqlite"), "index_path")
    max_file_bytes = int(raw.get("max_file_bytes", 1_048_576))
    if max_file_bytes < 1:
        raise KnowledgeConfigError("max_file_bytes must be positive")
    retrieval = raw.get("retrieval") or {}
    if not isinstance(retrieval, dict):
        raise KnowledgeConfigError("retrieval must be a mapping")
    top_k = int(retrieval.get("top_k", 8))
    max_context_chars = int(retrieval.get("max_context_chars", 24_000))
    max_answer_words = int(retrieval.get("max_answer_words", 320))
    if not 1 <= top_k <= 20 or max_context_chars < 1 or max_answer_words < 32:
        raise KnowledgeConfigError("retrieval bounds are out of range")
    return KnowledgeConfig(
        path=target.resolve(),
        index_path=index_path,
        max_file_bytes=max_file_bytes,
        top_k=top_k,
        max_context_chars=max_context_chars,
        max_answer_words=max_answer_words,
        sources=tuple(sources),
        deny_always=_compile(raw.get("deny_always"), "deny_always"),
        deny_test_data=_compile(raw.get("deny_test_data"), "deny_test_data"),
        secret_patterns=_compile(raw.get("secret_content_patterns"), "secret_content_patterns"),
    )


@dataclass(frozen=True)
class Candidate:
    source: str
    relative: str
    path: Path
    reason: str = "included"


@dataclass(frozen=True)
class ScanResult:
    included: tuple[Candidate, ...]
    excluded: tuple[Candidate, ...]

    @property
    def reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.excluded:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts


def _relative(path: Path, root: Path) -> str:
    return PurePosixPath(path.relative_to(root).as_posix()).as_posix()


def evaluate(config: KnowledgeConfig, source_name: str, relative: str) -> tuple[bool, str]:
    source = config.source(source_name)
    normalized = PurePosixPath(relative)
    if normalized.is_absolute() or ".." in normalized.parts:
        return False, "traversal"
    if any(pattern.search(relative) for pattern in config.deny_always):
        return False, "always-denied"
    if any(pattern.search(relative) for pattern in config.deny_test_data):
        return False, "test-data"
    return source.allows(relative)


def scan(config: KnowledgeConfig) -> ScanResult:
    included: list[Candidate] = []
    excluded: list[Candidate] = []
    for source in config.sources:
        if not source.root.is_dir():
            continue
        if source.markers and not any((source.root / marker).exists() for marker in source.markers):
            continue
        for current, dirnames, filenames in os.walk(source.root):
            current_path = Path(current)
            relative_dir = _relative(current_path, source.root)
            prefix = "" if relative_dir == "." else relative_dir + "/"
            dirnames[:] = sorted(
                name for name in dirnames
                if not any(pattern.search(prefix + name + "/") for pattern in config.deny_always)
                and not any(pattern.search(prefix + name + "/") for pattern in config.deny_test_data)
            )
            for name in sorted(filenames):
                path = current_path / name
                if path.is_symlink() or not path.is_file():
                    continue
                relative = _relative(path, source.root)
                allowed, reason = evaluate(config, source.name, relative)
                candidate = Candidate(source.name, relative, path, reason)
                if allowed:
                    included.append(candidate)
                else:
                    excluded.append(candidate)
    return ScanResult(tuple(included), tuple(excluded))


def contains_secret(config: KnowledgeConfig, text: str) -> bool:
    return any(pattern.search(text) for pattern in config.secret_patterns)
