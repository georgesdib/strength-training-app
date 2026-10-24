"""Local LLM settings: save, mask and preserve secrets."""

from __future__ import annotations

import stat

import pytest

from strength_coach.agents import config


def test_save_and_load_llm_settings_round_trip(tmp_path):
    path = tmp_path / "llm.local.toml"
    result = config.update_llm_settings(
        enabled=True,
        model="local-model",
        base_url="http://127.0.0.1:11434/v1",
        api_key="secret-key",
        temperature=0.1,
        max_tokens=500,
        timeout_s=20,
        path=path,
    )
    assert result["enabled"] is True
    assert result["model"] == "local-model"
    assert result["api_key"] == "secr…-key"
    assert "secret-key" not in str(result)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = config.load_settings(path, env={})
    assert loaded.api_key == "secret-key"
    assert loaded.model == "local-model"


def test_blank_key_keeps_the_stored_key_but_clear_removes_it(tmp_path):
    path = tmp_path / "llm.local.toml"
    config.update_llm_settings(
        enabled=True, model="m", base_url="http://localhost:1/v1",
        api_key="keep-me", path=path,
    )
    config.update_llm_settings(
        enabled=True, model="m2", base_url="http://localhost:1/v1",
        api_key="", path=path,
    )
    assert config.load_settings(path, env={}).api_key == "keep-me"
    assert config.load_settings(path, env={}).model == "m2"

    config.update_llm_settings(
        enabled=True, model="m3", base_url="http://localhost:1/v1",
        api_key="", clear_api_key=True, path=path,
    )
    assert config.load_settings(path, env={}).api_key is None


def test_disabling_uses_null_provider_without_losing_configuration(tmp_path):
    path = tmp_path / "llm.local.toml"
    config.update_llm_settings(
        enabled=False, model="m", base_url="http://localhost:1/v1",
        api_key="secret", path=path,
    )
    loaded = config.load_settings(path, env={})
    assert loaded.provider == "null"
    assert loaded.enabled is False
    assert loaded.api_key == "secret"


def test_enabled_settings_require_a_model_and_http_url(tmp_path):
    path = tmp_path / "llm.local.toml"
    with pytest.raises(config.LLMConfigError):
        config.update_llm_settings(
            enabled=True, model="", base_url="http://localhost:1/v1", path=path
        )
    with pytest.raises(config.LLMConfigError):
        config.update_llm_settings(
            enabled=True, model="m", base_url="localhost:1", path=path
        )
