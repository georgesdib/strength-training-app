"""MCP tools: thin adapters over the INT-1 capability service.

No analytics live here. Each handler maps a tool call to a capability, enforces the transport's
runtime limits (timeout, serialized size), emits exactly one structured audit record, and returns
the unchanged envelope as structured content. Expected failures become a ToolError the model can
read; internal failures never carry a traceback.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TypedDict

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from strength_coach.intelligence import IntelligenceService, audit
from strength_coach.intelligence.auth import Principal
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import Envelope
from strength_coach.intelligence.mcp.db import readonly_connection
from strength_coach.intelligence.mcp.security import current_principal

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

#: Coverage keys that describe how many rows the capability considered, in preference order.
ROW_KEYS = ("completed_sessions", "sets_considered", "constraints_included")


class EnvelopePayload(TypedDict):
    """The canonical envelope, as returned to an MCP client."""

    intelligence_version: str
    schema_version: str
    capability: str
    capability_version: str
    status: str
    as_of: str
    period: dict[str, Any]
    subject: dict[str, str]
    units: dict[str, str]
    facts: dict[str, Any]
    evidence: list[Any]
    observations: list[Any]
    coverage: dict[str, Any]
    missing: list[str]
    limitations: list[str]
    quality_flags: list[str]
    privacy: dict[str, Any]
    provenance: dict[str, Any]
    generated_at: str


def rows_considered(envelope: Envelope) -> int | None:
    for key in ROW_KEYS:
        value = envelope.coverage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _execute(
    db_path: Path,
    config: IntelligenceConfig,
    principal: Principal,
    capability: str,
    payload: dict[str, object],
) -> Envelope:
    with readonly_connection(db_path) as conn:
        result = IntelligenceService(conn, config=config).execute(
            principal, capability, payload
        )
    if not result.ok:
        assert result.error is not None
        raise ToolError(f"{result.error.code}: {result.error.message}")
    assert result.envelope is not None
    return result.envelope


async def _run(
    db_path: Path,
    config: IntelligenceConfig,
    capability: str,
    payload: dict[str, object],
    *,
    principal: Principal,
) -> EnvelopePayload:
    with audit.audit_call(
        kind="tool",
        name=capability,
        client_id=principal.identity,
        arguments=payload,
    ) as call:
        try:
            envelope = await asyncio.wait_for(
                asyncio.to_thread(_execute, db_path, config, principal, capability, payload),
                timeout=config.tool_timeout_seconds,
            )
        except TimeoutError:
            # The worker thread is not cancellable; it finishes its bounded read and its result is
            # discarded. The audit record and this error are the response guarantee.
            raise ToolError(
                "tool_timeout: capability exceeded the configured timeout"
            ) from None
        body = envelope.as_dict()
        size = len(envelope.canonical_json().encode("utf-8"))
        if size > config.max_tool_result_bytes:
            raise ToolError(
                "result_too_large: result exceeds the configured maximum; narrow the request"
            )
        call.record(body, status=envelope.status, result_rows=rows_considered(envelope))
        return body


def register_tools(
    server: Any, *, db_path: Path, config: IntelligenceConfig
) -> None:
    @server.tool(
        name="get_training_overview",
        description=(
            "Read-only overview over a window of 1-52 weeks ending on a training date: attendance "
            "against the sessions-per-week target, S/RPE coverage, a session e1RM performance "
            "ratio, per-pattern volume, readiness observed-day coverage and deload state. It "
            "computes nothing itself and never returns symptom, injury or note data. Missing data "
            "is reported as no_data or explicit missing entries, never as zero."
        ),
        annotations=READ_ONLY,
    )
    async def get_training_overview(
        as_of: str | None = None,
        window_weeks: int = 4,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {"window_weeks": window_weeks}
        if as_of is not None:
            payload["as_of"] = as_of
        return await _run(
            db_path,
            config,
            "get_training_overview",
            payload,
            principal=current_principal(),
        )

    @server.tool(
        name="get_session_details",
        description=(
            "Read-only detail for exactly one completed workout or imported session: strength, "
            "dose, prescription adherence, VBT status, effort/duration feedback and quality flags, "
            "with the evidence ids the owning services produced. Supply workout_id or session_id, "
            "not both. Free-text notes, symptoms and form ratings are excluded; imported sessions "
            "report adherence and VBT as unavailable rather than estimating them."
        ),
        annotations=READ_ONLY,
    )
    async def get_session_details(
        workout_id: str | None = None,
        session_id: str | None = None,
        include_ratios: bool = False,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {"include_ratios": include_ratios}
        if workout_id is not None:
            payload["workout_id"] = workout_id
        if session_id is not None:
            payload["session_id"] = session_id
        return await _run(
            db_path,
            config,
            "get_session_details",
            payload,
            principal=current_principal(),
        )
