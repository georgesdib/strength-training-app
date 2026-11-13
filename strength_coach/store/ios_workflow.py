"""Persistence helpers for R7 plan requests and Phase 2 idempotency receipts.

The HTTP/service layer owns the training decisions. This module only writes and reads the plan
request row and the receipt table; it never imports features or prescribe modules, so it stays at
the store layer.

R7 splits the old "issued plan" into a request lifecycle (`status`) and a liveness axis
(`consumed_at`/`superseded_at`). Every conditional write below is deliberate: the dispatcher and
the request handler can race, and a guarded UPDATE is how a superseded request is stopped from
publishing a plan (https://github.com/georgesdib/strength-app/blob/main/docs/contracts/IOS-R7-CONTRACT.md §4.4).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from strength_coach.store.db import transaction

RECEIPT_REPLAY_HEADER = "Idempotent-Replay"

STATUS_QUEUED = "queued"
STATUS_BUILDING = "building"
STATUS_READY = "ready"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"


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


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _loads(value: Any) -> Any:
    if value in (None, ""):
        return None
    return json.loads(value)


# --- request lifecycle -----------------------------------------------------


def enqueue_plan_request(
    conn,
    *,
    issued_plan_id: str,
    device_id: str,
    for_date: str,
    requested_session_type: str,
    target_device_id: str,
    execution_target: str,
    settings: dict[str, Any],
    build_inputs: dict[str, Any],
    readiness_json: str,
    readiness_ack: bool,
    created_at: str,
    request_expires_at: str,
) -> None:
    """Supersede the device's live row and insert this request atomically.

    Supersession is a timestamp, not a status rewrite: a row that is already building keeps
    its status so the dispatcher's guarded publish can tell that its result is stale. A queued
    row superseded here is terminalised by the dispatcher's stale sweep.
    """
    with transaction(conn):
        # Include an expired-but-never-started row so the partial unique index is clear.
        # One live row per requester and per executor: a phone asking for a watch plan
        # replaces its own live plan, and the watch's plan replaces a previous watch plan
        # even when a different device requested it.
        conn.execute(
            "UPDATE ios_issued_plan SET superseded_at = ? "
            "WHERE (device_id = ? OR COALESCE(target_device_id, device_id) = ?) "
            "  AND consumed_at IS NULL AND superseded_at IS NULL",
            (created_at, device_id, target_device_id),
        )
        conn.execute(
            "INSERT INTO ios_issued_plan "
            "(issued_plan_id, device_id, status, requested_session_type, session_type, "
            " settings_json, build_inputs_json, prescription_id, for_date, plan_json, "
            " readiness_json, readiness_ack, created_at, building_started_at, ready_at, "
            " finished_at, error_code, error_message, request_expires_at, plan_expires_at, "
            " consumed_at, superseded_at, workout_id, target_device_id, execution_target) "
            "VALUES (?, ?, 'queued', ?, NULL, ?, ?, NULL, ?, NULL, ?, ?, ?, NULL, NULL, "
            "        NULL, NULL, NULL, ?, NULL, NULL, NULL, NULL, ?, ?)",
            (
                issued_plan_id, device_id, requested_session_type,
                _json(settings), _json(build_inputs), for_date,
                readiness_json, 1 if readiness_ack else 0,
                created_at, request_expires_at, target_device_id, execution_target,
            ),
        )


def current_plan(conn, device_id: str):
    """The device's live row, whether it requested it or is its execution target."""
    row = conn.execute(
        "SELECT * FROM ios_issued_plan "
        "WHERE (device_id = ? OR target_device_id = ?) "
        "  AND consumed_at IS NULL AND superseded_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (str(device_id), str(device_id)),
    ).fetchone()
    return dict(row) if row is not None else None


def get_plan(conn, issued_plan_id: str, device_id: str):
    """One plan by id for an authenticated caller.

    The start handler enforces that the caller is the execution target; this lookup does not
    filter by device because a mismatched caller must receive wrong_execution_target rather
    than a misleading 404.
    """
    del device_id
    row = conn.execute(
        "SELECT * FROM ios_issued_plan WHERE issued_plan_id = ?",
        (str(issued_plan_id),),
    ).fetchone()
    return dict(row) if row is not None else None


def select_next_request(conn, at_iso: str):
    """Oldest eligible queued request, or None. FIFO; this deployment has one device."""
    row = conn.execute(
        "SELECT * FROM ios_issued_plan "
        "WHERE status = 'queued' AND consumed_at IS NULL AND superseded_at IS NULL "
        "  AND request_expires_at > ? "
        "ORDER BY created_at, issued_plan_id LIMIT 1",
        (at_iso,),
    ).fetchone()
    return dict(row) if row is not None else None


