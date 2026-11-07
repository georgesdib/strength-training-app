"""Persistence helpers for Phase 2 issued plans and idempotency receipts.

The HTTP/service layer owns the training decisions. This module only writes and reads the two
additive Phase 2 tables; it never imports features or prescribe modules, so it stays at the store
layer. Issued plans are device-scoped and single-use; receipts are device-scoped and bounded.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from strength_coach.store.db import transaction

RECEIPT_REPLAY_HEADER = "Idempotent-Replay"


class IOSWorkflowError(Exception):
    """A contract-level workflow failure with its HTTP status and optional details."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        fields: dict[str, str] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields or {}
        self.details = details or {}


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def iso(value: dt.datetime) -> str:
    return value.isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(now())


def add_days(value: dt.datetime, days: int) -> dt.datetime:
    return value + dt.timedelta(days=days)


def normalize_operation_id(value: object) -> str:
    """Require a UUID Idempotency-Key and normalize it for the composite primary key."""
    try:
        parsed = uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Idempotency-Key must be a UUID") from None
    return str(parsed).lower()


def request_hash(body: dict[str, Any]) -> str:
    """Stable hash of the parsed body; whitespace-only retries hash the same."""
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mint_issued_plan(
    conn,
    *,
    issued_plan_id: str,
    device_id: str,
    prescription_id: str,
    for_date: str,
    session_type: str,
    plan_json: str,
    readiness_json: str,
    readiness_ack: bool,
    created_at: str,
    expires_at: str,
) -> None:
    """Supersede the previous live plan and insert this one atomically."""
    with transaction(conn):
        # Include an expired-but-never-started row so the partial unique index is clear.
        conn.execute(
            "UPDATE ios_issued_plan SET superseded_at = ? "
            "WHERE device_id = ? AND consumed_at IS NULL AND superseded_at IS NULL",
            (created_at, device_id),
        )
        conn.execute(
            "INSERT INTO ios_issued_plan "
            "(issued_plan_id, device_id, prescription_id, for_date, session_type, "
            " plan_json, readiness_json, readiness_ack, created_at, expires_at, "
            " consumed_at, superseded_at, workout_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
            (
                issued_plan_id, device_id, prescription_id, for_date, session_type,
                plan_json, readiness_json, 1 if readiness_ack else 0,
                created_at, expires_at,
            ),
        )


def get_plan(conn, issued_plan_id: str, device_id: str):
    row = conn.execute(
        "SELECT * FROM ios_issued_plan WHERE issued_plan_id = ? AND device_id = ?",
        (str(issued_plan_id), str(device_id)),
    ).fetchone()
    return dict(row) if row is not None else None


def consume_plan(conn, issued_plan_id: str, workout_id: str, consumed_at: str) -> int:
    cursor = conn.execute(
        "UPDATE ios_issued_plan SET consumed_at = ?, workout_id = ? "
        "WHERE issued_plan_id = ? AND consumed_at IS NULL AND superseded_at IS NULL",
        (consumed_at, workout_id, str(issued_plan_id)),
    )
    return int(cursor.rowcount)


def get_receipt(conn, device_id: str, operation_id: str):
    row = conn.execute(
        "SELECT * FROM ios_operation_receipt WHERE device_id = ? AND operation_id = ?",
        (str(device_id), str(operation_id)),
    ).fetchone()
    return dict(row) if row is not None else None


def store_receipt(
    conn,
    *,
    device_id: str,
    operation_id: str,
    route: str,
    digest: str,
    status: int,
    payload: Any,
    created_at: str,
    expires_at: str,
) -> None:
    """Store one successful response; callers must pass 2xx only."""
    conn.execute(
        "INSERT INTO ios_operation_receipt "
        "(device_id, operation_id, route, request_hash, response_status, "
        " response_json, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(device_id), str(operation_id), str(route), str(digest), int(status),
            json.dumps(payload, separators=(",", ":"), default=str),
            created_at, expires_at,
        ),
    )


def prune_receipts(conn, before_iso: str) -> int:
    cursor = conn.execute(
        "DELETE FROM ios_operation_receipt WHERE expires_at < ?", (before_iso,)
    )
    return int(cursor.rowcount)
