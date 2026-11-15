"""Server chat: multi-turn over the read-only capability catalogue.

One generic tool lets the model choose a capability and its payload. The model never computes a
number or writes an artifact; tool results are envelopes and the answer is advisory text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from strength_coach.agents.client import LLMClient, LLMError
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
    if not hasattr(client, "complete_with_tools"):
        raise LLMError("the configured model does not support tool calling")
    conversation = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    tokens = 0
    tools: list[str] = []
    envelopes = []
    for _ in range(max_rounds + 1):
        response = client.complete_with_tools(conversation, [CAPABILITY_TOOL])
        tokens += int(response.get("tokens") or 0)
        content = str(response.get("content") or "").strip()
        calls = response.get("tool_calls") or []
        if not calls:
            return ChatResult(
                content, tokens or None, tools, number_warnings(content, envelopes)
            )
        conversation.append(
            {"role": "assistant", "content": content or None, "tool_calls": calls}
        )
        for call in calls:
            function = call.get("function") or {}
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            capability = str(args.get("name") or "")
            payload = args.get("payload") or {}
            result = service.execute(INTERNAL_PRINCIPAL, capability, payload)
            tools.append(capability)
            if result.ok:
                envelope = result.envelope
                body = {
                    "status": envelope.status,
                    "data": narrative_facts(envelope),
                }
                envelopes.append(envelope)
            else:
                body = {"error": result.error.code, "message": result.error.message}
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call.get("id") or ""),
                    "content": json.dumps(body, ensure_ascii=False, default=str),
                }
            )
    return ChatResult(
        "I stopped after the tool-call limit without a final answer.",
        tokens or None,
        tools,
        [],
    )
