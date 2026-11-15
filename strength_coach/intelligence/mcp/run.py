"""Run the intelligence MCP server (Streamable HTTP).

    strength-coach intelligence serve
    strength-intelligence-mcp --db data/coach.db --config config/intelligence.v1.yaml

The server refuses to start unless config/intelligence.v1.yaml has enabled: true, the database
exists, and at least one active client token exists. It binds to 127.0.0.1 by default; a
private-network deployment must set bind_host and allowed_hosts explicitly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from strength_coach.intelligence.config import (
    IntelligenceConfigError,
    load_config,
    local_config_path,
)
from strength_coach.intelligence.tokens import TokenStore, TokenStoreError

DEFAULT_LOG_LEVEL = "info"


def serve(
    *,
    config_path: str | Path | None = None,
    db_path: str | Path | None = None,
    tokens_path: str | Path | None = None,
    host: str | None = None,
    port: int | None = None,
    log_level: str = DEFAULT_LOG_LEVEL,
) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            'the MCP server needs the optional dependency: '
            'pip install "strength-coach[intelligence]"',
            file=sys.stderr,
        )
        return 2
    from strength_coach.intelligence.mcp.app import build_app
    from strength_coach.store import db as store_db

    try:
        config = load_config(config_path)
    except IntelligenceConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not config.enabled:
        print(
            "intelligence is disabled: set enabled: true in config/intelligence.v1.yaml",
            file=sys.stderr,
        )
        return 2

    target = Path(db_path) if db_path is not None else store_db.default_db_path()
    if not target.exists():
        print(f"database not found: {target}", file=sys.stderr)
        return 2

    try:
        store = TokenStore.load(
            Path(tokens_path) if tokens_path is not None else local_config_path()
        )
    except TokenStoreError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not any(client.active for client in store.clients):
        print(
            "no active MCP client tokens; create one with: "
            "strength-coach intelligence token create --label <name>",
            file=sys.stderr,
        )
        return 2

    app = build_app(db_path=target, config=config, store=store)
    print(
        f"strength intelligence MCP on http://{host or config.bind_host}:"
        f"{port or config.bind_port}{config.endpoint_path} (bearer token required)",
        file=sys.stderr,
    )
    uvicorn.run(
        app,
        host=host or config.bind_host,
        port=port or config.bind_port,
        log_level=log_level,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="strength-intelligence-mcp",
        description="Read-only Training Intelligence MCP server (Streamable HTTP).",
    )
    parser.add_argument("--config", default=None, help="intelligence config path")
    parser.add_argument("--db", default=None, help="database path (default: data/coach.db)")
    parser.add_argument("--tokens", default=None, help="client token file path")
    parser.add_argument("--host", default=None, help="bind address override")
    parser.add_argument("--port", type=int, default=None, help="bind port override")
    parser.add_argument("--log-level", default=DEFAULT_LOG_LEVEL)
    args = parser.parse_args(argv)
    return serve(
        config_path=args.config,
        db_path=args.db,
        tokens_path=args.tokens,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    raise SystemExit(main())
