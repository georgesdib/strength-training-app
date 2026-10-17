"""Domain layer: pure strength-training arithmetic.

No I/O, no pandas, no configuration loading. Everything here is a small function or
frozen dataclass that can be unit-tested in isolation and reused by features,
prescription, critique and the policy engine.
"""

from strength_coach.domain import e1rm, load

__all__ = ["e1rm", "load"]
