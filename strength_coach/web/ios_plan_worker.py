"""R7 plan-request worker: one bounded dispatcher over the database queue.

The queue is the `ios_issued_plan` table, not memory. A request survives an app exit, a server
restart and a lost response because it is a row; the dispatcher only decides which row to build
next. There is exactly one dispatcher thread per process and it builds at most one request at a
time, because it holds the same `_CPU_JOB_SLOTS` semaphore the web forecast and resolver preview
use. A thread per request would park an unbounded number of threads on a bounded resource, which
is the failure mode this module exists to avoid (docs/design/IOS-R7-CONTRACT.md §4.4).

The slot is passed in by the caller so this module never imports the web server (which imports
this module).
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
from typing import Any

from strength_coach import ios_config, settings_profile
from strength_coach.features import deload as deload_feature
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe import deload as deload_mod
from strength_coach.prescribe import schedule as schedule_mod
from strength_coach.store import db, ios_workflow

LOGGER = logging.getLogger(__name__)

DISPATCHER_NAME = "ios-plan-dispatcher"
IDLE_WAIT_SECONDS = 2.0

_dispatcher_lock = threading.Lock()
_dispatcher: threading.Thread | None = None
_wake = threading.Event()
_stop = threading.Event()


def wake() -> None:
    """Tell the dispatcher there is new work (or, on launch, that it should look again)."""
    _wake.set()


def _serialize_plan(prescription) -> dict:
    """Use the one serialiser the web UI and the Phase 2 route already share.

    Imported lazily: `web.server` imports this module, so a module-level import would cycle.
    """
    from strength_coach.web.server import prescription_dict

    return prescription_dict(prescription)


def _decision_from(data: Any):
    if not isinstance(data, dict):
        return None
    return deload_feature.DeloadDecision(
        reason=str(data.get("reason") or ""),
        trigger=str(data.get("trigger") or ""),
        block_week=data.get("block_week"),
    )


def build_plan(conn, row) -> tuple[str, str]:
    """Build one request through the shared deterministic path. No new calculation."""
    settings = ios_workflow.load_settings(row)
    inputs = ios_workflow.load_build_inputs(row)
    for_date = str(row["for_date"])
    requested = str(row["requested_session_type"] or "auto")
    session_type = (
        schedule_mod.next_session_type(conn, for_date)
        if requested in ("", "auto") else requested
    )

    # The deload decisions are date-based, so re-deriving them a few seconds after the request
    # is the same decision the handler validated. The client's confirmations are stored in
    # build_inputs_json rather than re-asked.
    resolved = settings_profile.feature_settings(conn, for_date)
    reactive = deload_feature.reactive_decision(conn, for_date, config=resolved.deload)
    scheduled = deload_feature.scheduled_decision(conn, for_date, config=resolved.deload)
    deload_decision = reactive
    if deload_decision is None and scheduled is not None and inputs.get("deload_confirmed"):
        deload_decision = scheduled
    scheduled_suggestion = (
        scheduled if scheduled is not None and deload_decision is None else None
    )

    target_minutes = settings.get("minimum_target_minutes")
    prescription = build_prescription(
        conn,
        for_date=for_date,
        session_type=session_type,
        minimum_session=bool(settings.get("minimum_session", False)),
        minimum_target_minutes=(
            int(target_minutes) if target_minutes not in (None, "") else None
        ),
        deload_decision=deload_decision,
        drop_confirmed=bool(inputs.get("drop_confirmed", False)),
        top_set_requested=settings.get("top_set"),
    )
    if scheduled_suggestion is not None:
        prescription = deload_mod.suggest(prescription, scheduled_suggestion)
    plan = _serialize_plan(prescription)
    return (
        json.dumps(plan, separators=(",", ":"), default=str),
        str(plan["session_type"]),
    )


def _terminalise(conn, issued_plan_id: str, reason: str, at_iso: str) -> None:
    """Record why a request will never be built. Missing/consumed rows need no write."""
    if reason == "superseded":
        ios_workflow.fail_request(
            conn, issued_plan_id, at_iso=at_iso, status=ios_workflow.STATUS_SKIPPED,
            error_code="superseded",
            error_message="a newer request replaced this one",
        )
    elif reason == "expired":
        ios_workflow.fail_request(
            conn, issued_plan_id, at_iso=at_iso, status=ios_workflow.STATUS_SKIPPED,
            error_code="expired",
            error_message="the request was not built before its deadline",
        )


def _remaining_seconds(deadline_iso: str) -> float:
    deadline = datetime.datetime.fromisoformat(str(deadline_iso))
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=datetime.UTC)
    return (deadline - ios_workflow.now()).total_seconds()


def drain_once(db_path=None, slot: threading.Semaphore | None = None) -> bool:
    """Process at most one eligible request; True when a row was handled.

    Tests call this directly so they never depend on the thread's timing. The real dispatcher
    calls it in a loop.
    """
    semaphore = slot if slot is not None else threading.Semaphore(1)
    with db.Store(db_path) as store:
        conn = store.connection
        at = ios_workflow.now_iso()
        ios_workflow.terminalise_stale(conn, at)
        row = ios_workflow.select_next_request(conn, at)
        if row is None:
            return False
        issued_plan_id = str(row["issued_plan_id"])

        # Check #1: before touching the shared CPU slot. A request that is no longer eligible
        # must never reach the resolver, which is the expensive part.
        reason = ios_workflow.is_eligible(conn, issued_plan_id, at)
        if reason is not None:
            _terminalise(conn, issued_plan_id, reason, at)
            return True

        if not semaphore.acquire(timeout=max(0.0, _remaining_seconds(row["request_expires_at"]))):
            _terminalise(conn, issued_plan_id, "expired", ios_workflow.now_iso())
            return True
        try:
            at = ios_workflow.now_iso()
            # Check #2: the slot may have taken minutes. Re-read everything.
            reason = ios_workflow.is_eligible(conn, issued_plan_id, at)
            if reason is not None:
                _terminalise(conn, issued_plan_id, reason, at)
                return True
            current = ios_workflow.get_plan(conn, issued_plan_id, row["device_id"])
            if current is None:
                return True
            if str(current["for_date"]) != datetime.date.today().isoformat():
                # Crossing midnight would build "today's" plan against yesterday's date.
                ios_workflow.fail_request(
                    conn, issued_plan_id, at_iso=at, error_code="stale_date",
                    error_message="the request was made on an earlier server date",
                )
                return True
            if ios_workflow.claim_request(conn, issued_plan_id, at) != 1:
                return True
            try:
                plan_json, resolved_type = build_plan(conn, current)
            except Exception as exc:  # boundary: record a safe code, never a traceback
                code, message = _build_failure(exc)
                LOGGER.warning("iOS plan request %s failed: %s", issued_plan_id, code)
                ios_workflow.fail_request(
                    conn, issued_plan_id, at_iso=ios_workflow.now_iso(),
                    error_code=code, error_message=message,
                )
                return True

            ready = ios_workflow.now()
            ready_iso = ios_workflow.iso(ready)
            config = ios_config.load_config()
            plan_expires_at = ios_workflow.iso(
                ready + datetime.timedelta(seconds=config.issued_plan_ttl_seconds)
            )
            published = ios_workflow.publish_plan(
                conn,
                issued_plan_id=issued_plan_id,
                plan_json=plan_json,
                resolved_session_type=resolved_type,
                ready_at=ready_iso,
                plan_expires_at=plan_expires_at,
            )
            if published != 1:
                # Superseded while building: the plan is discarded, never published.
                _terminalise(conn, issued_plan_id, "superseded", ready_iso)
            return True
        finally:
            semaphore.release()


def _build_failure(exc: Exception) -> tuple[str, str]:
    """Map a build failure to an owner-safe code and message (no paths or tracebacks)."""
    try:
        from strength_coach.prescribe.resolver import ResolverBuildError

        if isinstance(exc, ResolverBuildError):
            stage = getattr(exc, "stage", None)
            detail = str(exc) or "resolver build failed"
            return "resolver_build_failed", (f"{stage}: {detail}" if stage else detail)
    except Exception:  # pragma: no cover - import guard only
        pass
    return "build_failed", str(exc)[:200] or "prescription build failed"


def _loop(db_path, slot: threading.Semaphore) -> None:
    while not _stop.is_set():
        try:
            worked = drain_once(db_path, slot)
        except Exception:  # a dispatcher that dies strands the queue
            LOGGER.exception("iOS plan dispatcher iteration failed")
            worked = False
            time.sleep(1.0)
        if not worked:
            _wake.wait(timeout=IDLE_WAIT_SECONDS)
            _wake.clear()


def start_dispatcher(db_path=None, slot: threading.Semaphore | None = None) -> None:
    """Start the single dispatcher if it is not running. Safe to call on every request."""
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is not None and _dispatcher.is_alive():
            _wake.set()
            return
        _wake.set()
        thread = threading.Thread(
            target=_loop,
            args=(db_path, slot if slot is not None else threading.Semaphore(1)),
            name=DISPATCHER_NAME,
            daemon=True,
        )
        _dispatcher = thread
        thread.start()


def dispatcher_running() -> bool:
    thread = _dispatcher
    return thread is not None and thread.is_alive()


def stop_dispatcher() -> None:
    """Test helper: stop the singleton so a later start does not inherit its database."""
    global _dispatcher
    with _dispatcher_lock:
        thread = _dispatcher
        _dispatcher = None
        _stop.set()
        _wake.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=IDLE_WAIT_SECONDS + 1.0)
    _stop.clear()
