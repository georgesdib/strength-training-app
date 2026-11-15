"""The intelligence configuration switch and bounds."""

from __future__ import annotations

from pathlib import Path

import pytest

from strength_coach.intelligence.config import (
    DEFAULT_MAX_SESSIONS_PER_PAGE,
    DEFAULT_MAX_WINDOW_DAYS,
    IntelligenceConfig,
    IntelligenceConfigError,
    load_config,
    parse_config,
)


def test_repository_config_is_present_and_disabled():
    config = load_config()
    assert config.enabled is False
    assert config.max_window_days == DEFAULT_MAX_WINDOW_DAYS
    assert config.max_sessions_per_page == DEFAULT_MAX_SESSIONS_PER_PAGE


def test_parse_accepts_a_minimal_mapping():
    config = parse_config({"version": 1, "enabled": True})
    assert config == IntelligenceConfig(enabled=True)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"version": 2, "enabled": True},
        {"version": 1, "enabled": "yes"},
        {"version": 1, "enabled": 1},
        {"version": 1, "max_window_days": 27},
        {"version": 1, "max_window_days": 401},
        {"version": 1, "max_window_days": True},
        {"version": 1, "max_window_days": 30.5},
        {"version": 1, "max_sessions_per_page": 0},
        {"version": 1, "max_sessions_per_page": 101},
        {"version": 1, "unknown": 1},
        {"version": 1, "bind_host": ""},
        {"version": 1, "bind_host": "two words"},
        {"version": 1, "bind_port": 0},
        {"version": 1, "bind_port": 70000},
        {"version": 1, "endpoint_path": "mcp"},
        {"version": 1, "allowed_hosts": []},
        {"version": 1, "allowed_hosts": "127.0.0.1"},
        {"version": 1, "max_request_body_bytes": 512},
        {"version": 1, "max_request_body_bytes": 2_000_000},
        {"version": 1, "rate_limit_per_minute": -1},
        {"version": 1, "rate_limit_per_minute": 7000},
        {"version": 1, "max_concurrent_calls": 0},
        {"version": 1, "max_concurrent_calls": 65},
        {"version": 1, "tool_timeout_seconds": 0},
        {"version": 1, "tool_timeout_seconds": 301},
        {"version": 1, "tool_timeout_seconds": "20"},
        {"version": 1, "max_tool_result_bytes": 1023},
        {"version": 1, "max_tool_result_bytes": 10_485_761},
        [],
        "text",
    ],
)
def test_parse_rejects_invalid_configuration(data):
    with pytest.raises(ValueError):
        parse_config(data)


def test_transport_defaults_are_safe():
    config = IntelligenceConfig()
    assert config.bind_host == "127.0.0.1"
    assert config.bind_port == 8765
    assert config.endpoint_path == "/mcp"
    assert config.allowed_hosts == ("127.0.0.1:*", "localhost:*")
    assert config.max_request_body_bytes == 262_144
    assert config.rate_limit_per_minute == 60
    assert config.max_concurrent_calls == 4
    assert config.tool_timeout_seconds == 20
    assert config.max_tool_result_bytes == 1_048_576


def test_transport_settings_are_configurable(tmp_path: Path):
    target = tmp_path / "intelligence.v1.yaml"
    target.write_text(
        "version: 1\nenabled: true\nbind_host: 0.0.0.0\nbind_port: 9000\n"
        "endpoint_path: /intel\nallowed_hosts: ['mcp.example.com:*']\n",
        encoding="utf-8",
    )
    config = load_config(target)
    assert (config.bind_host, config.bind_port, config.endpoint_path) == (
        "0.0.0.0", 9000, "/intel"
    )
    assert config.allowed_hosts == ("mcp.example.com:*",)


def test_load_config_reads_an_explicit_file(tmp_path: Path):
    target = tmp_path / "intelligence.v1.yaml"
    target.write_text(
        "version: 1\nenabled: true\nmax_window_days: 100\nmax_sessions_per_page: 5\n",
        encoding="utf-8",
    )
    config = load_config(target)
    assert config.enabled is True
    assert config.max_window_days == 100
    assert config.max_sessions_per_page == 5


def test_load_config_reports_the_filename(tmp_path: Path):
    target = tmp_path / "intelligence.v1.yaml"
    target.write_text("version: 9\n", encoding="utf-8")
    with pytest.raises(IntelligenceConfigError, match="intelligence.v1.yaml"):
        load_config(target)


def test_missing_file_is_reported(tmp_path: Path):
    with pytest.raises(IntelligenceConfigError):
        load_config(tmp_path / "absent.yaml")


def test_sensitive_readiness_is_off_by_default_and_parseable():
    assert IntelligenceConfig().allow_sensitive_readiness is False
    enabled = parse_config({"version": 1, "allow_sensitive_readiness": True})
    assert enabled.allow_sensitive_readiness is True
    with pytest.raises(ValueError):
        parse_config({"version": 1, "allow_sensitive_readiness": "yes"})


def test_config_mapping_is_revision_ready():
    mapping = IntelligenceConfig(enabled=True).as_mapping()
    assert mapping["version"] == 1
    assert mapping["enabled"] is True
    assert mapping["max_window_days"] == DEFAULT_MAX_WINDOW_DAYS
    assert mapping["max_sessions_per_page"] == DEFAULT_MAX_SESSIONS_PER_PAGE
    for key in (
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
    ):
        assert key in mapping
