"""Registered capabilities.

Importing this package registers every shipped capability with the process-wide registry. The
import is deliberate and tiny: no discovery, no filesystem scanning, no entry points.
"""

from __future__ import annotations

from strength_coach.intelligence.capabilities import (
    adherence,
    compare,
    overview,
    prescription,
    programme,
    progression,
    readiness,
    session,
    vbt,
    weekly,
)

__all__ = [
    "adherence",
    "compare",
    "overview",
    "prescription",
    "programme",
    "progression",
    "readiness",
    "session",
    "vbt",
    "weekly",
]
