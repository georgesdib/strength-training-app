"""Derived-analytics infrastructure (phase 1).

The package records durable source revisions and the lifecycle of analytical family builds. It
does not materialise any analytical data yet: no consumer reads it and no metric is computed here.

Design: docs/design/DERIVED-ANALYTICS-ARCHITECTURE.md §4.4.
"""

from __future__ import annotations

from strength_coach.analytics.coordinator import (
    family_state,
    is_ready,
    publish,
    run_build,
    status_snapshot,
)
from strength_coach.analytics.families import FamilySpec, spec_for
from strength_coach.analytics.revision import (
    current_revision,
    record_dependency_change,
    record_mutation,
)

__all__ = [
    "FamilySpec",
    "current_revision",
    "family_state",
    "is_ready",
    "publish",
    "record_dependency_change",
    "record_mutation",
    "run_build",
    "spec_for",
    "status_snapshot",
]
