"""Authentication, principal context and resource limits for the MCP transport.

The capability package never imports this module. Tools read the authenticated principal from a
context variable that the bearer middleware sets for the request; an in-memory protocol test uses
the authenticated() context manager to stand in for the transport.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from strength_coach.intelligence.auth import IntelligenceAuthError, Principal, parse_bearer
from strength_coach.intelligence.tokens import TokenStore

_PRINCIPAL: ContextVar[Principal | None] = ContextVar(
    "intelligence_principal", default=None
)


def current_principal() -> Principal:
    principal = _PRINCIPAL.get()
    if principal is None:
        raise IntelligenceAuthError(401, "authentication required")
    return principal


@contextmanager
def authenticated(principal: Principal) -> Iterator[Principal]:
    """Set the request principal; used by tests and by any future in-process transport."""
    token = _PRINCIPAL.set(principal)
    try:
        yield principal
    finally:
        _PRINCIPAL.reset(token)


ASGIApp = Callable[..., Any]


async def _send_json(
    send: Callable[..., Any],
    status: int,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    raw_headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
    ]
    for name, value in (headers or {}).items():
        raw_headers.append((name.encode("ascii"), value.encode("ascii")))
    await send({"type": "http.response.start", "status": status, "headers": raw_headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


def _headers(scope: dict[str, Any]) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


class BearerAuthMiddleware:
    """Authenticate every HTTP request before the MCP application sees it."""

    def __init__(self, app: ASGIApp, *, store: TokenStore) -> None:
        self._app = app
        self._store = store

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        header = _headers(scope).get("authorization")
        try:
            principal = self._store.authenticate(parse_bearer(header))
        except IntelligenceAuthError as exc:
            challenge = 'Bearer realm="strength-intelligence"'
            await _send_json(
                send,
                exc.status,
                {"error": "invalid_token", "error_description": exc.message},
                {"www-authenticate": challenge},
            )
            return
        token = _PRINCIPAL.set(principal)
        try:
            await self._app(scope, receive, send)
        finally:
            _PRINCIPAL.reset(token)


class LimitMiddleware:
    """Per-client request budget and a concurrent-call ceiling.

    Both exist to bound accidental cost and to keep one client from starving the process. They
    are not a security boundary; authentication is.
    """

    def __init__(self, app: ASGIApp, *, per_minute: int, max_concurrent: int) -> None:
        self._app = app
        self._per_minute = per_minute
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._windows: dict[str, deque[float]] = {}

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        principal = _PRINCIPAL.get()
        client = principal.identity if principal is not None else "-"
        if not self._allow(client):
            await _send_json(
                send,
                429,
                {"error": "rate_limited", "error_description": "request budget exceeded"},
                {"retry-after": "60"},
            )
            return
        if self._semaphore.locked():
            await _send_json(
                send,
                429,
                {"error": "too_many_requests", "error_description": "concurrent call limit"},
                {"retry-after": "1"},
            )
            return
        async with self._semaphore:
            await self._app(scope, receive, send)

    def _allow(self, client: str) -> bool:
        if self._per_minute <= 0:
            return True
        now = time.monotonic()
        window = self._windows.setdefault(client, deque())
        while window and now - window[0] >= 60.0:
            window.popleft()
        if len(window) >= self._per_minute:
            return False
        window.append(now)
        return True
