"""Phase 2 iOS facade configuration.

The values are deliberately small and public: one rollback switch plus the issued-plan lifetime
and receipt retention. They are read per request so an owner can disable mutations without a code
change. A malformed file fails closed; the server returns a generic 500 rather than silently
enabling writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from strength_coach.utils import paths

MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 86400
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365

# R7: how long a request may sit queued/building before it counts as a failed build. Separate
# from issued_plan_ttl_seconds, which bounds how long a *ready* preview may be started.
DEFAULT_PLAN_REQUEST_TTL_SECONDS = 900
MIN_PLAN_REQUEST_TTL_SECONDS = 60
MAX_PLAN_REQUEST_TTL_SECONDS = 3600


class IOSConfigError(RuntimeError):
    """Malformed or out-of-range ios.v1.yaml; the server fails closed."""


@dataclass(frozen=True)
class IOSConfig:
    mutations_enabled: bool
    issued_plan_ttl_seconds: int
    receipt_retention_days: int
    plan_request_ttl_seconds: int = DEFAULT_PLAN_REQUEST_TTL_SECONDS


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


def load_config(path: str | Path | None = None) -> IOSConfig:
    target = Path(path) if path is not None else paths.config_dir("ios.v1.yaml")
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("ios.v1.yaml must contain a mapping")
        return IOSConfig(
            mutations_enabled=_boolean(data.get("mutations_enabled"), "mutations_enabled"),
            issued_plan_ttl_seconds=_bounded_int(
                data.get("issued_plan_ttl_seconds"), "issued_plan_ttl_seconds",
                MIN_TTL_SECONDS, MAX_TTL_SECONDS,
            ),
            receipt_retention_days=_bounded_int(
                data.get("receipt_retention_days"), "receipt_retention_days",
                MIN_RETENTION_DAYS, MAX_RETENTION_DAYS,
            ),
            # Optional so an existing ios.v1.yaml keeps loading unchanged.
            plan_request_ttl_seconds=_bounded_int(
                data.get(
                    "plan_request_ttl_seconds", DEFAULT_PLAN_REQUEST_TTL_SECONDS
                ),
                "plan_request_ttl_seconds",
                MIN_PLAN_REQUEST_TTL_SECONDS, MAX_PLAN_REQUEST_TTL_SECONDS,
            ),
        )
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise IOSConfigError(f"invalid ios.v1.yaml: {exc}") from exc
