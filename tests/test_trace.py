"""Run tracing: a run is closed even when the pipeline raises."""

from __future__ import annotations

import pytest

from strength_coach.store import db
from strength_coach.trace import RunTrace


def test_trace_records_events_in_order():
    with db.Store(":memory:") as store:
        with RunTrace.start(store.connection, input_hash="h") as trace:
            trace.event("input", {"rows": 3})
            trace.event("feature", {"e1rm": 120.0})
        assert trace.events == [(1, "input"), (2, "feature")]
        assert trace.status == "ok"


def test_a_failed_run_is_marked_error():
    store = db.Store(":memory:")
    try:
        with pytest.raises(RuntimeError):
            with RunTrace.start(store.connection, input_hash="h"):
                raise RuntimeError("boom")
        row = store.connection.execute("SELECT status, finished_at FROM run").fetchone()
        assert row["status"] == "error"
        assert row["finished_at"] is not None
    finally:
        store.close()


def test_unknown_event_kind_is_rejected():
    with db.Store(":memory:") as store:
        with RunTrace.start(store.connection, input_hash="h") as trace:
            with pytest.raises(ValueError, match="unknown run_event kind"):
                trace.event("not_a_kind")
