"""The single approved MCP resource: strength://athlete/profile."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ResourceError

from strength_coach.intelligence import audit, resources
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.mcp.db import readonly_connection
from strength_coach.intelligence.mcp.security import current_principal
from strength_coach.intelligence.mcp.tools import rows_considered

PROFILE_URI = resources.RESOURCE_URI


def _profile_envelope(db_path: Path, config: IntelligenceConfig):
    with readonly_connection(db_path) as conn:
        return resources.athlete_profile(conn, config=config)


def register_resources(
    server: Any, *, db_path: Path, config: IntelligenceConfig
) -> None:
    @server.resource(
        PROFILE_URI,
        name="athlete_profile",
        description=(
            "Compact read-only training profile: sessions-per-week target, session cap, block "
            "start, volume budget and main-lift policy, plus non-injury structured constraints. "
            "Goal fields are retired and not returned; injury constraints, symptoms, measurements "
            "and notes are withheld."
        ),
        mime_type="application/json",
    )
    async def athlete_profile() -> str:
        principal = current_principal()
        with audit.audit_call(
            kind="resource",
            name=PROFILE_URI,
            client_id=principal.identity,
            arguments={},
        ) as call:
            try:
                envelope = await asyncio.wait_for(
                    asyncio.to_thread(_profile_envelope, db_path, config),
                    timeout=config.tool_timeout_seconds,
                )
            except TimeoutError:
                raise ResourceError(
                    "resource_timeout: resource exceeded the configured timeout"
                ) from None
            body = envelope.canonical_json()
            if len(body.encode("utf-8")) > config.max_tool_result_bytes:
                raise ResourceError(
                    "result_too_large: resource exceeds the configured maximum"
                )
            call.record(
                envelope.as_dict(),
                status=envelope.status,
                result_rows=rows_considered(envelope),
            )
            return body