def is_eligible(conn, issued_plan_id: str, at_iso: str) -> str | None:
    """Re-read one request; return an ineligibility reason, or None when it may be built.

    The dispatcher calls this before the CPU slot and again immediately before the build,
    because the slot can take minutes. The reason values are the `error_code` written when the
    request is terminalised.
    """
    row = conn.execute(
        "SELECT status, consumed_at, superseded_at, request_expires_at FROM ios_issued_plan "
        "WHERE issued_plan_id = ?",
        (str(issued_plan_id),),
    ).fetchone()
    if row is None:
        return "missing"
    if row["consumed_at"] is not None:
        return "consumed"
    if row["superseded_at"] is not None:
        return "superseded"
    if row["status"] != STATUS_QUEUED:
        return "not_queued"
    if str(row["request_expires_at"]) <= at_iso:
        return "expired"
    return None


def claim_request(conn, issued_plan_id: str, at_iso: str) -> int:
    """Move queued -> building. Zero rows means someone else won or it stopped being eligible."""
    cursor = conn.execute(
        "UPDATE ios_issued_plan SET status = 'building', building_started_at = ? "
        "WHERE issued_plan_id = ? AND status = 'queued' AND superseded_at IS NULL "
        "  AND consumed_at IS NULL",
        (at_iso, str(issued_plan_id)),
    )
    return int(cursor.rowcount)


def publish_plan(
    conn,
    *,
    issued_plan_id: str,
    plan_json: str,
    resolved_session_type: str,
    ready_at: str,
    plan_expires_at: str,
) -> int:
    """building -> ready, only while the request is still live.

    Zero rows means it was superseded or terminalised while building: the caller must discard
    the plan. This is the generation check expressed as a conditional write.
    """
    cursor = conn.execute(
        "UPDATE ios_issued_plan SET status = 'ready', plan_json = ?, session_type = ?, "
        "       ready_at = ?, plan_expires_at = ?, finished_at = ? "
        "WHERE issued_plan_id = ? AND status = 'building' AND superseded_at IS NULL "
        "  AND consumed_at IS NULL",
        (plan_json, resolved_session_type, ready_at, plan_expires_at, ready_at,
         str(issued_plan_id)),
    )
    return int(cursor.rowcount)


def fail_request(
    conn,
    issued_plan_id: str,
    *,
    at_iso: str,
    error_code: str,
    error_message: str,
    status: str = STATUS_ERROR,
) -> int:
    """Terminalise a queued or building request with a reason. Never overwrites a ready row."""
    cursor = conn.execute(
        "UPDATE ios_issued_plan SET status = ?, error_code = ?, error_message = ?, "
        "       finished_at = ? "
        "WHERE issued_plan_id = ? AND status IN ('queued', 'building')",
        (status, error_code, error_message, at_iso, str(issued_plan_id)),
    )
    return int(cursor.rowcount)


def terminalise_stale(conn, at_iso: str) -> int:
    """Queue hygiene: a queued row that is superseded or past its build deadline is skipped.

    These rows are invisible to the selection query, so without this sweep they would sit at
    `queued` forever and look like work in progress in the database.
    """
    cursor = conn.execute(
        "UPDATE ios_issued_plan "
        "SET status = 'skipped', finished_at = ?, "
        "    error_code = CASE WHEN superseded_at IS NOT NULL THEN 'superseded' "
        "                      ELSE 'expired' END, "
        "    error_message = CASE WHEN superseded_at IS NOT NULL "
        "                         THEN 'a newer request replaced this one' "
        "                         ELSE 'the request was not built before its deadline' END "
        "WHERE status = 'queued' "
        "  AND (superseded_at IS NOT NULL OR request_expires_at <= ?)",
        (at_iso, at_iso),
    )
    return int(cursor.rowcount)


def reset_interrupted(conn) -> int:
    """Return building rows to queued after a restart.

    Nothing is published before the guarded publish, and the build has no side effects, so a
    build interrupted by a process death can simply run again. Marking it an error would
    manufacture a failure for a request that can still succeed.
    """
    cursor = conn.execute(
        "UPDATE ios_issued_plan SET status = 'queued', building_started_at = NULL "
        "WHERE status = 'building'"
    )
    return int(cursor.rowcount)


def consume_plan(
    conn,
    issued_plan_id: str,
    workout_id: str,
    consumed_at: str,
    *,
    prescription_id: str | None = None,
) -> int:
    """Link a started workout. `prescription_id` is written only for a post-R7 preview."""
    cursor = conn.execute(
        "UPDATE ios_issued_plan SET consumed_at = ?, workout_id = ?, "
        "       prescription_id = COALESCE(?, prescription_id) "
        "WHERE issued_plan_id = ? AND consumed_at IS NULL AND superseded_at IS NULL",
        (consumed_at, workout_id, prescription_id, str(issued_plan_id)),
    )
    return int(cursor.rowcount)


def _column(row, name: str):
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


def load_settings(row) -> dict[str, Any]:
    data = _loads(_column(row, "settings_json"))
    return data if isinstance(data, dict) else {}


def load_build_inputs(row) -> dict[str, Any]:
    data = _loads(_column(row, "build_inputs_json"))
    return data if isinstance(data, dict) else {}


# --- receipts --------------------------------------------------------------


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
