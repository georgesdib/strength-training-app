"""Versioned rules, registry predicates and the policy engine.

Layering: above `store` and `features`, below `prescribe`/`critique`. A rule document is
immutable; the predicates in `registry` are the only implementations of `check.fn`, and
`policy` decides the effect (veto/downgrade/warn/advisory) -- predicates never do.
"""

from strength_coach.rules.context import RuleContext
from strength_coach.rules.loader import Rule, RuleDocument, RuleDocumentError, load_document
from strength_coach.rules.policy import (
    PolicyResult,
    RuleVerdict,
    UnresolvedReference,
    evaluate,
    publish,
    resolve_reference,
)

__all__ = [
    "PolicyResult",
    "Rule",
    "RuleContext",
    "RuleDocument",
    "RuleDocumentError",
    "RuleVerdict",
    "UnresolvedReference",
    "evaluate",
    "load_document",
    "publish",
    "resolve_reference",
]
