"""Server chat: generic capability tool loop."""

from __future__ import annotations

import json

from intelligence_support import seed_store, service

from strength_coach.intelligence.model.chat import run_chat


class FakeToolClient:
    model = "fake-chat"

    def __init__(self):
        self.calls = 0

    def complete_with_tools(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "training_data",
                            "arguments": json.dumps(
                                {"name": "get_weekly_review", "payload": {}}
                            ),
                        },
                    }
                ],
                "tokens": 10,
            }
        return {"content": "Two sessions this week.", "tool_calls": [], "tokens": 5}


def test_chat_uses_the_capability_tool_then_answers():
    store = seed_store()
    try:
        client = FakeToolClient()
        result = run_chat(service(store.connection), client, [{"role": "user", "content": "What changed?"}])
        assert result.answer == "Two sessions this week."
        assert result.tools == ["get_weekly_review"]
        assert result.tokens == 15
        assert client.calls == 2
    finally:
        store.close()
