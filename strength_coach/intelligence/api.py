"""REST adapter for the iOS intelligence facade.

The routes are additive, authenticated by the existing device bearer token, and return the same
envelope the capability layer produced. No route reshapes or partially returns a payload.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from strength_coach.intelligence.auth import Principal
from strength_coach.intelligence.config import load_config
from strength_coach.intelligence.mcp.db import readonly_connection
from strength_coach.intelligence.service import IntelligenceService

ERROR_STATUS = {
    "invalid_argument": 400,
    "not_found": 404,
    "invalid_state": 409,
    "unavailable": 503,
    "tool_timeout": 504,
    "result_too_large": 413,
    "internal": 500,
}


class RouteError(Exception):
    """A capability failure that the web facade turns into its existing error envelope."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def principal_for(device: dict[str, Any]) -> Principal:
    return Principal(identity=str(device["device_id"]), kind=str(device["kind"]))


def _query(raw_path: str, allowed: set[str]) -> dict[str, str]:
    values = parse_qs(urlsplit(raw_path).query, keep_blank_values=True)
    query: dict[str, str] = {}
    for key, items in values.items():
        if key not in allowed:
            raise RouteError(400, f"unknown query parameter {key!r}")
        if len(items) != 1:
            raise RouteError(400, f"query parameter {key!r} must appear once")
        query[key] = items[0]
    return query


def run(
    conn: sqlite3.Connection,
    device: dict[str, Any],
    name: str,
    payload: dict[str, Any],
    *,
    config=None,
    clock=None,
) -> dict[str, Any]:
    service = IntelligenceService(
        conn,
        config=config if config is not None else load_config(),
        clock=clock,
    )
    result = service.execute(principal_for(device), name, payload)
    if not result.ok:
        error = result.error
        raise RouteError(ERROR_STATUS.get(error.code, 500), error.message)
    return result.envelope.as_dict()


def _int_query(query: dict[str, str], key: str) -> int:
    try:
        return int(query[key])
    except ValueError:
        raise RouteError(400, f"query parameter {key!r} must be an integer") from None


def _bool_query(query: dict[str, str], key: str) -> bool:
    value = query[key].lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    raise RouteError(400, f"query parameter {key!r} must be true or false")


def overview(
    db_path: str | Path, device: dict[str, Any], raw_path: str, *, config=None, clock=None
) -> dict[str, Any]:
    query = _query(raw_path, {"as_of", "window_weeks"})
    payload: dict[str, Any] = {}
    if "as_of" in query:
        payload["as_of"] = query["as_of"]
    if "window_weeks" in query:
        payload["window_weeks"] = _int_query(query, "window_weeks")
    with readonly_connection(db_path) as conn:
        return run(conn, device, "get_training_overview", payload, config=config, clock=clock)


def progression(
    db_path: str | Path,
    exercise_id: str,
    device: dict[str, Any],
    raw_path: str,
    *,
    config=None,
    clock=None,
) -> dict[str, Any]:
    query = _query(
        raw_path, {"as_of", "window_days", "include_sessions", "limit_sessions"}
    )
    payload: dict[str, Any] = {"exercise_id": exercise_id}
    if "as_of" in query:
        payload["as_of"] = query["as_of"]
    if "window_days" in query:
        payload["window_days"] = _int_query(query, "window_days")
    if "include_sessions" in query:
        payload["include_sessions"] = _bool_query(query, "include_sessions")
    if "limit_sessions" in query:
        payload["limit_sessions"] = _int_query(query, "limit_sessions")
    with readonly_connection(db_path) as conn:
        return run(conn, device, "get_exercise_progression", payload, config=config, clock=clock)


def readiness(
    db_path: str | Path, device: dict[str, Any], raw_path: str, *, config=None, clock=None
) -> dict[str, Any]:
    query = _query(raw_path, {"from", "to", "fields"})
    payload: dict[str, Any] = {}
    if "from" in query:
        payload["from"] = query["from"]
    if "to" in query:
        payload["to"] = query["to"]
    if "fields" in query:
        fields = [item.strip() for item in query["fields"].split(",") if item.strip()]
        if not fields:
            raise RouteError(400, "query parameter 'fields' must name at least one field")
        payload["fields"] = fields
    with readonly_connection(db_path) as conn:
        return run(conn, device, "get_readiness_history", payload, config=config, clock=clock)


def session_details(
    db_path: str | Path, device: dict[str, Any], raw_path: str, *, config=None, clock=None
) -> dict[str, Any]:
    query = _query(raw_path, {"workout_id", "session_id", "include_ratios"})
    payload: dict[str, Any] = {}
    for key in ("workout_id", "session_id"):
        if key in query:
            payload[key] = query[key]
    if "include_ratios" in query:
        payload["include_ratios"] = _bool_query(query, "include_ratios")
    with readonly_connection(db_path) as conn:
        return run(conn, device, "get_session_details", payload, config=config, clock=clock)


def weekly_review(
    db_path: str | Path,
    device: dict[str, Any],
    raw_path: str,
    *,
    config=None,
    clock=None,
) -> dict[str, Any]:
    """The REST entrypoint opens SQLite read-only; a caller cannot hand it a writable handle."""
    query = _query(raw_path, {"week_end"})
    payload: dict[str, Any] = {}
    if "week_end" in query:
        payload["week_end"] = query["week_end"]
    with readonly_connection(db_path) as conn:
        return run(conn, device, "get_weekly_review", payload, config=config, clock=clock)
