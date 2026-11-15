"""Server chat: multi-turn over the read-only capability catalogue.

One generic tool lets the model choose a capability and its payload. The model never computes a
number or writes an artifact; tool results are envelopes and the answer is advisory text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from strength_coach.agents.client import LLMClient
from strength_coach.intelligence.auth import INTERNAL_PRINCIPAL
from strength_coach.intelligence.model.narrative import narrative_facts, number_warnings
from strength_coach.intelligence.service import IntelligenceService

SYSTEM_PROMPT = (
    "You are a training assistant. Answer only from facts returned by the training_data tool. "
    "Call the tool before making a data claim. Never invent a number, prescribe a load or plan, or "
    "give medical advice. You may suggest changes in a clearly labelled 'Suggestions (not applied)' "
    "section; they are proposals and are never applied. Keep answers under 200 words."
)

CAPABILITY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "training_data",
        "description": (
            "Read one capability. name is one of: get_weekly_review, get_training_overview, "
            "get_exercise_progression (exercise_id), get_readiness_history (from, to, fields), "
            "get_session_details (workout_id or session_id), get_prescription (for_date or "
            "prescription_id), get_programme_block_summary (as_of, block_weeks), "
            "get_adherence_analysis (weeks or from/to), compare_training_periods, get_vbt_analysis."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["name", "payload"],
        },
    },
}


@dataclass
class ChatResult:
    answer: str
    tokens: int | None
    tools: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_chat(
    service: IntelligenceService,
    client: LLMClient,
    messages: list[dict[str, Any]],
    *,
    max_rounds: int = 4,
) -> ChatResult:
    """Answer one conversational turn from a fresh read-only fact dossier.

    Tool calling is deliberately not used in the first server/web slice: some providers stall on
    it. Every capability is available as structured facts instead.
    """
    import datetime as dt

    today = dt.date.today()
    start = (today - dt.timedelta(days=6)).isoformat()
    cases = [
        ("get_weekly_review", {}),
        ("get_training_overview", {}),
        ("get_adherence_analysis", {"weeks": 12}),
        ("get_programme_block_summary", {}),
        ("get_prescription", {}),
        ("get_readiness_history", {"from": start, "to": today.isoformat(), "fields": ["score"]}),
    ]
    blocks = []
    envelopes = []
    tools = []
    for name, payload in cases:
        result = service.execute(INTERNAL_PRINCIPAL, name, payload)
        if not result.ok:
            continue
        envelope = result.envelope
        envelopes.append(envelope)
        tools.append(name)
        blocks.append(
            {"capability": name, "status": envelope.status, "data": narrative_facts(envelope)}
        )
    facts = json.dumps(blocks, ensure_ascii=False, default=str)
    history = "\n".join(
        f"{message['role']}: {message['content']}" for message in messages[-18:]
    )
    prompt = (
        "Answer the latest athlete message using only these facts. If the facts do not cover it, "
        "say so. Label any change proposal as 'Suggestions (not applied)'.\n\n"
        + "CONVERSATION:\n" + history + "\n\nFACTS:\n" + facts
    )
    response = client.complete(prompt, system=SYSTEM_PROMPT)
    return ChatResult(
        response.text,
        response.tokens,
        tools,
        number_warnings(response.text, envelopes),
    )
