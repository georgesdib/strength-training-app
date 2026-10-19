"""VBT wiring: attach a velocity target when the calibration is trustworthy, say so when not."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from conftest import make_readiness, make_training
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer

DATES = ("2024-01-04", "2024-01-11", "2024-01-18")


def rows_with_velocity() -> list[dict]:
    rows = []
    for day_index, day in enumerate(DATES):
        for set_index in range(4):
            rows.append({
                "Date": day,
                "Exercise": "Safety Squat Bar",
                "Weight_Used": "100",
                "RIR": "2",
                "Reps_Done": "3",
                "Avg_velocity": f"{0.34 + 0.01 * set_index:.6f}",
            })
    rows += [
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
         "RIR": "2", "Reps_Done": "10"},
    ]
    return rows


def rows_without_velocity() -> list[dict]:
    return [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
         "RIR": "2", "Reps_Done": "10"},
    ]


@contextmanager
def store_with(rows, readiness_rows=None):
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def test_a_trustworthy_calibration_attaches_and_persists_a_target():
    with store_with(rows_with_velocity()) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-22", session_day="A")
        squat = next(i for i in prescription.items if i.exercise_id == "ssb_squat")
        rows = [
            dict(row) for row in conn.execute(
                "SELECT * FROM vbt_calibration"
            )
        ]

    assert squat.velocity_target == pytest.approx(0.355, abs=0.01)
    assert squat.vbt_basis and "lift" in squat.vbt_basis
    assert len(prescription.calibration_ids) == 1
    assert prescription.notes["vbt"]["status"] == "available"
    assert prescription.notes["vbt"]["targets"] == 1
    assert len(rows) == 1

    stored = [row for row in prescription.as_rows() if row["exercise_id"] == "ssb_squat"][0]
    assert stored["velocity_target"] == pytest.approx(squat.velocity_target)
    assert stored["vbt_basis"] == squat.vbt_basis


def test_the_same_target_is_not_persisted_twice():
    with store_with(rows_with_velocity()) as store:
        conn = store.connection
        first = build_prescription(conn, for_date="2024-01-22", session_day="A")
        second = build_prescription(conn, for_date="2024-01-22", session_day="A")
        count = conn.execute("SELECT COUNT(*) AS c FROM vbt_calibration").fetchone()["c"]

    assert first.calibration_ids == second.calibration_ids
    assert count == 1


def test_without_enough_velocity_data_no_target_is_invented():
    with store_with(rows_without_velocity()) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-22",
                                          session_day="A")

    assert all(item.velocity_target is None for item in prescription.items)
    assert prescription.calibration_ids == ()
    assert prescription.notes["vbt"]["status"] == "unavailable"
    assert "12 clean sets" in prescription.notes["vbt"]["reason"]


def test_a_modified_session_skips_velocity_targets():
    with store_with(
        rows_with_velocity(),
        readiness_rows=[{"Date": "2024-01-22", "Sleep": "2", "Energy": "4"}],
    ) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-22",
                                          session_day="A")

    assert prescription.fallback_level == "fatigue_reduced"
    assert all(item.velocity_target is None for item in prescription.items)
    assert prescription.notes["vbt"]["status"] == "skipped"


def test_hex_bar_velocity_targets_are_withheld():
    rows = []
    for day in ("2024-01-04", "2024-01-11", "2024-01-18"):
        for index in range(4):
            rows.append({
                "Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
                "RIR": "2", "Reps_Done": "3",
                "Avg_velocity": f"{0.31 + 0.01 * index:.6f}",
            })
    rows += [
        {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)",
         "Weight_Used": "70", "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
         "RIR": "2", "Reps_Done": "10"},
        {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "3", "Reps_Done": "8"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-22",
                                          session_day="B")

    trap_bar = next(i for i in prescription.items if i.exercise_id == "trap_bar_deadlift")
    assert trap_bar.velocity_target is None
    assert "trap_bar_deadlift" in prescription.notes["vbt"]["withheld"]
