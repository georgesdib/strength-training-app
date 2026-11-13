"""Historical critique facts.

The deterministic rubric that scored a session is retired (`DEC-EVAL-09`): nothing computes or
persists a critique any more. This package keeps the fact projection because the read-only
historical review sheet and the resolver tests still read it.
"""

from strength_coach.critique.facts import CritiqueFacts, UnknownSessionError, build_facts

__all__ = [
    "CritiqueFacts",
    "UnknownSessionError",
    "build_facts",
]
