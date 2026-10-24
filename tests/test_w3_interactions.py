"""W3 regression tests for the approved modifier precedence."""

from __future__ import annotations

from test_prescribe import BASE_HISTORY, store_with

from strength_coach.features.deload import DeloadDecision
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe.deload import apply_items
from strength_coach.prescribe.minimum_session import estimate_minutes

LOW_READINESS = [{
    "Date": "2024-01-15", "Sleep": "1", "Energy": "1", "Mood": "1",
    "Soreness": "1", "Stress": "1", "Nutrition": "1", "Hydration": "1",
}]
DECISION = DeloadDecision("audit", "scheduled")


def test_deload_never_increases_a_one_set_item():
    with store_with(BASE_HISTORY) as store:
        minimum = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            minimum_session=True, minimum_target_minutes=45,
        )
        items, _, _, _ = apply_items(minimum.items, DECISION)
    before = {item.exercise_id: item.sets for item in minimum.items}
    after = {item.exercise_id: item.sets for item in items}
    assert all(after[key] <= before[key] for key in after)


def test_deload_uses_one_load_factor_not_a_product():
    with store_with(BASE_HISTORY, readiness_rows=LOW_READINESS) as store:
        without = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
        )
        with_deload = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            deload_decision=DECISION,
        )
    low_load = next(i.load_kg for i in without.items if i.exercise_id == "trap_bar_deadlift")
    deloaded = next(i.load_kg for i in with_deload.items if i.exercise_id == "trap_bar_deadlift")
    assert deloaded == low_load
    assert with_deload.items[0].rir_target <= 4


def test_deload_rir_cap_keeps_primary_compounds_in_window():
    with store_with(BASE_HISTORY, readiness_rows=LOW_READINESS) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            deload_decision=DECISION,
        )
    assert not prescription.issues
    for item in prescription.items:
        if item.exercise_id in {"trap_bar_deadlift", "bench_press_narrow"}:
            assert 1 <= item.rir_target <= 4


def test_deload_does_not_undo_mrv_cap():
    rows = BASE_HISTORY + [
        {"Date": "2024-01-14", "Exercise": "Pull-ups (wide grip)",
         "Weight_Used": "0", "RIR": "2", "Reps_Done": "8"}
        for _ in range(14)
    ]
    with store_with(rows) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            deload_decision=DECISION,
        )
    pull = next(i for i in prescription.items if i.exercise_id == "pull_up")
    assert pull.sets == 1


def test_minimum_note_is_after_deload_not_before_it():
    with store_with(BASE_HISTORY) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            minimum_session=True, minimum_target_minutes=30,
            deload_decision=DECISION,
        )
    note = prescription.notes["minimum_session"]
    assert note["after_minutes"] == estimate_minutes(prescription.items)
    assert "MOD-DELOAD-001" in " ".join(prescription.warnings)
