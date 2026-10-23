"""Narrative: facts in, prose out. The model never supplies a number.

Every numeric fact is already decided; the prompt hands it over as JSON and asks for an
explanation. The response is recorded as a `run_event`, not written into a prescription or a
score, so a model cannot silently change an artifact -- at worst it produces bad prose.

Failure is contained on purpose: a raising client yields `None` plus an error event, and the
deterministic run carries on. That is the "the system still emits a safe prescription" claim.
"""

from __future__ import annotations

import json
from typing import Any

from strength_coach.agents.client import LLMClient, LLMError

SYSTEM_PROMPT = (
    "You are a strength coach explaining a decision that a deterministic engine has already "
    "made. Do not calculate, estimate, round or invent any number: every number you mention "
    "must appear verbatim in the facts you are given. Do not propose a different load or "
    "session. Refer to rules by their id (for example PRG-RIR-001) only when they appear in "
    "the facts. Be concise: at most 120 words, plain prose, no markdown."
)


def critique_prompt(critique, facts) -> str:
    payload = {
        "session": facts.session_id,
        "date": facts.occurred_on,
        "session_type": facts.session_type,
        "composite": critique.composite,
        "items": [
            {
                "item": item.key,
                "score": item.score,
                "measurable": item.measurable,
                "detail": item.detail,
                "rules": list(item.rule_ids),
                "evidence": list(item.evidence_refs),
            }
            for item in critique.items
        ],
    }
    return (
        "Explain this training-session critique to the athlete: what went well, what to "
        "change next session, and which rule ids justify it. Unmeasurable items must be "
        "described as not measurable, never as a zero score.\n\nFACTS:\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
    )


def prescription_prompt(prescription) -> str:
    payload = {
        "for_date": prescription.for_date,
        "session_type": prescription.session_type,
        "fallback_level": prescription.fallback_level,
        "items": [
            {
                "exercise": item.exercise_id,
                "sets": item.sets,
                "reps_low": item.reps_low,
                "reps_high": item.reps_high,
                "load_kg": item.load_kg,
                "rir_target": item.rir_target,
                "rest_s": item.rest_s,
                "essential": item.essential,
                "refs": list(item.rationale_refs),
            }
            for item in prescription.items
        ],
        "warnings": list(prescription.warnings),
    }
    return (
        "Explain this session prescription to the athlete: why these lifts and loads, and "
        "what to pay attention to. Do not change any number.\n\nFACTS:\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
    )


def narrate(
    client: LLMClient,
    prompt: str,
    trace,
    *,
    system: str = SYSTEM_PROMPT,
) -> str | None:
    """Ask for prose; never let a failure escape."""
    if not client.available:
        # NullLLM: no event at all, so a run with the model off has a different event count
        # but an identical set of artifacts (V0-SCOPE §4 criterion 5).
        return None
    try:
        response = client.complete(prompt, system=system)
    except LLMError as exc:
        trace.event(
            "llm_output",
            {"model": client.model, "status": "error", "error": str(exc)},
        )
        return None

    trace.event(
        "llm_output",
        {
            "model": response.model,
            "status": "ok",
            "text": response.text,
            "tokens": response.tokens,
        },
    )
    if response.tokens:
        trace.add_tokens(response.tokens)
    return response.text


def explain_critique(client: LLMClient, critique, facts, trace) -> str | None:
    return narrate(client, critique_prompt(critique, facts), trace)


def explain_prescription(client: LLMClient, prescription, trace) -> str | None:
    return narrate(client, prescription_prompt(prescription), trace)


def summarize(settings: Any) -> str:
    """One line for logs: provider and model, never the key."""
    if not getattr(settings, "enabled", False):
        return "llm: off (NullLLM)"
    return f"llm: {settings.provider} / {settings.model}"
