"""Policy: turn rule evaluations into one decision.

Severity comes from the constitution, never from the caller:

    veto       the proposal is rejected; the deterministic fallback is used
    downgrade  the offending item is reduced; the prescription survives
    warn       recorded and surfaced; no change
    advisory   informational only

The aggregate outcome is ordered, and `unknown` sits *above* `pass`: a run in which the
symptom rules could not be assessed is not a compliant run (AGENTS.md invariant 12).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from strength_coach.rules import registry
from strength_coach.rules.context import RuleContext
from strength_coach.rules.loader import RuleDocument
from strength_coach.rules.registry import Evaluation, Evidence

VETO = "veto"
DOWNGRADE = "downgrade"
WARN = "warn"
ADVISORY = "advisory"

# Most severe first. Used for the aggregate outcome and for reporting.
_SEVERITY_ORDER = (VETO, DOWNGRADE, WARN, ADVISORY)


class UnresolvedReference(RuntimeError):
    """An evidence reference does not resolve to a stored fact."""


@dataclass(frozen=True)
class RuleVerdict:
    rule_id: str
    title: str
    severity: str
    action: str
    verdict: str
    code: str | None
    evidence: tuple[Evidence, ...]
    missing_inputs: tuple[str, ...]
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.verdict == registry.FAIL

    @property
    def unknown(self) -> bool:
        return self.verdict == registry.UNKNOWN

    @property
    def passed(self) -> bool:
        return self.verdict == registry.PASS


@dataclass(frozen=True)
class PolicyResult:
    document_id: str
    document_version: str
    verdicts: tuple[RuleVerdict, ...]

    def verdict(self, rule_id: str) -> RuleVerdict:
        for candidate in self.verdicts:
            if candidate.rule_id == rule_id:
                return candidate
        raise KeyError(f"rule {rule_id!r} was not evaluated")

    @property
    def failures(self) -> tuple[RuleVerdict, ...]:
        return tuple(v for v in self.verdicts if v.failed)

    @property
    def unknowns(self) -> tuple[RuleVerdict, ...]:
        return tuple(v for v in self.verdicts if v.unknown)

    @property
    def vetoes(self) -> tuple[RuleVerdict, ...]:
        return tuple(v for v in self.failures if v.action == VETO)

    @property
    def downgrades(self) -> tuple[RuleVerdict, ...]:
        return tuple(v for v in self.failures if v.action == DOWNGRADE)

    @property
    def warnings(self) -> tuple[RuleVerdict, ...]:
        return tuple(v for v in self.failures if v.action == WARN)

    @property
    def advisories(self) -> tuple[RuleVerdict, ...]:
        return tuple(v for v in self.failures if v.action == ADVISORY)

    @property
    def unknown_rule_ids(self) -> tuple[str, ...]:
        return tuple(v.rule_id for v in self.unknowns)

    @property
    def outcome(self) -> str:
        """The strongest effect in the result: veto > downgrade > warn > unknown > pass."""
        for level in (VETO, DOWNGRADE, WARN):
            if any(v.action == level for v in self.failures):
                return level
        if self.advisories:
            return ADVISORY
        if self.unknowns:
            return registry.UNKNOWN
        return registry.PASS


def evaluate(
    document: RuleDocument,
    context: RuleContext,
    *,
    rule_ids: Sequence[str] | None = None,
    validate_evidence: bool = True,
) -> PolicyResult:
    """Evaluate the document (or a subset) against a context."""
    selected = list(document.rules)
    if rule_ids is not None:
        wanted = set(rule_ids)
        selected = [rule for rule in document.rules if rule.id in wanted]
        missing = wanted - {rule.id for rule in selected}
        if missing:
            raise KeyError(f"unknown rule ids: {sorted(missing)}")

    verdicts: list[RuleVerdict] = []
    for rule in selected:
        evaluation: Evaluation = registry.get(rule.check_fn)(document, rule, context)
        if validate_evidence:
            unresolved = [
                item.ref
                for item in evaluation.evidence
                if not resolve_reference(context, item.ref)
            ]
            if unresolved:
                # A citation that does not resolve is a hallucination, even when produced by
                # Python: fail loudly instead of storing an unverifiable rationale.
                raise UnresolvedReference(
                    f"{rule.id} cited unresolvable evidence: {unresolved}"
                )
        verdicts.append(
            RuleVerdict(
                rule_id=rule.id,
                title=rule.title,
                severity=rule.severity,
                action=rule.fail_action,
                verdict=evaluation.verdict,
                code=evaluation.code if evaluation.failed else None,
                evidence=evaluation.evidence,
                missing_inputs=evaluation.missing_inputs,
                details=evaluation.details,
            )
        )

    return PolicyResult(
        document_id=document.document_id,
        document_version=document.version,
        verdicts=tuple(verdicts),
    )


def resolve_reference(context: RuleContext, ref: str) -> bool:
    """Whether an evidence reference names a fact that exists in this context.

    The context carries the lookup indices (`set_keys`, `session_ids`, `iso_weeks`) so this
    is O(1) per citation. Rebuilding them here made a rule-heavy forecast take minutes; the
    fallbacks keep a hand-built context correct.
    """
    kind, _, value = ref.partition(":")
    if kind == "set":
        session_id, _, set_id = value.partition("/")
        if not set_id.isdigit() or context.sets.empty:
            return False
        key = (session_id, int(set_id))
        if context.set_keys:
            return key in context.set_keys
        match = context.sets[
            (context.sets["set_id"] == int(set_id))
            & (context.sets["session_id"].astype(str) == session_id)
        ]
        return not match.empty
    if kind == "session":
        if context.sets.empty:
            return False
        if context.session_ids:
            return value in context.session_ids
        return value in set(context.sets["session_id"].astype(str))
    if kind == "symptom":
        return context.symptom_on is not None and context.symptom_on == value
    if kind == "week":
        if context.sets.empty:
            return False
        if context.iso_weeks:
            return value in context.iso_weeks
        weeks = {
            registry.iso_week(value) for value in context.sets["date"].dropna()
        }
        return value in weeks
    return False


def publish(conn, document: RuleDocument) -> bool:
    """Persist the document and its rules; return True when newly written.

    Re-publishing the same version with the same bytes is a no-op, so a retried run cannot
    create a second copy. Publishing a *different* document under an existing version is
    refused: rules are immutable and a change means a new version.
    """
    from strength_coach.store import repositories as repo

    if document.effective_from is None:
        # A draft is not in force. Storing it with an invented date would make "which version
        # applied on this date" answerable wrongly, so refusing is the honest option.
        raise ValueError(
            f"{document.document_id} {document.version} has no effective_from "
            f"(status {document.status!r}); approve it before publishing"
        )

    existing = conn.execute(
        "SELECT source_hash FROM rule_document WHERE document_id = ? AND version = ?",
        (document.document_id, document.version),
    ).fetchone()
    if existing is not None:
        if existing["source_hash"] != document.source_hash:
            raise ValueError(
                f"{document.document_id} {document.version} already published with a different "
                "content hash; bump the version instead of editing a released one"
            )
        return False

    repo.append_rule_document(
        conn,
        document_id=document.document_id,
        version=document.version,
        effective_from=document.effective_from,
        source_hash=document.source_hash,
        body_yaml=document.body_yaml,
    )
    for rule in document.rules:
        repo.append_rule(
            conn,
            rule_id=rule.id,
            document_id=document.document_id,
            document_version=document.version,
            severity=rule.severity,
            scope=dict(rule.scope),
            check_fn=rule.check_fn,
            citations=list(rule.citations),
            depends_on_data_decisions=list(rule.depends_on_data_decisions),
            body=dict(rule.raw or {}),
        )
    return True
