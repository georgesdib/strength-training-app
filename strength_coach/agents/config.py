"""LLM configuration: file first, environment overrides, safe defaults.

Keys must never be committed, so the real settings file is git-ignored
(`config/llm.local.toml`) and a documented example is committed next to it. Precedence is
environment over file over defaults, which lets a shell or a service unit inject a key without
writing one to disk.

The default is `provider = \"null\"`: an unconfigured checkout behaves exactly like a run with
no model, which is the property the whole architecture depends on.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from strength_coach.agents.client import (
    LLMClient,
    NullLLM,
    OpenAICompatibleClient,
)
from strength_coach.utils import paths

DEFAULT_CONFIG_NAME = "llm.local.toml"
EXAMPLE_CONFIG_NAME = "llm.example.toml"
PROVIDERS = ("null", "openai_compatible")

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
    model: str | None = None
    base_url: str | None = None
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
        model=_optional_str(block.get("model")),
        base_url=_optional_str(block.get("base_url")),
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
