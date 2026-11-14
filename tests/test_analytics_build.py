"""Build lifecycle, checkpoints and safe publication for derived-analytics families."""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest
from conftest import make_readiness, make_training

from strength_coach.analytics import (
    FamilySpec,
    current_revision,
    family_state,
    is_ready,
    record_dependency_change,
    record_mutation,
    run_build,
    status_snapshot,
)
from strength_coach.store import db, importer
from strength_coach.web.server import create_server

SPEC = FamilySpec("probe_family", "1.0.0", {"e1rm": "v1", "taxonomy": "v1"})


@pytest.fixture
def store(tmp_path):
    handle = db.Store(tmp_path / "coach.db")
    try:
        yield handle
    finally:
        handle.close()


def append_revision(conn, kind="import", detail=None):
    with db.transaction(conn):
        return record_mutation(conn, kind, detail=detail)


def test_build_completes_and_publishes(store):
    conn = store.connection
    append_revision(conn)
    append_revision(conn)
    state = run_build(conn, SPEC)
    assert state["status"] == "ready"
    assert state["ready"] is True
    assert state["processed_revision"] == 2
    assert is_ready(conn, SPEC)
    assert family_state(conn, SPEC)["source_revision"] == 2


def test_no_work_still_publishes_an_empty_family(store):
    conn = store.connection
    state = run_build(conn, SPEC)
    assert state["status"] == "ready"
    assert state["processed_revision"] == 0


def test_partial_batches_are_not_published(store):
    conn = store.connection
    for _ in range(5):
        append_revision(conn)
    state = run_build(conn, SPEC, batch_size=2, max_batches=1)
    assert state["status"] == "running"
    assert state["processed_revision"] == 2
    assert state["ready"] is False
    assert not is_ready(conn, SPEC)


def test_interrupted_build_resumes_from_checkpoint(store):
    conn = store.connection
    for _ in range(5):
        append_revision(conn)
    run_build(conn, SPEC, batch_size=2, max_batches=1)
    state = run_build(conn, SPEC, batch_size=2)
    assert state["status"] == "ready"
    assert state["processed_revision"] == 5


def test_failed_build_records_the_error_and_never_publishes(store):
    conn = store.connection
    append_revision(conn)
    seen = []

    def handler(conn, revision):
        seen.append(revision["revision_id"])
        if len(seen) == 2:
            raise ValueError("handler failed")

    append_revision(conn)
    with pytest.raises(ValueError):
        run_build(conn, SPEC, handler, batch_size=1)
    state = family_state(conn, SPEC)
    assert state["status"] == "failed"
    assert "handler failed" in state["last_error"]
    assert state["processed_revision"] == 1
    assert not is_ready(conn, SPEC)


def test_source_change_during_build_is_processed_before_publication(store):
    conn = store.connection
    for _ in range(2):
        append_revision(conn)
    appended = []

    def handler(conn, revision):
        if not appended:
            appended.append(True)
            record_mutation(conn, "import", detail={"late": True})

    state = run_build(conn, SPEC, handler)
    assert state["status"] == "ready"
    assert state["processed_revision"] == 3
    assert current_revision(conn) == 3


def test_source_change_immediately_before_publication_blocks_readiness(store):
    conn = store.connection
    append_revision(conn)
    appended = []

    def before_publish(conn):
        if not appended:
            appended.append(True)
            record_mutation(conn, "correction", session_id="late")

    state = run_build(conn, SPEC, before_publish=before_publish)
    assert state["status"] == "ready"
    assert state["processed_revision"] == 2
    assert current_revision(conn) == 2


def test_publication_refuses_a_newer_source_revision(store):
    conn = store.connection
    append_revision(conn)
    state = run_build(conn, SPEC, max_batches=1)
    assert state["status"] == "running"
    append_revision(conn)
    # A ready family is invalidated by the mutation, and a running family cannot publish stale.
    assert not is_ready(conn, SPEC)
    state = run_build(conn, SPEC)
    assert state["status"] == "ready"
    assert state["processed_revision"] == 2


def test_dependency_mismatch_prevents_readiness_and_restarts(store):
    conn = store.connection
    append_revision(conn)
    run_build(conn, SPEC)
    assert is_ready(conn, SPEC)

    changed = FamilySpec("probe_family", "2.0.0", {"e1rm": "v2"})
    assert not is_ready(conn, changed)
    state = run_build(conn, changed)
    assert state["ready"] is True
    assert state["method_version"] == "2.0.0"
    assert state["processed_revision"] == current_revision(conn)


def test_ready_family_becomes_stale_on_a_source_mutation(store):
    conn = store.connection
    append_revision(conn)
    run_build(conn, SPEC)
    assert is_ready(conn, SPEC)
    append_revision(conn)
    assert not is_ready(conn, SPEC)
    assert family_state(conn, SPEC)["status"] == "stale"


def test_config_change_invalidates_only_the_named_family(store):
    conn = store.connection
    other = FamilySpec("other_family", "1.0.0", {"volume": "v1"})
    append_revision(conn)
    run_build(conn, SPEC)
    run_build(conn, other)
    assert is_ready(conn, SPEC) and is_ready(conn, other)

    record_dependency_change(
        conn, "config", config_digest="sha256:changed", families=[SPEC.family]
    )
    assert not is_ready(conn, SPEC)
    assert is_ready(conn, other)


def test_fingerprint_is_deterministic_and_order_independent(store):
    first = FamilySpec("probe_family", "1", {"b": "2", "a": "1"})
    second = FamilySpec("probe_family", "1", {"a": "1", "b": "2"})
    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint() != FamilySpec("probe_family", "1", {"a": "2"}).fingerprint()


def test_status_snapshot_is_serialisable(store, tmp_path):
    conn = store.connection
    append_revision(conn)
    run_build(conn, SPEC)
    snapshot = status_snapshot(conn)
    assert snapshot["revision"] == 1
    assert snapshot["families"][0]["family"] == "probe_family"
    assert snapshot["families"][0]["status"] == "ready"
    json.dumps(snapshot)


def test_concurrent_connection_mutation_during_build_is_seen(tmp_path):
    path = tmp_path / "concurrent.db"
    first = db.Store(path)
    second = db.Store(path)
    try:
        for _ in range(2):
            append_revision(first.connection)
        state = run_build(first.connection, SPEC, batch_size=1, max_batches=1)
        assert state["processed_revision"] == 1

        with db.transaction(second.connection):
            record_mutation(second.connection, "void", session_id="other")

        state = run_build(first.connection, SPEC, batch_size=1)
        assert state["status"] == "ready"
        assert state["processed_revision"] == 3
    finally:
        first.close()
        second.close()


def test_status_endpoint_reports_the_revision(tmp_path):
    path = tmp_path / "web.db"
    handle = db.Store(path)
    training = make_training([{"Exercise": "Trap Bar Deadlift", "Weight_Used": "150"}])
    readiness = make_readiness([{}])
    importer.import_export(
        handle.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    handle.close()

    httpd = create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/api/analytics/status") as response:
            payload = json.loads(response.read().decode())
        assert response.status == 200
        assert payload["revision"] == 1
        assert payload["families"] == []
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
