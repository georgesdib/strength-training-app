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
        self.prompt = prompt
        return LLMResponse(
            text=(
                "Two sessions this week.\n\nSuggestions (not applied):\n"
                "- Consider a lighter hinge next week.\n- Keep the bench slot."
            ),
            model=self.model,
            tokens=15,
        )


def test_chat_uses_the_capability_tool_then_answers():
    store = seed_store()
    try:
        client = FakeToolClient()
        result = run_chat(service(store.connection), client, [{"role": "user", "content": "What changed?"}])
        assert result.answer == "Two sessions this week."
        assert result.suggestions == [
            "Consider a lighter hinge next week.",
            "Keep the bench slot.",
        ]
        assert "get_weekly_review" in result.tools
        assert result.tokens == 15
        assert client.calls == 1
        assert result.raw["model"] == "fake-chat"
        assert result.raw["request"]["messages"][0]["role"] == "system"
        assert "What changed?" in result.raw["request"]["messages"][-1]["content"]
        assert result.raw["response"]["choices"][0]["message"]["content"].startswith(
            "Two sessions this week."
        )
    finally:
        store.close()


def test_chat_trims_history_to_the_recent_window():
    store = seed_store()
    try:
        client = FakeToolClient()
        messages = []
        for index in range(12):
            messages.append({"role": "user", "content": f"turn {index}"})
            messages.append({"role": "assistant", "content": "ack"})
        run_chat(service(store.connection), client, messages)
        assert "turn 0" not in client.prompt
        assert "turn 11" in client.prompt
    finally:
        store.close()


class DurationClient:
    model = "duration"

    def complete(self, prompt, *, system=None):
        self.prompt = prompt
        return LLMResponse(text="That session took 52.5 min.", model=self.model, tokens=3)


def test_latest_session_duration_is_in_the_dossier_and_grounded():
    store = seed_store()
    try:
        store.connection.execute(
            "INSERT INTO session (session_id, occurred_on, set_count, exercise_count, duration_min) "
            "VALUES ('s-duration', '2026-11-10', 1, 1, 52.5)"
        )
        client = DurationClient()
        result = run_chat(service(store.connection), client, [{"role": "user", "content": "How long?"}])
        assert "latest_session_duration" in result.tools
        assert "52.5" in client.prompt
        assert result.warnings == []
        assert result.answer == "That session took 52.5 min."
    finally:
        store.close()
