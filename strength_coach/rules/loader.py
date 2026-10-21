"""Parse the constitution YAML into validated, hash-carrying rule objects.

The YAML is never interpreted as an expression: it names a registered predicate and the
arguments to pass it (docs/RULES-FORMAT.md §1). This module therefore does exactly two
things -- validate the document's shape, and turn it into immutable dataclasses.

Validation is deliberately strict. A typo in `check.fn` or a scope pointing at a missing
collection would otherwise become a rule that silently never fires, which is worse than a
crash: the report would claim the constitution passed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import yaml

from strength_coach.utils import paths

SEVERITIES = ("veto", "downgrade", "warn", "advisory")
RULE_ID_RE = re.compile(r"^[A-Z]{2,6}-[A-Z]{2,6}-\d{3}$")


class RuleDocumentError(ValueError):
    """The rule document is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Rule:
    """One constitutional rule: human statement, machine params, named predicate."""

    id: str
    title: str
    severity: str
    statement: str
    scope: Mapping[str, Any]
    params: Mapping[str, Any]
    inputs: tuple[str, ...]
    check_fn: str
    check_args: Mapping[str, Any]
    citations: tuple[str, ...]
    depends_on_data_decisions: tuple[str, ...]
    on_fail: Mapping[str, Any]
    notes: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def fail_code(self) -> str:
        return str(self.on_fail.get("code", "UNSPECIFIED"))

    @property
    def fail_action(self) -> str:
        """The policy effect when the rule fails; falls back to the rule severity."""
        return str(self.on_fail.get("action", self.severity))


@dataclass(frozen=True)
class RuleDocument:
    """A versioned constitution. Immutable: a change is a new version."""

    document_id: str
    version: str
    status: str
    effective_from: str | None
    owner: str
    source_text: str
    source_hash: str
    body_yaml: str
    collections: Mapping[str, tuple[str, ...]]
    rules: tuple[Rule, ...]
    modifiers: tuple[Mapping[str, Any], ...]
    path: Path = field(repr=False, default=Path())

    def rule(self, rule_id: str) -> Rule:
        for candidate in self.rules:
            if candidate.id == rule_id:
                return candidate
        raise KeyError(f"no rule {rule_id!r} in {self.document_id} {self.version}")

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.id for rule in self.rules)

    def collection(self, name: str) -> tuple[str, ...]:
        """Resolve a scope reference such as `$primary_compounds`."""
        key = name[1:] if name.startswith("$") else name
        try:
            return self.collections[key]
        except KeyError as exc:
            raise RuleDocumentError(
                f"scope references unknown collection {name!r}; "
                f"known: {sorted(self.collections)}"
            ) from exc

    def scope_exercises(self, scope: Mapping[str, Any]) -> tuple[str, ...] | None:
        """The exercise ids a rule is scoped to, or None when it is not exercise-scoped."""
        exercises = scope.get("exercises")
        if exercises is None:
            return None
        if isinstance(exercises, str):
            return self.collection(exercises)
        return tuple(str(item) for item in exercises)


