"""LLM configuration: file first, environment overrides, safe defaults.

Keys must never be committed, so the real settings file is git-ignored
(`config/llm.local.toml`) and a documented example is committed next to it. Precedence is
environment over file over defaults, which lets a shell or a service unit inject a key without
writing one to disk.

The default is `provider = \"null\"`: an unconfigured checkout behaves exactly like a run with
no model, which is the property the whole architecture depends on. Once a provider is
chosen, the endpoint and model default to DeepSeek (OpenAI-compatible), so enabling
narration needs only a provider and a key.
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from strength_coach.agents.client import (
    LLMClient,
    NullLLM,
    OpenAICompatibleClient,
)
from strength_coach.utils import paths

DEFAULT_CONFIG_NAME = "llm.local.toml"
EXAMPLE_CONFIG_NAME = "llm.example.toml"
PROVIDERS = ("null", "openai_compatible")

# The default endpoint is DeepSeek's OpenAI-compatible API. PROVIDER still defaults to
# "null", so an unconfigured checkout stays offline; these are the values used the moment a
# provider is chosen, which means `provider` + an API key is enough to enable narration.
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"

ENV_PREFIX = "STRENGTH_COACH_LLM_"
ENV_KEYS = {
    "PROVIDER": "provider",
    "MODEL": "model",
    "BASE_URL": "base_url",
    "API_KEY": "api_key",
    "TEMPERATURE": "temperature",
    "MAX_TOKENS": "max_tokens",
    "TIMEOUT_S": "timeout_s",
}


class LLMConfigError(ValueError):
    """The configuration is invalid; fix it rather than silently falling back."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str = "null"
    model: str | None = DEFAULT_MODEL
    base_url: str | None = DEFAULT_BASE_URL
    api_key: str | None = None
    temperature: float = 0.2
    max_tokens: int = 700
    timeout_s: float = 30.0
    source: str = "defaults"

    @property
    def enabled(self) -> bool:
        """A model is usable when a provider is chosen and it has something to call."""
        return self.provider != "null" and bool(self.model) and bool(self.base_url)

    def masked_key(self) -> str | None:
        """Never print a key. Enough to tell 'set' from 'unset' and spot the wrong one."""
        if not self.api_key:
            return None
        key = self.api_key
        if len(key) <= 8:
            return "set"
        return f"{key[:4]}…{key[-4:]}"


def config_path(path: str | Path | None = None) -> Path:
    override = os.environ.get(f"{ENV_PREFIX}CONFIG")
    if path is not None:
        return Path(path)
    if override:
        return Path(override)
    return paths.config_dir(DEFAULT_CONFIG_NAME)


