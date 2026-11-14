"""Build lifecycle, checkpoints and safe publication.

A family build is a sequence of bounded transactions over `analytics_revision` rows. Committed
batches are durable progress, never published state. `publish` re-checks the revision, method
version and dependency fingerprint inside one `BEGIN IMMEDIATE` transaction; a source mutation
that committed before the check prevents publication, and a mutation cannot commit during it.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable

from strength_coach.analytics.families import FamilySpec, spec_for
from strength_coach.analytics.revision import current_revision, family_revision
from strength_coach.store import db

Handler = Callable[[sqlite3.Connection, sqlite3.Row], None]
Backfill = Callable[[sqlite3.Connection, str | None, int], tuple[str | None, bool]]


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _row(conn: sqlite3.Connection, family: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM analytics_build WHERE family = ?", (family,)
    ).fetchone()


def _require_transaction(conn: sqlite3.Connection) -> None:
    if not conn.in_transaction:
        raise RuntimeError("build state must be written inside a transaction")


def ensure_build(conn: sqlite3.Connection, spec: FamilySpec) -> sqlite3.Row:
    """Create or reconcile the family row; a version/fingerprint change restarts the build."""
    _require_transaction(conn)
    row = _row(conn, spec.family)
    fingerprint = spec.fingerprint()
    if row is None:
        conn.execute(
            "INSERT INTO analytics_build "
            "(family, method_version, dependency_fingerprint, status) "
            "VALUES (?, ?, ?, 'pending')",
            (spec.family, spec.method_version, fingerprint),
        )
    elif (
        row["method_version"] != spec.method_version
        or row["dependency_fingerprint"] != fingerprint
    ):
        conn.execute(
            "UPDATE analytics_build SET method_version = ?, dependency_fingerprint = ?, "
            "status = 'pending', processed_revision = 0, source_revision = 0, cursor = NULL, "
            "started_at = NULL, finished_at = NULL, last_error = NULL WHERE family = ?",
            (spec.method_version, fingerprint, spec.family),
        )
    return _row(conn, spec.family)  # type: ignore[return-value]


def _state(conn: sqlite3.Connection, row: sqlite3.Row, spec: FamilySpec | None) -> dict:
    """Persisted lifecycle plus validated readiness.

    `status` is what the build table says (pending/running/ready/failed/stale). `ready` is
    **validated readiness** and is only true when a FamilySpec is available to check the current
    method version and dependency fingerprint. In phase 1 the registry is empty, so a row may
    legitimately show `status: ready` with `ready: false` and `readiness: unverified`; that
    distinction keeps diagnostics from implying a verified family. Consumers never infer
    readiness from `status`; they call `is_ready` with their spec.
    """
    current = family_revision(conn, row["family"])
    resolved = spec or spec_for(row["family"])
    persisted = row["status"]
    processed = int(row["processed_revision"])
    ready = False
    reason: str | None = None

    if resolved is None:
        if persisted == "ready" and processed >= current:
            readiness = "unverified"
            reason = "no registered family specification"
        else:
            readiness = "not_ready"
            reason = (
                f"build is {persisted}"
                if persisted != "ready"
                else "source revision is newer than the build"
            )
    else:
        version_ok = row["method_version"] == resolved.method_version
        fingerprint_ok = row["dependency_fingerprint"] == resolved.fingerprint()
        ready = (
            persisted == "ready"
            and processed >= current
            and version_ok
            and fingerprint_ok
        )
        if ready:
            readiness = "verified"
        else:
            readiness = "not_ready"
            if persisted != "ready":
                reason = f"build is {persisted}"
            elif processed < current:
                reason = "source revision is newer than the build"
            elif not version_ok:
                reason = "method version changed"
            else:
                reason = "dependency fingerprint changed"

    return {
        "family": row["family"],
        "status": persisted,
        "readiness": readiness,
        "readiness_reason": reason,
        "ready": ready,
        "method_version": row["method_version"],
        "dependency_fingerprint": row["dependency_fingerprint"],
        "processed_revision": processed,
        "source_revision": int(row["source_revision"]),
        "family_revision": current,
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "last_published_at": row["last_published_at"],
        "last_error": row["last_error"],
    }


def is_ready(conn: sqlite3.Connection, spec: FamilySpec) -> bool:
    """True only for a published family whose revision and dependencies are current."""
    row = _row(conn, spec.family)
    if row is None:
        return False
    return bool(_state(conn, row, spec)["ready"])


def family_state(conn: sqlite3.Connection, spec: FamilySpec) -> dict | None:
    row = _row(conn, spec.family)
    return None if row is None else _state(conn, row, spec)


def _process_batch(
    conn: sqlite3.Connection, family: str, handler: Handler, batch_size: int
) -> int:
    with db.transaction(conn):
        row = _row(conn, family)
        if row is None:
            raise RuntimeError(f"no build row for family {family!r}")
        revisions = conn.execute(
            "SELECT * FROM analytics_revision "
            "WHERE (family IS NULL OR family = ?) AND revision_id > ? "
            "ORDER BY revision_id LIMIT ?",
            (family, int(row["processed_revision"]), int(batch_size)),
        ).fetchall()
        for revision in revisions:
            handler(conn, revision)
        if revisions:
            conn.execute(
                "UPDATE analytics_build SET processed_revision = ? WHERE family = ?",
                (int(revisions[-1]["revision_id"]), family),
            )
        return len(revisions)


def publish(
    conn: sqlite3.Connection,
    spec: FamilySpec,
    *,
    before_publish: Callable[[sqlite3.Connection], None] | None = None,
    require_cursor: str | None = None,
) -> bool:
    """Atomically promote a running, current, dependency-matching build to `ready`.

    Returns False when any invariant fails. The family then stays non-ready and a later call can
    resume it; committed batches are never implicitly published.
    """
    with db.transaction(conn):
        row = _row(conn, spec.family)
        if row is None or row["status"] != "running":
            return False
        if before_publish is not None:
            before_publish(conn)
        if require_cursor is not None and row["cursor"] != require_cursor:
            return False
        if (
            row["method_version"] != spec.method_version
            or row["dependency_fingerprint"] != spec.fingerprint()
        ):
            conn.execute(
                "UPDATE analytics_build SET status = 'stale', finished_at = ?, "
                "last_error = ? WHERE family = ?",
                (_now(), "dependency fingerprint changed before publication", spec.family),
            )
            return False
        current = family_revision(conn, spec.family)
        if int(row["processed_revision"]) < current:
            return False
        timestamp = _now()
        conn.execute(
            "UPDATE analytics_build SET status = 'ready', source_revision = ?, "
            "finished_at = ?, last_published_at = ?, last_error = NULL WHERE family = ?",
            (current, timestamp, timestamp, spec.family),
        )
        return True


def _noop_handler(conn: sqlite3.Connection, revision: sqlite3.Row) -> None:
    """Phase 1 has no materialisation; the coordinator still exercises real revision batches."""


def run_build(
    conn: sqlite3.Connection,
    spec: FamilySpec,
    handler: Handler | None = None,
    *,
    backfill: Backfill | None = None,
    batch_size: int = 100,
    max_batches: int | None = None,
    before_publish: Callable[[sqlite3.Connection], None] | None = None,
) -> dict:
    """Start or resume a build and return its state.

    `max_batches` bounds the work for interruption tests: the family is left `running` with its
    checkpoint, and a later call resumes. A handler failure records `failed` and re-raises; the
    batch transaction rolls back so `processed_revision` does not advance past the failed work.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if max_batches is not None and max_batches < 0:
        raise ValueError("max_batches must not be negative")
    handler = handler or _noop_handler
    family = spec.family

    try:
        with db.transaction(conn):
            ensure_build(conn, spec)
            row = _row(conn, family)
            assert row is not None
            if _state(conn, row, spec)["ready"]:
                return _state(conn, row, spec)
            conn.execute(
                "UPDATE analytics_build SET status = 'running', "
                "started_at = COALESCE(started_at, ?), finished_at = NULL, last_error = NULL, "
                "source_revision = MAX(source_revision, ?) WHERE family = ?",
                (_now(), family_revision(conn, family), family),
            )

        if backfill is not None:
            while True:
                with db.transaction(conn):
                    row = _row(conn, family)
                    assert row is not None
                    if row["cursor"] == "backfill-done":
                        break
                    next_cursor, done = backfill(conn, row["cursor"], batch_size)
                    conn.execute(
                        "UPDATE analytics_build SET cursor = ? WHERE family = ?",
                        ("backfill-done" if done else next_cursor, family),
                    )
                if done:
                    break

        batches = 0
        while True:
            row = _row(conn, family)
            assert row is not None
            if max_batches is not None and batches >= max_batches:
                return _state(conn, row, spec)
            if int(row["processed_revision"]) < family_revision(conn, family):
                progressed = _process_batch(conn, family, handler, batch_size)
                if progressed == 0:
                    return _state(conn, row, spec)
                batches += 1
                continue
            if publish(
                conn, spec, before_publish=before_publish,
                require_cursor="backfill-done" if backfill is not None else None,
            ):
                return _state(conn, _row(conn, family), spec)  # type: ignore[arg-type]
            row = _row(conn, family)
            assert row is not None
            if row["status"] != "running":
                return _state(conn, row, spec)
            if family_revision(conn, family) <= int(row["processed_revision"]):
                return _state(conn, row, spec)
    except Exception as exc:
        with db.transaction(conn):
            conn.execute(
                "UPDATE analytics_build SET status = 'failed', finished_at = ?, "
                "last_error = ? WHERE family = ?",
                (_now(), str(exc)[:500], family),
            )
        raise


def status_snapshot(conn: sqlite3.Connection) -> dict:
    """Serialisable status for the diagnostics endpoint; no payloads or personal values."""
    current = current_revision(conn)
    rows = conn.execute("SELECT * FROM analytics_build ORDER BY family").fetchall()
    return {
        "revision": current,
        "families": [_state(conn, row, None) for row in rows],
    }
