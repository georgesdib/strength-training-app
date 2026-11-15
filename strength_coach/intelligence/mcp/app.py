"""Build the MCP server and the guarded ASGI application."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

import strength_coach
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.mcp.resources import register_resources
from strength_coach.intelligence.mcp.security import BearerAuthMiddleware, LimitMiddleware
from strength_coach.intelligence.mcp.tools import register_tools
from strength_coach.intelligence.mcp.validation import StrictToolArgumentsMiddleware
from strength_coach.intelligence.tokens import TokenStore

SERVER_NAME = "strength-intelligence"

INSTRUCTIONS = (
    "Read-only strength-training intelligence for one athlete. Every tool returns a versioned "
    "envelope with explicit status, coverage, missing data and limitations; reported metrics are "
    "computed by the deterministic backend and never by a model. No tool can change a "
    "prescription, workout, readiness score or any other stored state."
)


def build_server(*, db_path: Path, config: IntelligenceConfig) -> MCPServer:
    server = MCPServer(
        name=SERVER_NAME,
        title="Strength Intelligence",
        version=strength_coach.__version__,
        instructions=INSTRUCTIONS,
        middleware=[StrictToolArgumentsMiddleware()],
    )
    register_tools(server, db_path=db_path, config=config)
    register_resources(server, db_path=db_path, config=config)
    return server


def build_app(
    *, db_path: Path, config: IntelligenceConfig, store: TokenStore
) -> Any:
    """Return the ASGI app: bearer auth outermost, then limits, then the MCP app.

    Authentication therefore runs before any capability, and before the MCP layer parses a
    request. The SDK keeps DNS-rebinding protection on and enforces the body-size cap.
    """
    server = build_server(db_path=db_path, config=config)
    mcp_app = server.streamable_http_app(
        streamable_http_path=config.endpoint_path,
        json_response=True,
        max_request_body_size=config.max_request_body_bytes,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(config.allowed_hosts),
            allowed_origins=[],
        ),
        host=config.bind_host,
    )
    limited = LimitMiddleware(
        mcp_app,
        per_minute=config.rate_limit_per_minute,
        max_concurrent=config.max_concurrent_calls,
    )
    return BearerAuthMiddleware(limited, store=store)
