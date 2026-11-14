"""REST adapter for the iOS intelligence facade.

The routes are additive, authenticated by the existing device bearer token, and return the same
envelope the capability layer produced. No route reshapes or partially returns a payload.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import parse_qs, urlsplit

from strength_coach.intelligence.auth import Principal
from strength_coach.intelligence.config import load_config
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


def weekly_review(
    conn: sqlite3.Connection,
    device: dict[str, Any],
    raw_path: str,
    *,
    config=None,
    clock=None,
) -> dict[str, Any]:
    query = _query(raw_path, {"week_end"})
    payload: dict[str, Any] = {}
    if "week_end" in query:
        payload["week_end"] = query["week_end"]
    return run(conn, device, "get_weekly_review", payload, config=config, clock=clock)
