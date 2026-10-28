"""Shadow rows are written on persistence only, and the gate never enables anything."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from strength_coach.features import shadow_report
from strength_coach.prescribe import persistence
from strength_coach.store import db, queries, repositories

ON = "2026-03-30"


def plan_for(day=ON):
    return {
        "for_date": day,
        "session_type": "squat",
        "notes": {"exposure_trim": {"enabled": False, "applied": False}},
        "items": [{
            "exercise_id": "ssb_squat", "sets": 3, "reps_low": 5, "reps_high": 5,
            "load_kg": 100, "load_basis": "e1rm", "rir_target": 2, "essential": True,
            "refs": [],
        }],
    }


def store_and_persist():
    store = db.Store(":memory:")
    persistence.store_plan(store.connection, plan_for())
    return store


def test_persisting_a_prescription_writes_exposure_and_substitution_rows():
    store = store_and_persist()
    try:
        rows = queries.shadow_decisions(store.connection)
    finally:
        store.close()
    assert {row["component"] for row in rows} == {"exposure", "substitution"}
    assert all(row["applied"] == 0 for row in rows)
    assert all(row["action"] == "none" for row in rows)
    assert all(row["prescription_id"] for row in rows)


def test_shadow_rows_cannot_be_updated_or_deleted():
    store = store_and_persist()
    try:
        conn = store.connection
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE shadow_decision SET reason = 'rewritten'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM shadow_decision")
    finally:
        store.close()


def test_the_gate_fails_on_thin_data_and_never_enables_anything():
    store = store_and_persist()
    try:
        report = shadow_report.report(store.connection, ON)
    finally:
        store.close()
    assert report.rows == 2
    assert report.ready is False
    assert report.activation_allowed is False
    assert any(not check.passed for check in report.checks)


def test_the_gate_passes_only_with_span_evaluations_and_high_days():
    store = db.Store(":memory:")
    conn = store.connection
    start = dt.date(2026, 2, 10)
    try:
        for index in range(10):
            day = (start + dt.timedelta(days=7 * index)).isoformat()
            repositories.append_shadow_decision(
                conn, evaluated_on=day, component="exposure", rule_id="MOD-EXP-001",
                signal={"signal": "high" if index < 3 else "normal", "ratio": 1.4},
                proposed={}, reason="recorded", action="none", applied=False,
            )
        report = shadow_report.report(conn, "2026-04-30")
    finally:
        store.close()
    assert report.ready is True
    assert report.activation_allowed is False
    assert report.high_signal_days == 3
    assert report.shadow_days >= 56
    assert all(check.passed for check in report.checks)
