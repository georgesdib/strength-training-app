"""Milestone B: materialised core rows must reproduce the on-demand owner outputs."""

from __future__ import annotations

import json

import pytest
from conftest import make_readiness, make_training

from strength_coach import history
from strength_coach.analytics import core
from strength_coach.features import progress, strength_trend
from strength_coach.store import db, importer

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "2"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "90", "RIR": "2"},
    {"Date": "2024-01-04", "Exercise": "Trap Bar Deadlift", "Weight_Used": "155", "RIR": "2"},
    {"Date": "2024-01-04", "Exercise": "Competition Bench Press", "Weight_Used": "92.5", "RIR": "1"},
    {"Date": "2024-01-08", "Exercise": "Trap Bar Deadlift", "Weight_Used": "160", "RIR": "2"},
    {"Date": "2024-01-08", "Exercise": "Competition Bench Press", "Weight_Used": "95", "RIR": "2"},
    {"Date": "2024-01-11", "Exercise": "Trap Bar Deadlift", "Weight_Used": "162.5", "RIR": "2"},
]


@pytest.fixture
def store(tmp_path):
    handle = db.Store(tmp_path / "core.db")
    training = make_training(ROWS)
    readiness = make_readiness([{"Date": "2024-01-01"}])
    importer.import_export(
        handle.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    try:
        yield handle
    finally:
        handle.close()


def on_demand(monkeypatch):
    monkeypatch.setattr(core, "ensure", lambda conn: False)


def test_progress_parity_before_and_after_materialisation(store, monkeypatch):
    conn = store.connection
    on_demand(monkeypatch)
    before = progress.performance_points(conn, "2024-01-12")
    before_best, before_dates = progress._session_lift_e1rms(conn)
    assert before

    monkeypatch.undo()
    state = core.build(conn)
    assert state["ready"] is True

    after = progress.performance_points(conn, "2024-01-12")
    after_best, after_dates = progress._session_lift_e1rms(conn)
    assert after == before
    assert after_best == before_best
    assert after_dates == before_dates


def test_strength_trend_parity(store, monkeypatch):
    conn = store.connection
    on_demand(monkeypatch)
    before = strength_trend.observations(
        conn, "trap_bar_deadlift", "2023-12-01", "2024-01-31"
    )
    assert before

    monkeypatch.undo()
    core.build(conn)
    after = strength_trend.observations(
        conn, "trap_bar_deadlift", "2023-12-01", "2024-01-31"
    )
    assert after == before


def test_correction_rebuilds_and_preserves_parity(store, monkeypatch):
    conn = store.connection
    core.build(conn)
    session_id = conn.execute(
        "SELECT session_id FROM session WHERE occurred_on = '2024-01-11'"
    ).fetchone()[0]
    detail = history.detail(conn, session_id)
    sets = [
        {"exercise_id": item["exercise_id"], "load_kg": "170",
         "reps": item["reps"], "rir": item["rir"]}
        for item in detail["sets"]
    ]
    history.edit_session(conn, session_id, sets=sets)

    assert core.is_ready(conn, core.CORE_SPEC) is True

    on_demand(monkeypatch)
    expected = strength_trend.observations(
        conn, "trap_bar_deadlift", "2023-12-01", "2024-01-31"
    )
    expected_points = progress.performance_points(conn, "2024-01-12")

    monkeypatch.undo()
    actual = strength_trend.observations(
        conn, "trap_bar_deadlift", "2023-12-01", "2024-01-31"
    )
    actual_points = progress.performance_points(conn, "2024-01-12")
    assert actual == expected
    assert actual_points == expected_points


def test_voided_session_disappears_from_derived(store, monkeypatch):
    conn = store.connection
    core.build(conn)
    session_id = conn.execute(
        "SELECT session_id FROM session WHERE occurred_on = '2024-01-08'"
    ).fetchone()[0]
    history.void_session(conn, session_id, reason="test")

    on_demand(monkeypatch)
    expected = strength_trend.observations(
        conn, "trap_bar_deadlift", "2023-12-01", "2024-01-31"
    )
    monkeypatch.undo()
    actual = strength_trend.observations(
        conn, "trap_bar_deadlift", "2023-12-01", "2024-01-31"
    )
    assert actual == expected


def test_unbuilt_family_falls_back_to_on_demand(store):
    conn = store.connection
    assert core.ensure(conn) is False
    points = progress.performance_points(conn, "2024-01-12")
    assert points
    assert conn.execute("SELECT COUNT(*) FROM derived_set").fetchone()[0] == 0


def test_failed_family_is_never_consumed(store):
    conn = store.connection
    core.build(conn)
    conn.execute("DELETE FROM derived_set")
    conn.execute(
        "UPDATE analytics_build SET status = 'failed' WHERE family = ?",
        (core.CORE_SPEC.family,),
    )
    assert core.ensure(conn) is False
    assert progress.performance_points(conn, "2024-01-12")


def test_import_refreshes_an_already_ready_family(store, monkeypatch):
    conn = store.connection
    core.build(conn)
    assert core.ensure(conn) is True

    training = make_training([
        {"Date": "2024-01-15", "Exercise": "Trap Bar Deadlift",
         "Weight_Used": "165", "RIR": "2"},
    ])
    readiness = make_readiness([{}])
    importer.import_export(
        conn, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    # The incremental hook keeps the family ready and current for a small import.
    assert core.ensure(conn) is True

    on_demand(monkeypatch)
    expected = progress.performance_points(conn, "2024-01-20")
    monkeypatch.undo()
    assert progress.performance_points(conn, "2024-01-20") == expected
    assert any(row["date"] == "2024-01-15" for row in expected)


def test_taxonomy_change_invalidates_the_family(store, monkeypatch):
    conn = store.connection
    core.build(conn)
    assert core.ensure(conn) is True
    assert "taxonomy" in core.CORE_SPEC.dependencies

    monkeypatch.setattr(core, "_taxonomy_digest", lambda: "files:changed")
    assert core.ensure(conn) is False

    monkeypatch.undo()
    assert core.ensure(conn) is True


def test_derived_rows_carry_the_method_version(store):
    conn = store.connection
    core.build(conn)
    versions = {
        row[0] for row in conn.execute("SELECT DISTINCT method_version FROM derived_set")
    }
    assert versions == {core.METHOD_VERSION}
    payload = conn.execute(
        "SELECT strength_json FROM derived_set WHERE strength_json IS NOT NULL LIMIT 1"
    ).fetchone()[0]
    assert json.loads(payload)["estimate"]["quality"]
