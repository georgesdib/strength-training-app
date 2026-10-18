"""LLM client interface, a null implementation, and one HTTP adapter.

The architecture claim is that the model explains and never computes, so the client protocol
is deliberately tiny: one method, text in, text out. There is no tool-calling surface here --
numbers are produced by Python and handed to the model as facts, never the other way round.

`NullLLM` is the default. A run with it installed must be structurally identical to a run with
a real model, differing only in narrative fields (docs/V0-SCOPE.md §4 criterion 5).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """The model call failed. The caller must keep the deterministic artifacts."""


class LLMUnavailable(LLMError):
    """No model is configured (the NullLLM path)."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    tokens: int | None = None


@runtime_checkable
class LLMClient(Protocol):
    """The only thing the rest of the system may ask a model to do."""

    model: str

    @property
    def available(self) -> bool: ...

    def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse: ...


class NullLLM:
    """No model. The system must still emit a valid prescription with this installed."""

    model = "null"

    @property
    def available(self) -> bool:
        return False

    def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        raise LLMUnavailable("no LLM is configured (NullLLM)")


class OpenAICompatibleClient:
    """Chat-completions client for OpenAI-compatible endpoints.

    Deliberately generic: OpenAI, OpenRouter, vLLM, llama.cpp and Ollama all expose
    `/chat/completions` with the same shape, so one adapter covers a local model and a hosted
    one without adding a dependency. The API key is optional because a local server may not
    need one.
    """

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 700,
        timeout_s: float = 30.0,
        transport: Any | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self._transport = transport or _urllib_transport

    @property
    def available(self) -> bool:
        return True

    def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = self._transport(
            f"{self.base_url}/chat/completions",
            payload,
            headers,
            self.timeout_s,
        )
        try:
            parsed = json.loads(body)
            text = parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError(f"unexpected response shape from {self.base_url}: {exc}") from exc
        if not isinstance(text, str) or not text.strip():
            raise LLMError(f"{self.model} returned an empty response")
        tokens = (parsed.get("usage") or {}).get("total_tokens")
        return LLMResponse(text=text.strip(), model=self.model, tokens=tokens)


def _urllib_transport(
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_s: float,
) -> str:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise LLMError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMError(f"could not reach {url}: {exc.reason}") from exc
