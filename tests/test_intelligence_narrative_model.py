"""INT-5 narrative: prompt, grounding and failure containment."""

from __future__ import annotations

import json

import pytest

from strength_coach.agents.client import LLMResponse
from strength_coach.intelligence.model import NarrativeValidationError, narrate_envelope


class FakeEnvelope:
    def __init__(self, facts, status="ok"):
        self._payload = {
            "capability": "get_weekly_review",
            "status": status,
            "period": {"start": "2026-11-02", "end": "2026-11-08"},
            "facts": facts,
            "missing": [],
            "limitations": ["Descriptive only."],
            "evidence": [{"id": "ev:1"}],
        }

    def as_dict(self):
        return self._payload


class FakeClient:
    model = "fake-model"

    def __init__(self, text):
        self.text = text
        self.prompts = []

    @property
    def available(self):
        return True

    def complete(self, prompt, *, system=None):
        self.prompts.append(prompt)
        return LLMResponse(text=self.text, model=self.model, tokens=12)


def _answer(headline, observations=("Two sessions completed.",)):
    return json.dumps(
        {"headline": headline, "observations": list(observations), "limitations": []}
    )


def test_grounded_narrative_is_accepted():
    envelope = FakeEnvelope(
        {"activity": {"value": {"completed_sessions": 2, "target_sessions": 3}}}
    )
    client = FakeClient(_answer("Two of three sessions"))
    narrative = narrate_envelope(client, envelope)
    assert narrative.headline == "Two of three sessions"
    assert narrative.tokens == 12
    assert "FACTS" in client.prompts[0]


def test_invented_number_is_a_warning():
    envelope = FakeEnvelope(
        {"activity": {"value": {"completed_sessions": 2, "target_sessions": 3}}}
    )
    client = FakeClient(_answer("9 of three sessions"))
    narrative = narrate_envelope(client, envelope)
    assert narrative.warnings == ("number '9' is not in the facts",)


def test_signed_fact_grounds_the_unsigned_number():
    envelope = FakeEnvelope({"progression": {"value": -5.3}})
    client = FakeClient(_answer("The trend was 5.3 kg."))
    narrative = narrate_envelope(client, envelope)
    assert narrative.headline == "The trend was 5.3 kg."


def test_many_limitations_are_accepted():
    envelope = FakeEnvelope({"activity": {"value": {"completed_sessions": 2}}})
    client = FakeClient(
        json.dumps(
            {
                "headline": "Two sessions",
                "observations": ["Two sessions."],
                "limitations": ["One.", "Two.", "Three.", "Four."],
            }
        )
    )
    narrative = narrate_envelope(client, envelope)
    assert len(narrative.limitations) == 4


def test_non_json_is_rejected():
    client = FakeClient("I think you did well.")
    with pytest.raises(NarrativeValidationError, match="not JSON"):
        narrate_envelope(client, FakeEnvelope({"activity": {"value": 2}}))


def test_unknown_fields_are_rejected():
    client = FakeClient(
        json.dumps(
            {
                "headline": "Two sessions",
                "observations": ["Two sessions."],
                "limitations": [],
                "prescription": "change it",
            }
        )
    )
    with pytest.raises(NarrativeValidationError, match="unknown fields"):
        narrate_envelope(client, FakeEnvelope({"activity": {"value": 2}}))


def test_null_client_is_unavailable():
    class Null:
        model = "null"

        @property
        def available(self):
            return False

        def complete(self, prompt, *, system=None):
            raise AssertionError("must not be called")

    with pytest.raises(Exception, match="no model"):
        narrate_envelope(Null(), FakeEnvelope({"activity": {"value": 2}}))
