"""Server chat: multi-turn over a fresh read-only capability dossier.

The first slice does not use model tool calling (the configured provider stalled on it). Each turn
supplies a compact dossier and the model answers from it; no number is computed and no artifact is
written.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from strength_coach.intelligence.auth import INTERNAL_PRINCIPAL
from strength_coach.intelligence.model.narrative import narrative_facts, number_warnings
from strength_coach.intelligence.service import IntelligenceService


class ChatClient(Protocol):
    """The one model call this module needs. Injected by the caller so the intelligence package
    does not import the agents/model layer (ADR-INT-002's boundary)."""

    def complete(self, prompt: str, **kwargs: Any) -> Any: ...


SYSTEM_PROMPT = (
    "You are a training assistant. Answer only from the supplied training facts. Never invent a "
    "number, prescribe a load or plan, or give medical advice. You may suggest changes only after "
    "an empty line headed exactly 'Suggestions (not applied):' followed by bullet lines; they are "
    "proposals and are never applied. Keep answers under 200 words."
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
            "get_adherence_analysis (weeks or from/to), compare_training_periods, get_vbt_analysis, "
            "get_longevity_assessment (as_of, include_time_in_zone, include_patterns) for aerobic "
            "activity, VO2max and per-pattern volume headroom."
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
    suggestions: list[str] = field(default_factory=list)


def run_chat(
    service: IntelligenceService,
    client: ChatClient,
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
        ("get_prescription", {}),
        ("get_readiness_history", {"from": start, "to": today.isoformat(), "fields": ["score"]}),
        ("get_adherence_analysis", {"weeks": 12}),
        ("get_programme_block_summary", {}),
        ("get_longevity_assessment", {}),
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
    from strength_coach.features import programme as programme_feature

    blocks.append(
        {
            "capability": "programme_header",
            "status": "ok",
            "data": programme_feature.header(service.connection, today.isoformat()),
        }
    )
    latest = service.connection.execute(
        "SELECT occurred_on, duration_min FROM session "
        "WHERE voided = 0 AND duration_min IS NOT NULL "
        "ORDER BY occurred_on DESC, created_at DESC LIMIT 1"
    ).fetchone()
    if latest is not None:
        blocks.append(
            {
                "capability": "latest_session_duration",
                "status": "ok",
                "data": {
                    "occurred_on": latest["occurred_on"],
                    "duration_min": latest["duration_min"],
                },
            }
        )
        tools.append("latest_session_duration")
    duration_numbers = () if latest is None else (str(latest["duration_min"]),)
    truncated = False
    while len(json.dumps(blocks, ensure_ascii=False, default=str)) > 18_000 and len(blocks) > 1:
        blocks.pop()
        truncated = True
    if truncated:
        blocks.append({"note": "dossier truncated; ask about a narrower window for more detail"})
    facts = json.dumps(blocks, ensure_ascii=False, default=str)
    history = "\n".join(
        f"{message['role']}: {message['content']}" for message in messages[-10:]
    )
    prompt = (
        "Answer the latest athlete message using only these facts. If the facts do not cover it, "
        "say so. Label any change proposal as 'Suggestions (not applied)'.\n\n"
        + "CONVERSATION:\n" + history + "\n\nFACTS:\n" + facts
    )
    response = client.complete(prompt, system=SYSTEM_PROMPT)
    answer, suggestions = _split_suggestions(response.text)
    return ChatResult(
        answer,
        response.tokens,
        tools,
        number_warnings(answer, envelopes, duration_numbers),
        suggestions,
    )


def _split_suggestions(text: str) -> tuple[str, list[str]]:
    match = re.search(
        r"(?im)^\s*(?:\*\*)?Suggestions \(not applied\)(?:\*\*)?\s*:?\s*$", text
    )
    if match is None:
        return text.strip(), []
    answer = text[: match.start()].strip()
    items = []
    for line in text[match.end() :].splitlines():
        item = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if item:
            items.append(item)
    return answer, items[:6]
