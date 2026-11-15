"""Server-side narrative layer (INT-5).

The model explains envelopes that the deterministic capabilities produced. It never computes a
number and never writes an artifact; the CLI records the result as a run event.
"""

from strength_coach.intelligence.model.narrative import (
    Narrative,
    NarrativeValidationError,
    narrate_envelope,
    narrative_facts,
)

__all__ = ["Narrative", "NarrativeValidationError", "narrate_envelope", "narrative_facts"]
