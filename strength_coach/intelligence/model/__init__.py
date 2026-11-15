"""Server-side narrative layer (INT-5).

The model explains envelopes that the deterministic capabilities produced. It never computes a
number and never writes an artifact; the CLI records the result as a run event.
"""

from strength_coach.intelligence.model.chat import ChatResult, run_chat
from strength_coach.intelligence.model.narrative import (
    Narrative,
    NarrativeBudgetError,
    NarrativeValidationError,
    daily_tokens_used,
    ensure_daily_budget,
    narrate_envelope,
    narrative_facts,
)

__all__ = [
    "ChatResult",
    "run_chat",
    "Narrative",
    "NarrativeBudgetError",
    "NarrativeValidationError",
    "daily_tokens_used",
    "ensure_daily_budget",
    "narrate_envelope",
    "narrative_facts",
]