def load_document(path: str | Path | None = None) -> RuleDocument:
    """Read, validate and hash the constitution.

    Parsing is cached by content hash: a forecast rebuilds the same document for every
    projected session, and parsing it each time cost more than the prescription itself. A
    changed file has a new digest, so an edit is never served from the cache.
    """
    source = Path(path or paths.programme_rules_yaml())
    if not source.exists():
        raise RuleDocumentError(f"rule document not found: {source}")
    body = source.read_text(encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return _parse_document(str(source), digest, body)


@lru_cache(maxsize=8)
def _parse_document(source_name: str, digest: str, body: str) -> RuleDocument:
    source = Path(source_name)
    raw = yaml.safe_load(body)
    if not isinstance(raw, dict):
        raise RuleDocumentError(f"{source.name}: top level must be a mapping")

    document = raw.get("document") or {}
    document_id = document.get("id")
    version = document.get("version")
    if not document_id or not version:
        raise RuleDocumentError(f"{source.name}: document.id and document.version are required")

    collections = _parse_collections(raw.get("collections") or {})
    rules = tuple(_parse_rule(item, index) for index, item in enumerate(raw.get("rules") or []))
    _check_unique([rule.id for rule in rules], "rule id", source.name)
    _check_predicates_exist(rules, source.name)

    parsed = RuleDocument(
        document_id=str(document_id),
        version=str(version),
        status=str(document.get("status", "unspecified")),
        effective_from=_optional_str(document.get("effective_from")),
        owner=str(document.get("owner", "unknown")),
        source_text=str(document.get("source_text", "")),
        source_hash=digest,
        body_yaml=body,
        collections=collections,
        rules=rules,
        modifiers=tuple(dict(m) for m in (raw.get("modifiers") or [])),
        path=source,
    )
    _validate_scope_references(parsed)
    return parsed


def _parse_collections(raw: Mapping[str, Any]) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType(
        {
            str(name): tuple(str(item) for item in (items or ()))
            for name, items in raw.items()
        }
    )


def _parse_rule(item: Mapping[str, Any], index: int) -> Rule:
    where = f"rule #{index + 1}"
    if not isinstance(item, dict):
        raise RuleDocumentError(f"{where}: expected a mapping")
    rule_id = item.get("id")
    if not rule_id or not RULE_ID_RE.match(str(rule_id)):
        raise RuleDocumentError(f"{where}: invalid id {rule_id!r}; expected e.g. PRG-RIR-001")
    where = str(rule_id)

    severity = str(item.get("severity", ""))
    if severity not in SEVERITIES:
        raise RuleDocumentError(f"{where}: severity must be one of {SEVERITIES}, got {severity!r}")

    check = item.get("check") or {}
    if not check.get("fn"):
        raise RuleDocumentError(f"{where}: check.fn is required")

    on_fail = item.get("on_fail") or {}
    action = str(on_fail.get("action", severity))
    if action not in SEVERITIES:
        raise RuleDocumentError(f"{where}: on_fail.action must be one of {SEVERITIES}")
    if not on_fail.get("code"):
        raise RuleDocumentError(f"{where}: on_fail.code is required")

    scope = item.get("scope") or {}
    if not isinstance(scope, dict):
        raise RuleDocumentError(f"{where}: scope must be a mapping")

    return Rule(
        id=where,
        title=str(item.get("title", where)),
        severity=severity,
        statement=str(item.get("statement", "")),
        scope=MappingProxyType(dict(scope)),
        params=MappingProxyType(dict(item.get("params") or {})),
        inputs=tuple(str(i) for i in (item.get("inputs") or ())),
        check_fn=str(check["fn"]),
        check_args=MappingProxyType(dict(check.get("args") or {})),
        citations=tuple(str(c) for c in (item.get("citations") or ())),
        depends_on_data_decisions=tuple(
            str(d) for d in (item.get("depends_on_data_decisions") or ())
        ),
        on_fail=MappingProxyType(dict(on_fail)),
        notes=str(item.get("notes", "")),
    )


def _check_unique(values: Sequence[str], what: str, source: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise RuleDocumentError(f"{source}: duplicate {what}s: {sorted(set(duplicates))}")


def _check_predicates_exist(rules: Sequence[Rule], source: str) -> None:
    # Imported lazily so the registry can type-hint against this module without a cycle.
    from strength_coach.rules import registry

    known = set(registry.registered())
    unknown = sorted({rule.check_fn for rule in rules if rule.check_fn not in known})
    if unknown:
        raise RuleDocumentError(
            f"{source}: unregistered check.fn {unknown}; known predicates: {sorted(known)}"
        )


def _validate_scope_references(document: RuleDocument) -> None:
    for rule in document.rules:
        exercises = rule.scope.get("exercises")
        if isinstance(exercises, str) and exercises.startswith("$"):
            document.collection(exercises)  # raises with a helpful message


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
