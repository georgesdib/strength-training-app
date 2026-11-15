"""Rate and concurrency limits at the transport boundary."""

from __future__ import annotations

import asyncio

from strength_coach.intelligence.mcp.security import LimitMiddleware


def _scope(scope_type: str = "http") -> dict:
    return {"type": scope_type, "method": "POST", "path": "/mcp", "headers": []}


async def _invoke(app, scope: dict | None = None) -> list[dict]:
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await app(scope or _scope(), receive, send)
    return sent


async def _ok(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def test_rate_limit_rejects_the_call_over_budget():
    async def run():
        calls: list[int] = []

        async def inner(scope, receive, send):
            calls.append(1)
            await _ok(scope, receive, send)

        middleware = LimitMiddleware(inner, per_minute=1, max_concurrent=4)
        first = await _invoke(middleware)
        second = await _invoke(middleware)
        return calls, first, second

    calls, first, second = asyncio.run(run())
    assert len(calls) == 1
    assert first[0]["status"] == 200
    assert second[0]["status"] == 429
    assert (b"retry-after", b"60") in second[0]["headers"]


def test_rate_limit_can_be_disabled():
    async def run():
        middleware = LimitMiddleware(_ok, per_minute=0, max_concurrent=4)
        return [await _invoke(middleware) for _ in range(3)]

    assert [result[0]["status"] for result in asyncio.run(run())] == [200, 200, 200]


def test_concurrent_calls_are_bounded():
    async def run():
        started = asyncio.Event()
        release = asyncio.Event()

        async def inner(scope, receive, send):
            started.set()
            await release.wait()
            await _ok(scope, receive, send)

        middleware = LimitMiddleware(inner, per_minute=0, max_concurrent=1)
        running = asyncio.create_task(_invoke(middleware))
        await asyncio.wait_for(started.wait(), timeout=5)
        rejected = await _invoke(middleware)
        release.set()
        accepted = await asyncio.wait_for(running, timeout=5)
        return accepted, rejected

    accepted, rejected = asyncio.run(run())
    assert accepted[0]["status"] == 200
    assert rejected[0]["status"] == 429
    assert (b"retry-after", b"1") in rejected[0]["headers"]


def test_non_http_scopes_bypass_the_limits():
    async def run():
        seen: list[str] = []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        middleware = LimitMiddleware(inner, per_minute=1, max_concurrent=1)
        await _invoke(middleware, _scope("lifespan"))
        return seen

    assert asyncio.run(run()) == ["lifespan"]
