"""The intelligence configuration switch and bounds.

Follows the existing backend convention: one versioned YAML file under config/, a frozen
dataclass, explicit ranges and an exception that names the file. It deliberately contains no
secrets and no model settings: intelligence authentication reuses the per-device bearer tokens
already in the database, and INT-1 has no provider.

The switch gates *execution*, not import. Tests and in-process callers can build a service with
an explicit enabled configuration; a deployment that exposes a transport checks this switch
before it serves anything.
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

MIN_WINDOW_DAYS = 28
MAX_WINDOW_DAYS = 400
MIN_SESSIONS_PER_PAGE = 1
MAX_SESSIONS_PER_PAGE = 100

FIELDS = ("version", "enabled", "max_window_days", "max_sessions_per_page")


class IntelligenceConfigError(ValueError):
    """The intelligence configuration file is missing or invalid."""


@dataclass(frozen=True)
class IntelligenceConfig:
    enabled: bool = DEFAULT_ENABLED
    max_window_days: int = DEFAULT_MAX_WINDOW_DAYS
    max_sessions_per_page: int = DEFAULT_MAX_SESSIONS_PER_PAGE

    def as_mapping(self) -> dict[str, object]:
        return {
            "version": VERSION,
            "enabled": self.enabled,
            "max_window_days": self.max_window_days,
            "max_sessions_per_page": self.max_sessions_per_page,
        }


def config_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else paths.config_dir(FILENAME)


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
    return IntelligenceConfig(
        enabled=enabled, max_window_days=window, max_sessions_per_page=page
    )


def load_config(path: str | Path | None = None) -> IntelligenceConfig:
    target = config_path(path)
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return parse_config(data)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise IntelligenceConfigError(f"invalid {FILENAME}: {exc}") from exc