def load_settings(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> LLMSettings:
    """Read the settings file, then let the environment override it."""
    environ = os.environ if env is None else env
    settings = LLMSettings()
    source = "defaults"

    file = config_path(path)
    if file.exists():
        settings = replace(_from_file(file), source=str(file))
        source = str(file)

    overrides = _from_env(environ)
    if overrides:
        settings = replace(settings, **overrides, source=f"{source} + environment")

    if settings.provider not in PROVIDERS:
        raise LLMConfigError(
            f"unknown llm provider {settings.provider!r}; expected one of {PROVIDERS}"
        )
    return settings


def _from_file(path: Path) -> LLMSettings:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LLMConfigError(f"could not read {path}: {exc}") from exc

    block = raw.get("llm") or {}
    return LLMSettings(
        provider=str(block.get("provider", "null")),
        model=_optional_str(block.get("model")) or DEFAULT_MODEL,
        base_url=_optional_str(block.get("base_url")) or DEFAULT_BASE_URL,
        api_key=_optional_str(block.get("api_key")),
        temperature=float(block.get("temperature", 0.2)),
        max_tokens=int(block.get("max_tokens", 700)),
        timeout_s=float(block.get("timeout_s", 30.0)),
    )


def _from_env(env: Mapping[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for suffix, field in ENV_KEYS.items():
        raw = env.get(f"{ENV_PREFIX}{suffix}")
        if raw is None or raw == "":
            continue
        if field in {"temperature", "timeout_s"}:
            values[field] = float(raw)
        elif field == "max_tokens":
            values[field] = int(raw)
        else:
            values[field] = raw
    return values


def build_client(settings: LLMSettings | None = None) -> LLMClient:
    """The client for these settings. Unconfigured means NullLLM, never a silent fallback."""
    settings = settings or load_settings()
    if not settings.enabled:
        return NullLLM()
    return OpenAICompatibleClient(
        model=str(settings.model),
        base_url=str(settings.base_url),
        api_key=settings.api_key,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout_s=settings.timeout_s,
    )


def describe(settings: LLMSettings | None = None) -> dict[str, Any]:
    """A diagnostic dictionary with the key masked; used by tools/llm_check.py."""
    settings = settings or load_settings()
    return {
        "provider": settings.provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "api_key": settings.masked_key(),
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "timeout_s": settings.timeout_s,
        "enabled": settings.enabled,
        "source": settings.source,
    }


def _optional_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def save_settings(settings: LLMSettings, path: str | Path | None = None) -> Path:
    """Write the local LLM settings atomically, with owner-only permissions.

    The file is git-ignored by contract. Writing a minimal TOML intentionally drops comments:
    the UI owns this file; the committed example remains the documented template.
    """
    target = config_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# LLM settings written by the local Settings page.",
        "# config/llm.local.toml is git-ignored. Never commit an API key.",
        "",
        "[llm]",
        f"provider = {json.dumps(settings.provider)}",
    ]
    if settings.model is not None:
        lines.append(f"model = {json.dumps(str(settings.model))}")
    if settings.base_url is not None:
        lines.append(f"base_url = {json.dumps(str(settings.base_url))}")
    if settings.api_key:
        lines.append(f"api_key = {json.dumps(str(settings.api_key))}")
    lines.extend([
        f"temperature = {float(settings.temperature)}",
        f"max_tokens = {int(settings.max_tokens)}",
        f"timeout_s = {float(settings.timeout_s)}",
        "",
    ])
    temp = target.with_name(target.name + ".tmp")
    temp.write_text("\n".join(lines), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(target)
    return target


def update_llm_settings(
    *,
    enabled: bool,
    model: str,
    base_url: str,
    api_key: str | None = None,
    clear_api_key: bool = False,
    temperature: float = 0.2,
    max_tokens: int = 700,
    timeout_s: float = 30.0,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Update the local file, preserving an existing key when the field is left blank."""
    target = config_path(path)
    # Read the file only: an environment key must not be copied into the local file by a
    # blank save, because that would move a secret the user deliberately kept out of disk.
    existing = _from_file(target) if target.exists() else LLMSettings()
    key = None if clear_api_key else (str(api_key).strip() or existing.api_key)
    if enabled:
        if not str(model).strip():
            raise LLMConfigError("model is required when the LLM is enabled")
        if not str(base_url).strip().startswith(("http://", "https://")):
            raise LLMConfigError("base_url must start with http:// or https://")
        if not 0 <= float(temperature) <= 2:
            raise LLMConfigError("temperature must be between 0 and 2")
        if int(max_tokens) <= 0:
            raise LLMConfigError("max_tokens must be positive")
        if float(timeout_s) <= 0:
            raise LLMConfigError("timeout_s must be positive")
    settings = LLMSettings(
        provider="openai_compatible" if enabled else "null",
        model=str(model).strip() or DEFAULT_MODEL,
        base_url=str(base_url).strip() or DEFAULT_BASE_URL,
        api_key=key,
        temperature=float(temperature),
        max_tokens=int(max_tokens),
        timeout_s=float(timeout_s),
    )
    save_settings(settings, path)
    effective = load_settings(path)
    return {
        **describe(effective),
        "config_path": str(config_path(path)),
        "environment_override": "environment" in effective.source,
    }
