"""Deterministic critique of a performed session.

Layering: above `rules`, `prescribe` and `store`; below `agents`/`eval`. Nothing here calls a
model: the rubric computes, and an LLM may later narrate the result without changing a score.
"""

from strength_coach.critique.facts import CritiqueFacts, UnknownSessionError, build_facts
from strength_coach.critique.rubric import Critique, RubricItem, persist, score_session

__all__ = [
    "Critique",
    "CritiqueFacts",
    "RubricItem",
    "UnknownSessionError",
    "build_facts",
    "persist",
    "score_session",
]
