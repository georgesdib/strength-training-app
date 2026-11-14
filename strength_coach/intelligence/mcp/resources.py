"""The single approved MCP resource: strength://athlete/profile."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from strength_coach.intelligence import resources
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.mcp.db import readonly_connection

PROFILE_URI = resources.RESOURCE_URI


def _profile_json(db_path: Path, config: IntelligenceConfig) -> str:
    with readonly_connection(db_path) as conn:
        envelope = resources.athlete_profile(conn, config=config)
    return envelope.canonical_json()


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
        return await asyncio.to_thread(_profile_json, db_path, config)
