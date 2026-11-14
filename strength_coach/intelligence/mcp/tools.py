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

from strength_coach.intelligence import IntelligenceService, audit, latency
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
ROW_KEYS = (
    "completed_sessions",
    "sets_considered",
    "constraints_included",
    "observations",
    "workouts",
    "target_sets",
    "items",
    "prescribed_sets",
    "observed_days",
    "score_days",
    "sessions_considered",
)


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
            + latency.description("get_training_overview")
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
            + latency.description("get_session_details")
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

    @server.tool(
        name="get_exercise_progression",
        description=(
            "Read-only e1RM progression for one canonical exercise over 28-365 days ending on a "
            "training date: raw observations, a 3-point rolling median, series breaks and the "
            "owner's descriptive summary. Optionally returns the most recent sessions. A calculated "
            "e1RM is not a tested maximum, and breaks are reported rather than smoothed."
            + latency.description("get_exercise_progression")
        ),
        annotations=READ_ONLY,
    )
    async def get_exercise_progression(
        exercise_id: str,
        as_of: str | None = None,
        window_days: int = 84,
        include_sessions: bool = False,
        limit_sessions: int = 5,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {
            "exercise_id": exercise_id,
            "window_days": window_days,
            "include_sessions": include_sessions,
            "limit_sessions": limit_sessions,
        }
        if as_of is not None:
            payload["as_of"] = as_of
        return await _run(
            db_path, config, "get_exercise_progression", payload,
            principal=current_principal(),
        )

    @server.tool(
        name="get_readiness_history",
        description=(
            "Read-only readiness history for an inclusive date window of at most 366 days. By "
            "default returns the owner's readiness score per observed day; raw fields (sleep, "
            "energy, mood, stress, soreness and the measured fields) are returned only when named. "
            "Missing days are reported, never filled. Score series are limited to the most recent "
            "120 observed days."
            + latency.description("get_readiness_history")
        ),
        annotations=READ_ONLY,
    )
    async def get_readiness_history(
        start: str,
        end: str,
        fields: list[str] | None = None,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {"from": start, "to": end}
        if fields is not None:
            payload["fields"] = fields
        return await _run(
            db_path, config, "get_readiness_history", payload,
            principal=current_principal(),
        )

    @server.tool(
        name="get_adherence_analysis",
        description=(
            "Read-only prescription-adherence analysis over app-tracked completed workouts. Supply "
            "either weeks (1-52, default 8) or start and end; group_by is week or month. Returns "
            "totals, periods, per-exercise comparison, coverage and at most 20 workout entries. "
            "Imported sessions and the block dimension are unavailable by design."
            + latency.description("get_adherence_analysis")
        ),
        annotations=READ_ONLY,
    )
    async def get_adherence_analysis(
        weeks: int | None = None,
        as_of: str | None = None,
        start: str | None = None,
        end: str | None = None,
        group_by: str = "week",
        exercise_id: str | None = None,
        session_type: str | None = None,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {"group_by": group_by}
        if start is not None:
            payload["from"] = start
        if end is not None:
            payload["to"] = end
        if weeks is not None:
            payload["weeks"] = weeks
        if as_of is not None:
            payload["as_of"] = as_of
        if exercise_id is not None:
            payload["exercise_id"] = exercise_id
        if session_type is not None:
            payload["session_type"] = session_type
        return await _run(
            db_path, config, "get_adherence_analysis", payload,
            principal=current_principal(),
        )

    @server.tool(
        name="get_prescription",
        description=(
            "Read-only persisted prescription: header, items, recorded modifiers and rule refs. "
            "Supply at most one of prescription_id or for_date; neither returns the newest. A "
            "persisted artifact is not a forecast, and an unstarted issued plan is only a preview."
            + latency.description("get_prescription")
        ),
        annotations=READ_ONLY,
    )
    async def get_prescription(
        prescription_id: str | None = None,
        for_date: str | None = None,
        include_provenance: bool = True,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {"include_provenance": include_provenance}
        if prescription_id is not None:
            payload["prescription_id"] = prescription_id
        if for_date is not None:
            payload["for_date"] = for_date
        return await _run(
            db_path, config, "get_prescription", payload,
            principal=current_principal(),
        )

    @server.tool(
        name="get_vbt_analysis",
        description=(
            "Read-only longitudinal velocity-based training analysis for 28-365 days: cohort gates, "
            "weekly residuals, within-set drift and every abstention reason. VBT is sparse, so an "
            "insufficient cohort is a normal answer; no estimate is invented and per-set rows are "
            "summarised rather than returned."
            + latency.description("get_vbt_analysis")
        ),
        annotations=READ_ONLY,
    )
    async def get_vbt_analysis(
        start: str,
        end: str,
        exercise_id: str | None = None,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {"from": start, "to": end}
        if exercise_id is not None:
            payload["exercise_id"] = exercise_id
        return await _run(
            db_path, config, "get_vbt_analysis", payload,
            principal=current_principal(),
        )

    @server.tool(
        name="get_programme_block_summary",
        description=(
            "Read-only summary of a derived 4, 6 or 8 week reporting window ending on a training "
            "date: settings and volume budget, deload state, regime findings, declared breaks and "
            "target-based attendance. No stored training block and no planned-session calendar "
            "exist, so this is a reporting window, not a block entity."
            + latency.description("get_programme_block_summary")
        ),
        annotations=READ_ONLY,
    )
    async def get_programme_block_summary(
        as_of: str | None = None,
        block_weeks: int = 4,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {"block_weeks": block_weeks}
        if as_of is not None:
            payload["as_of"] = as_of
        return await _run(
            db_path, config, "get_programme_block_summary", payload,
            principal=current_principal(),
        )

    @server.tool(
        name="compare_training_periods",
        description=(
            "Read-only comparison of two date windows for one metric: attendance, adherence, weekly "
            "volume, or an exercise's strength direction (exercise_id required only for the last). "
            "Each side comes from its owner; the delta is arithmetic between the two values. Two "
            "windows over one athlete are descriptive, not a treatment effect."
            + latency.description("compare_training_periods")
        ),
        annotations=READ_ONLY,
    )
    async def compare_training_periods(
        period_a: dict[str, str],
        period_b: dict[str, str],
        metric: str,
        exercise_id: str | None = None,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {
            "period_a": period_a,
            "period_b": period_b,
            "metric": metric,
        }
        if exercise_id is not None:
            payload["exercise_id"] = exercise_id
        return await _run(
            db_path, config, "compare_training_periods", payload,
            principal=current_principal(),
        )

    @server.tool(
        name="get_weekly_review",
        description=(
            "Deterministic Monday-Sunday review for a completed week: activity and attendance, "
            "prescription adherence, completed sessions, main-lift progression, volume against "
            "budget, readiness coverage and direction, programme state and at most two gated "
            "observations. Every section names its owner; no narrative and no model. An empty week "
            "returns no_data with the expected inputs listed, never zeros."
            + latency.description("get_weekly_review")
        ),
        annotations=READ_ONLY,
    )
    async def get_weekly_review(
        week_end: str | None = None,
        include_observations: bool = True,
    ) -> EnvelopePayload:
        payload: dict[str, object] = {"include_observations": include_observations}
        if week_end is not None:
            payload["week_end"] = week_end
        return await _run(
            db_path, config, "get_weekly_review", payload,
            principal=current_principal(),
        )
