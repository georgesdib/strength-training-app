"""Phase 2 iOS facade configuration.

The values are deliberately small and public: one rollback switch plus the issued-plan lifetime
and receipt retention. They are read per request so an owner can disable mutations without a code
change. A malformed file fails closed; the server returns a generic 500 rather than silently
enabling writes.
"""

from __future__ import annotations

import os
import re
import tempfile
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

DEFAULT_MUTATIONS_ENABLED = True
DEFAULT_ISSUED_PLAN_TTL_SECONDS = 3600
DEFAULT_RECEIPT_RETENTION_DAYS = 30
# The watch app ships separately; minting stays closed until the owner enables it.
DEFAULT_WATCH_ENABLED = False

FIELDS = (
    "mutations_enabled",
    "watch_enabled",
    "issued_plan_ttl_seconds",
    "plan_request_ttl_seconds",
    "receipt_retention_days",
)

DEFAULTS = {
    "mutations_enabled": DEFAULT_MUTATIONS_ENABLED,
    "watch_enabled": DEFAULT_WATCH_ENABLED,
    "issued_plan_ttl_seconds": DEFAULT_ISSUED_PLAN_TTL_SECONDS,
    "plan_request_ttl_seconds": DEFAULT_PLAN_REQUEST_TTL_SECONDS,
    "receipt_retention_days": DEFAULT_RECEIPT_RETENTION_DAYS,
}

RANGES = {
    "mutations_enabled": {"kind": "bool"},
    "watch_enabled": {"kind": "bool"},
    "issued_plan_ttl_seconds": {
        "kind": "int", "min": MIN_TTL_SECONDS, "max": MAX_TTL_SECONDS,
    },
    "plan_request_ttl_seconds": {
        "kind": "int", "min": MIN_PLAN_REQUEST_TTL_SECONDS,
        "max": MAX_PLAN_REQUEST_TTL_SECONDS,
    },
    "receipt_retention_days": {
        "kind": "int", "min": MIN_RETENTION_DAYS, "max": MAX_RETENTION_DAYS,
    },
}

LABELS = {
    "mutations_enabled": "Enable iOS mutations",
    "watch_enabled": "Enable watch device minting",
    "issued_plan_ttl_seconds": "Issued plan TTL (seconds)",
    "plan_request_ttl_seconds": "Plan request TTL (seconds)",
    "receipt_retention_days": "Receipt retention (days)",
}

DESCRIPTIONS = {
    "mutations_enabled": (
        "Master write switch for the iOS facade. Off returns every iOS mutation as 503 "
        "mutation_disabled while bootstrap, today, history and progress stay available."
    ),
    "watch_enabled": (
        "Allows the phone to mint a watch device and token. Existing watch credentials are "
        "ended by revoking them, not by this switch."
    ),
    "issued_plan_ttl_seconds": (
        "How long a ready plan can be started, measured from the moment it becomes ready. "
        "This is the owner's starting window, not the build deadline."
    ),
    "plan_request_ttl_seconds": (
        "How long a request may remain queued or building before it is treated as a failed "
        "build. Kept separate from the ready-plan lifetime so a slow build does not consume "
        "the starting window."
    ),
    "receipt_retention_days": (
        "How long idempotency receipts are retained for safe retries. Older receipts are "
        "expired and removed; this does not affect training rows."
    ),
}


class IOSConfigError(RuntimeError):
    """Malformed or out-of-range ios.v1.yaml; the server fails closed."""


@dataclass(frozen=True)
class IOSConfig:
    mutations_enabled: bool
    issued_plan_ttl_seconds: int
    receipt_retention_days: int
    plan_request_ttl_seconds: int = DEFAULT_PLAN_REQUEST_TTL_SECONDS
    watch_enabled: bool = DEFAULT_WATCH_ENABLED


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


def config_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else paths.config_dir("ios.v1.yaml")


def _parse_config(data: dict) -> IOSConfig:
    if not isinstance(data, dict):
        raise ValueError("ios.v1.yaml must contain a mapping")
    return IOSConfig(
        mutations_enabled=_boolean(data.get("mutations_enabled"), "mutations_enabled"),
        watch_enabled=_boolean(
            data.get("watch_enabled", DEFAULT_WATCH_ENABLED), "watch_enabled"
        ),
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


def load_config(path: str | Path | None = None) -> IOSConfig:
    target = config_path(path)
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return _parse_config(data)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise IOSConfigError(f"invalid ios.v1.yaml: {exc}") from exc


def _display_source(target: Path) -> str:
    try:
        return str(target.resolve().relative_to(paths.repo_root().resolve()))
    except ValueError:
        return str(target)


def describe_config(path: str | Path | None = None) -> dict:
    """Effective values plus the metadata the Settings form needs."""
    target = config_path(path)
    config = load_config(target)
    return {
        "path": str(target),
        "source": _display_source(target),
        "reload": "per request",
        "restart_required": False,
        "effective": {
            "mutations_enabled": config.mutations_enabled,
            "watch_enabled": config.watch_enabled,
            "issued_plan_ttl_seconds": config.issued_plan_ttl_seconds,
            "plan_request_ttl_seconds": config.plan_request_ttl_seconds,
            "receipt_retention_days": config.receipt_retention_days,
        },
        "defaults": dict(DEFAULTS),
        "ranges": {key: dict(value) for key, value in RANGES.items()},
        "labels": dict(LABELS),
        "descriptions": dict(DESCRIPTIONS),
    }


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def save_config(values: dict, path: str | Path | None = None) -> dict:
    """Validate, update only the four known keys, and return the new effective state."""
    target = config_path(path)
    if not isinstance(values, dict):
        raise IOSConfigError("iOS settings must be an object")
    unknown = sorted(set(values) - set(FIELDS))
    if unknown:
        raise IOSConfigError(f"unknown iOS setting(s): {', '.join(unknown)}")

    current = load_config(target)
    merged = {
        "mutations_enabled": values.get("mutations_enabled", current.mutations_enabled),
        "watch_enabled": values.get("watch_enabled", current.watch_enabled),
        "issued_plan_ttl_seconds": values.get(
            "issued_plan_ttl_seconds", current.issued_plan_ttl_seconds
        ),
        "plan_request_ttl_seconds": values.get(
            "plan_request_ttl_seconds", current.plan_request_ttl_seconds
        ),
        "receipt_retention_days": values.get(
            "receipt_retention_days", current.receipt_retention_days
        ),
    }
    try:
        updated = _parse_config(merged)
        text = target.read_text(encoding="utf-8")
        for key in FIELDS:
            line = re.compile(rf"(?m)^{re.escape(key)}:\s*[^\n]*$")
            matches = line.findall(text)
            if len(matches) > 1:
                raise ValueError(f"duplicate {key} in ios.v1.yaml")
            replacement = f"{key}: {_format_value(getattr(updated, key))}"
            if matches:
                text = line.sub(replacement, text, count=1)
            else:
                if not text.endswith("\n"):
                    text += "\n"
                text += replacement + "\n"
        parsed = yaml.safe_load(text) or {}
        _parse_config(parsed)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise IOSConfigError(f"invalid ios.v1.yaml: {exc}") from exc

    _atomic_write(target, text)
    return describe_config(target)
