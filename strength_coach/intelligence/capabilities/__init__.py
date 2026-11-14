"""Registered capabilities.

Importing this package registers every shipped capability with the process-wide registry. The
import is deliberate and tiny: no discovery, no filesystem scanning, no entry points.
"""

from __future__ import annotations

from strength_coach.intelligence.capabilities import overview

__all__ = ["overview"]
