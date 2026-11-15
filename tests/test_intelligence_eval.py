"""End-to-end narration harness: all capabilities through the real validator."""

from __future__ import annotations

import json

from intelligence_support import seed_store, service

from strength_coach.agents.client import LLMResponse
from strength_coach.intelligence.model.eval import CASES, run_eval


class FakeClient:
    model = "eval-fake"

    @property
    def available(self):
        return True

    def complete(self, prompt, *, system=None):
        return LLMResponse(
            text=json.dumps(
                {
                    "headline": "Descriptive capability summary",
                    "observations": ["The deterministic capability returned data."],
                    "limitations": [],
                }
            ),
            model=self.model,
            tokens=5,
        )


def test_every_capability_passes_the_harness():
    store = seed_store()
    try:
        results = run_eval(service(store.connection), FakeClient())
        assert len(results) == len(CASES) == 10
        assert all(result.ok for result in results), [
            (result.capability, result.detail) for result in results if not result.ok
        ]
        assert all(
            result.status in {"ok", "no_data", "insufficient", "expected_error"}
            for result in results
        )
    finally:
        store.close()
