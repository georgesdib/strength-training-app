"""The LLM layer: interface, configuration, and narrative only.

Layering: the top of the stack, above `critique` and `prescribe`. It may read their outputs and
call a model; it may never compute a number or veto a rule (AGENTS.md §3.2-3.3).

`NullLLM` is the default and must keep the system fully functional: that is the property the
architecture is built on, not an optimisation.
"""

from strength_coach.agents.client import (
    LLMClient,
    LLMError,
    LLMResponse,
    LLMUnavailable,
    NullLLM,
    OpenAICompatibleClient,
)
from strength_coach.agents.config import (
    LLMConfigError,
    LLMSettings,
    build_client,
    describe,
    load_settings,
)
from strength_coach.agents.narrative import (
    explain_critique,
    explain_prescription,
    narrate,
)

__all__ = [
    "LLMClient",
    "LLMConfigError",
    "LLMError",
    "LLMResponse",
    "LLMSettings",
    "LLMUnavailable",
    "NullLLM",
    "OpenAICompatibleClient",
    "build_client",
    "describe",
    "explain_critique",
    "explain_prescription",
    "load_settings",
    "narrate",
]
