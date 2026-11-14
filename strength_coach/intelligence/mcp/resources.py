"""The three approved MCP resources: profile, current programme and current overview.

Each is a compact envelope over the same read-only services, guarded by the same timeout, size
limit and audit record as a tool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ResourceError

from strength_coach.intelligence import audit, resources
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import Envelope
from strength_coach.intelligence.mcp.db import readonly_connection
from strength_coach.intelligence.mcp.security import current_principal
from strength_coach.intelligence.mcp.tools import rows_considered

PROFILE_URI = resources.RESOURCE_URI
PROGRAMME_URI = resources.PROGRAMME_URI
OVERVIEW_URI = resources.OVERVIEW_URI

Builder = Callable[[Path, IntelligenceConfig], Envelope]


def _profile(db_path: Path, config: IntelligenceConfig) -> Envelope:
    with readonly_connection(db_path) as conn:
        return resources.athlete_profile(conn, config=config)


def _programme(db_path: Path, config: IntelligenceConfig) -> Envelope:
    with readonly_connection(db_path) as conn:
        return resources.programme_current(conn, config=config)


def _overview(db_path: Path, config: IntelligenceConfig) -> Envelope:
    with readonly_connection(db_path) as conn:
        return resources.overview_current(conn, config=config)


def _register(server: Any, *, uri: str, name: str, description: str,
              db_path: Path, config: IntelligenceConfig, builder: Builder) -> None:
    @server.resource(uri, name=name, description=description, mime_type="application/json")
    async def handler() -> str:
        principal = current_principal()
        with audit.audit_call(
            kind="resource", name=uri, client_id=principal.identity, arguments={}
        ) as call:
            try:
                envelope = await asyncio.wait_for(
                    asyncio.to_thread(builder, db_path, config),
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


def register_resources(
    server: Any, *, db_path: Path, config: IntelligenceConfig
) -> None:
    _register(
        server,
        uri=PROFILE_URI,
        name="athlete_profile",
        description=(
            "Compact read-only training profile: sessions-per-week target, session cap, block "
            "start, volume budget and main-lift policy, plus non-injury structured constraints. "
            "Goal fields are retired and not returned; injury constraints, symptoms, measurements "
            "and notes are withheld."
        ),
        db_path=db_path,
        config=config,
        builder=_profile,
    )
    _register(
        server,
        uri=PROGRAMME_URI,
        name="programme_current",
        description=(
            "Compact current-programme context: settings profile and volume budget, deload state, "
            "a regime-finding count and any active declared break. Use the programme tool for the "
            "finding detail. No stored block exists."
        ),
        db_path=db_path,
        config=config,
        builder=_programme,
    )
    _register(
        server,
        uri=OVERVIEW_URI,
        name="overview_current",
        description=(
            "Compact four-week training overview: attendance, S/RPE coverage, performance ratio, "
            "volume, readiness coverage and deload state. Use the overview tool for an explicit "
            "window."
        ),
        db_path=db_path,
        config=config,
        builder=_overview,
    )
