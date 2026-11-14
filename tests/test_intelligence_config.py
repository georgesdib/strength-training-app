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
        [],
        "text",
    ],
)
def test_parse_rejects_invalid_configuration(data):
    with pytest.raises(ValueError):
        parse_config(data)


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


def test_config_mapping_is_revision_ready():
    mapping = IntelligenceConfig(enabled=True).as_mapping()
    assert mapping == {
        "version": 1,
        "enabled": True,
        "max_window_days": DEFAULT_MAX_WINDOW_DAYS,
        "max_sessions_per_page": DEFAULT_MAX_SESSIONS_PER_PAGE,
    }
