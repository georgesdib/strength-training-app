"""LLM chooser for the exercise-selection shadow.

The model receives only the already-filtered candidates and may only return one of their ids.
It does not see or supply a load, rep count, RIR or veto. Python validates the answer and
falls back to the deterministic choice on any error.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from strength_coach.agents.client import LLMClient, LLMError
from strength_coach.prescribe import selection as selection_mod
from strength_coach.prescribe import templates


def chooser(client: LLMClient) -> Callable:
    def choose(slot: templates.Slot, candidates: tuple[selection_mod.Candidate, ...]):
        lines = "\n".join(
            f"- {c.exercise_id}: score {c.score:.3f}; {', '.join(c.reasons)}"
            for c in candidates
        )
        prompt = (
            f"Slot {slot.id} has these allowed exercise variants:\n{lines}\n\n"
            "Choose one exercise_id from this list only. Return JSON exactly as "
            '{"exercise_id": "<id>", "reason": "<one sentence>"}.\n'
            "Do not invent an exercise, a load, reps, RIR or a safety veto."
        )
        response = client.complete(
            prompt,
            system="You are choosing between pre-approved exercise variants. Return JSON only.",
        )
        text = response.text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise LLMError("selection response was not JSON")
        try:
            payload = json.loads(match.group(0))
            exercise_id = str(payload["exercise_id"])
            reason = str(payload.get("reason") or "model choice")
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError(f"invalid selection response: {exc}") from exc
        return exercise_id, reason

    return choose
