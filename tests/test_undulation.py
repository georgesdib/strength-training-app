"""Weekly undulation: a config cycle of rep schemes, keyed to the declared anchor."""

from __future__ import annotations

from contextlib import contextmanager
from types import MappingProxyType

from conftest import make_readiness, make_training
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe.undulation import Undulation
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30",
     "RIR": "3", "Reps_Done": "8"},
]


@contextmanager
def store_with(block_start=None):
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        if block_start:
            repositories.append_athlete_profile(
                store.connection,
                effective_from=block_start,
                primary_goal="longevity",
                goal_rank=["longevity", "strength"],
                focus_lifts=[],
                block_start_date=block_start,
            )
        yield store
    finally:
        store.close()


def item(prescription, exercise_id):
    return next(i for i in prescription.items if i.exercise_id == exercise_id)


def test_week_three_puts_main_lifts_on_maximal():
    with store_with("2024-01-01") as store:
        # 2024-01-15 is week 3 of the cycle.
        prescription = build_prescription(store.connection, for_date="2024-01-15",
                                          session_day="A")

    bench = item(prescription, "bench_press")
    assert (bench.reps_low, bench.reps_high) == (1, 3)
    assert bench.load_kg > 84.5           # fewer reps at the same RIR means more load
    assert prescription.notes["undulation_week"] == 3
    assert any("DUP week 3" in warning for warning in prescription.warnings)


def test_the_hinge_keeps_the_strength_scheme():
    with store_with("2024-01-01") as store:
        prescription = build_prescription(store.connection, for_date="2024-01-15",
                                          session_day="B")

    trap_bar = item(prescription, "trap_bar_deadlift")
    assert (trap_bar.reps_low, trap_bar.reps_high) == (3, 5)


def test_week_two_puts_accessories_on_volume():
    with store_with("2024-01-01") as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08",
                                          session_day="A")

    lateral = item(prescription, "lateral_raise")
    assert (lateral.reps_low, lateral.reps_high) == (6, 8)


def test_without_an_anchor_the_day_templates_apply():
    with store_with() as store:
        prescription = build_prescription(store.connection, for_date="2024-01-15",
                                          session_day="A")

    bench = item(prescription, "bench_press")
    assert (bench.reps_low, bench.reps_high) == (3, 5)
    assert prescription.notes["undulation_week"] is None


def test_undulation_can_be_disabled():
    disabled = Undulation(
        enabled=False, cycle_weeks=4,
        weeks=MappingProxyType({3: MappingProxyType({"main": "maximal"})}),
    )
    with store_with("2024-01-01") as store:
        prescription = build_prescription(store.connection, for_date="2024-01-15",
                                          session_day="A", undulation=disabled)

    bench = item(prescription, "bench_press")
    assert (bench.reps_low, bench.reps_high) == (3, 5)
    assert not any("DUP" in warning for warning in prescription.warnings)
