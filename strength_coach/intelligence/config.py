"""The intelligence switch, bounds and transport settings.

Follows the existing backend convention: one versioned YAML file under config/, a frozen
dataclass, explicit ranges and an exception that names the file. It deliberately contains no
secrets: MCP client tokens are hashed in the git-ignored config/intelligence.local.yaml, and
INT-1 has no provider credentials.

The switch gates *execution and the server*, not import. Tests and in-process callers can build
a service with an explicit enabled configuration; the MCP process refuses to start until the
operator enables it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from strength_coach.utils import paths

VERSION = 1
FILENAME = "intelligence.v1.yaml"

DEFAULT_ENABLED = False
DEFAULT_MAX_WINDOW_DAYS = 400
DEFAULT_MAX_SESSIONS_PER_PAGE = 20
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_BIND_PORT = 8765
DEFAULT_ENDPOINT_PATH = "/mcp"
DEFAULT_ALLOWED_HOSTS = ("127.0.0.1:*", "localhost:*")
DEFAULT_MAX_REQUEST_BODY_BYTES = 262_144
DEFAULT_RATE_LIMIT_PER_MINUTE = 60
DEFAULT_MAX_CONCURRENT_CALLS = 4
DEFAULT_TOOL_TIMEOUT_SECONDS = 20
DEFAULT_MAX_TOOL_RESULT_BYTES = 1_048_576
# Raw readiness values are local-only by default; the MCP dispatch rejects them unless the
# owner deliberately permits them for a trusted host.
DEFAULT_ALLOW_SENSITIVE_READINESS = False

MIN_WINDOW_DAYS = 28
MAX_WINDOW_DAYS = 400
MIN_SESSIONS_PER_PAGE = 1
MAX_SESSIONS_PER_PAGE = 100
MIN_BODY_BYTES = 1_024
MAX_BODY_BYTES = 1_048_576
MAX_RATE_LIMIT = 6_000
MAX_CONCURRENT = 64
MIN_TOOL_TIMEOUT_SECONDS = 1
MAX_TOOL_TIMEOUT_SECONDS = 300
MIN_TOOL_RESULT_BYTES = 1_024
MAX_TOOL_RESULT_BYTES = 10_485_760

FIELDS = (
    "version",
    "enabled",
    "max_window_days",
    "max_sessions_per_page",
    "bind_host",
    "bind_port",
    "endpoint_path",
    "allowed_hosts",
    "max_request_body_bytes",
    "rate_limit_per_minute",
    "max_concurrent_calls",
    "tool_timeout_seconds",
    "max_tool_result_bytes",
    "allow_sensitive_readiness",
)


class IntelligenceConfigError(ValueError):
    """The intelligence configuration file is missing or invalid."""


@dataclass(frozen=True)
class IntelligenceConfig:
    enabled: bool = DEFAULT_ENABLED
    max_window_days: int = DEFAULT_MAX_WINDOW_DAYS
    max_sessions_per_page: int = DEFAULT_MAX_SESSIONS_PER_PAGE
    bind_host: str = DEFAULT_BIND_HOST
    bind_port: int = DEFAULT_BIND_PORT
    endpoint_path: str = DEFAULT_ENDPOINT_PATH
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    max_concurrent_calls: int = DEFAULT_MAX_CONCURRENT_CALLS
    tool_timeout_seconds: int = DEFAULT_TOOL_TIMEOUT_SECONDS
    max_tool_result_bytes: int = DEFAULT_MAX_TOOL_RESULT_BYTES
    allow_sensitive_readiness: bool = DEFAULT_ALLOW_SENSITIVE_READINESS

    def as_mapping(self) -> dict[str, object]:
        return {
            "version": VERSION,
            "enabled": self.enabled,
            "max_window_days": self.max_window_days,
            "max_sessions_per_page": self.max_sessions_per_page,
            "bind_host": self.bind_host,
            "bind_port": self.bind_port,
            "endpoint_path": self.endpoint_path,
            "allowed_hosts": list(self.allowed_hosts),
            "max_request_body_bytes": self.max_request_body_bytes,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "max_concurrent_calls": self.max_concurrent_calls,
            "tool_timeout_seconds": self.tool_timeout_seconds,
            "max_tool_result_bytes": self.max_tool_result_bytes,
            "allow_sensitive_readiness": self.allow_sensitive_readiness,
        }


def config_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else paths.config_dir(FILENAME)


def local_config_path(path: str | Path | None = None) -> Path:
    """The git-ignored token file; never committed and never printed."""
    return Path(path) if path is not None else paths.config_dir("intelligence.local.yaml")


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def _bounded_int(value: object, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    if not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if any(character.isspace() for character in value):
        raise ValueError(f"{name} must not contain whitespace")
    return value


def _hosts(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("allowed_hosts must be a non-empty list")
    hosts: list[str] = []
    for entry in value:
        hosts.append(_text(entry, "allowed_hosts"))
    return tuple(hosts)


def parse_config(data: object) -> IntelligenceConfig:
    if not isinstance(data, dict):
        raise ValueError(f"{FILENAME} must contain a mapping")
    unknown = sorted(set(data) - set(FIELDS))
    if unknown:
        raise ValueError(f"unknown key(s): {', '.join(unknown)}")
    version = data.get("version")
    if version != VERSION:
        raise ValueError(f"version must be {VERSION}")
    enabled = _boolean(data.get("enabled", DEFAULT_ENABLED), "enabled")
    allow_sensitive = _boolean(
        data.get("allow_sensitive_readiness", DEFAULT_ALLOW_SENSITIVE_READINESS),
        "allow_sensitive_readiness",
    )
    window = _bounded_int(
        data.get("max_window_days", DEFAULT_MAX_WINDOW_DAYS),
        "max_window_days",
        MIN_WINDOW_DAYS,
        MAX_WINDOW_DAYS,
    )
    page = _bounded_int(
        data.get("max_sessions_per_page", DEFAULT_MAX_SESSIONS_PER_PAGE),
        "max_sessions_per_page",
        MIN_SESSIONS_PER_PAGE,
        MAX_SESSIONS_PER_PAGE,
    )
    bind_host = _text(data.get("bind_host", DEFAULT_BIND_HOST), "bind_host")
    bind_port = _bounded_int(data.get("bind_port", DEFAULT_BIND_PORT), "bind_port", 1, 65_535)
    endpoint_path = _text(
        data.get("endpoint_path", DEFAULT_ENDPOINT_PATH), "endpoint_path"
    )
    if not endpoint_path.startswith("/"):
        raise ValueError("endpoint_path must start with /")
    hosts = _hosts(data.get("allowed_hosts", list(DEFAULT_ALLOWED_HOSTS)))
    body = _bounded_int(
        data.get("max_request_body_bytes", DEFAULT_MAX_REQUEST_BODY_BYTES),
        "max_request_body_bytes",
        MIN_BODY_BYTES,
        MAX_BODY_BYTES,
    )
    rate = _bounded_int(
        data.get("rate_limit_per_minute", DEFAULT_RATE_LIMIT_PER_MINUTE),
        "rate_limit_per_minute",
        0,
        MAX_RATE_LIMIT,
    )
    concurrent = _bounded_int(
        data.get("max_concurrent_calls", DEFAULT_MAX_CONCURRENT_CALLS),
        "max_concurrent_calls",
        1,
        MAX_CONCURRENT,
    )
    timeout = _bounded_int(
        data.get("tool_timeout_seconds", DEFAULT_TOOL_TIMEOUT_SECONDS),
        "tool_timeout_seconds",
        MIN_TOOL_TIMEOUT_SECONDS,
        MAX_TOOL_TIMEOUT_SECONDS,
    )
    result_bytes = _bounded_int(
        data.get("max_tool_result_bytes", DEFAULT_MAX_TOOL_RESULT_BYTES),
        "max_tool_result_bytes",
        MIN_TOOL_RESULT_BYTES,
        MAX_TOOL_RESULT_BYTES,
    )
    return IntelligenceConfig(
        enabled=enabled,
        max_window_days=window,
        max_sessions_per_page=page,
        bind_host=bind_host,
        bind_port=bind_port,
        endpoint_path=endpoint_path,
        allowed_hosts=hosts,
        max_request_body_bytes=body,
        rate_limit_per_minute=rate,
        max_concurrent_calls=concurrent,
        tool_timeout_seconds=timeout,
        max_tool_result_bytes=result_bytes,
        allow_sensitive_readiness=allow_sensitive
    )


def load_config(path: str | Path | None = None) -> IntelligenceConfig:
    target = config_path(path)
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return parse_config(data)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise IntelligenceConfigError(f"invalid {FILENAME}: {exc}") from exc
