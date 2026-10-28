"""Prescription invariants across the four session types.

These are the contract-level checks the audit cares about: a load is executable or explicitly
unknown, rounding is real, no RIR is fabricated for quality work, and a clean history yields an
executable prescription.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach.prescribe import build_prescription, loads
from strength_coach.store import db, importer

HISTORY = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Squat", "Weight_Used": "105",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "75",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (pause)", "Weight_Used": "75",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Sumo Deadlift", "Weight_Used": "120",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "12"},
    {"Date": "2024-01-01", "Exercise": "Ab Wheel", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Hanging Leg Raise", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Dumbbell Row", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Lying Leg Curls", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Overhead Press (seated)", "Weight_Used": "40",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Pull-ups (wide grip)", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Box Jumps", "Weight_Used": "0",
     "RIR": "4", "Reps_Done": "4"},
]

SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")


@contextmanager
def store_with():
    training = make_training(HISTORY)
    readiness = make_readiness([{}])
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


@pytest.mark.parametrize("session_type", SESSION_TYPES)
def test_every_prescribed_load_is_executable_or_explicitly_unknown(session_type):
    with store_with() as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type=session_type,
        )

    assert prescription.executable, prescription.issues
    for item in prescription.items:
        assert item.load_kg is not None
        assert item.load_kg >= 0
        if item.load_kg > 0:
            assert loads.is_multiple_of(item.load_kg, item.rounding_increment_kg)
        assert not (item.unknown_load_reason and prescription.executable)
        if item.effort_model == "quality":
            assert item.rir_target is None
            assert item.quality_stop
        else:
            assert item.rir_target is not None
            assert 1 <= item.rir_target <= 4
    assert not any(issue.startswith("SPINAL_CAP:") for issue in prescription.issues)
