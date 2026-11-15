"""Server chat: generic capability tool loop."""

from __future__ import annotations

from intelligence_support import seed_store, service

from strength_coach.agents.client import LLMResponse
from strength_coach.intelligence.model.chat import run_chat


class FakeToolClient:
    model = "fake-chat"

    def __init__(self):
        self.calls = 0

    def complete(self, prompt, *, system=None):
        self.calls += 1
        return LLMResponse(text="Two sessions this week.", model=self.model, tokens=15)


def test_chat_uses_the_capability_tool_then_answers():
    store = seed_store()
    try:
        client = FakeToolClient()
        result = run_chat(service(store.connection), client, [{"role": "user", "content": "What changed?"}])
        assert result.answer == "Two sessions this week."
        assert "get_weekly_review" in result.tools
        assert result.tokens == 15
        assert client.calls == 1
    finally:
        store.close()
