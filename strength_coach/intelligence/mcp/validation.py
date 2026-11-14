"""Strict tool-argument checking at the MCP boundary.

The SDK builds a pydantic model from the handler signature. That is good for discovery, but its
defaults are wrong for this contract: unknown keys are ignored and "4" is coerced to 4. A
capability must see exactly what the caller sent, and reject anything else.

Server middleware runs before validation and exposes the raw params, so it is the right layer.
Ranges and semantic checks stay in the capability request parser; this module only enforces the
shape the tool schema advertises: known arguments, JSON types, no coercion.
"""

from __future__ import annotations

from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.types import CallToolResult, TextContent

#: tool name -> argument -> allowed JSON types. None is an allowed value where listed.
ARGUMENTS: dict[str, dict[str, tuple[type, ...]]] = {
    "get_training_overview": {
        "as_of": (str, type(None)),
        "window_weeks": (int,),
    },
    "get_session_details": {
        "workout_id": (str, type(None)),
        "session_id": (str, type(None)),
        "include_ratios": (bool,),
    },
    "get_exercise_progression": {
        "exercise_id": (str,),
        "as_of": (str, type(None)),
        "window_days": (int,),
        "include_sessions": (bool,),
        "limit_sessions": (int,),
    },
    "get_readiness_history": {
        "start": (str,),
        "end": (str,),
        "fields": (list, type(None)),
    },
    "get_adherence_analysis": {
        "weeks": (int, type(None)),
        "as_of": (str, type(None)),
        "start": (str, type(None)),
        "end": (str, type(None)),
        "group_by": (str,),
        "exercise_id": (str, type(None)),
        "session_type": (str, type(None)),
    },
    "get_prescription": {
        "prescription_id": (str, type(None)),
        "for_date": (str, type(None)),
        "include_provenance": (bool,),
    },
    "get_vbt_analysis": {
        "start": (str,),
        "end": (str,),
        "exercise_id": (str, type(None)),
    },
    "get_programme_block_summary": {
        "as_of": (str, type(None)),
        "block_weeks": (int,),
    },
    "compare_training_periods": {
        "period_a": (dict,),
        "period_b": (dict,),
        "metric": (str,),
        "exercise_id": (str, type(None)),
    },
}


def _matches(value: Any, expected: tuple[type, ...]) -> bool:
    if value is None:
        return type(None) in expected
    if isinstance(value, bool):
        return bool in expected
    return any(type(value) is candidate for candidate in expected if candidate is not bool)


def validate_arguments(tool: object, arguments: object) -> str | None:
    """Return an error message, or None when the arguments are acceptable."""
    spec = ARGUMENTS.get(str(tool))
    if spec is None:
        return None
    if not isinstance(arguments, dict):
        return "invalid_argument: arguments must be an object"
    unknown = sorted(set(arguments) - set(spec))
    if unknown:
        return "invalid_argument: unknown argument(s): " + ", ".join(unknown)
    for name, value in arguments.items():
        if not _matches(value, spec[name]):
            return f"invalid_argument: {name} has the wrong type"
    return None


def error_result(message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        is_error=True,
    )


class StrictToolArgumentsMiddleware:
    """Reject unknown keys and coerced types before the SDK validates the call."""

    async def __call__(self, ctx: ServerRequestContext, call_next):  # type: ignore[no-untyped-def]
        if str(ctx.method) != "tools/call" or not isinstance(ctx.params, dict):
            return await call_next(ctx)
        problem = validate_arguments(
            ctx.params.get("name"), ctx.params.get("arguments", {})
        )
        if problem is not None:
            return error_result(problem)
        return await call_next(ctx)
