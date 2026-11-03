"""Step 3 engine integration: top-set structure and hinge maximal change."""

from __future__ import annotations

from contextlib import contextmanager

from conftest import make_readiness, make_training

from strength_coach.features.deload import DeloadDecision
from strength_coach.prescribe import build_prescription, loads
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
    {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-15", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
]


@contextmanager
def store_with(block_start="2024-01-01", competition_date=None):
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        repositories.append_athlete_profile(
            store.connection,
            effective_from="2024-01-01",
            block_start_date=block_start,
            competition_date=competition_date,
        )
        yield store
    finally:
        store.close()


def _item(prescription, exercise_id):
    return next(item for item in prescription.items if item.exercise_id == exercise_id)


def test_top_set_applies_to_the_session_main_and_preserves_sets() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            top_set_requested=True,
        )
    main = _item(prescription, "ssb_squat")
    assert prescription.notes["top_set"]["applied"] is True
    assert [group.role for group in main.set_groups] == ["top_set", "back_off"]
    assert sum(group.sets for group in main.set_groups) == main.sets
    assert main.set_groups[0].rir_target == 1
    assert main.set_groups[0].load_kg > main.set_groups[1].load_kg
    assert main.warmup[0].load_kg < main.load_kg


def test_deload_suppresses_top_set_and_keeps_the_plan_executable() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            top_set_requested=True,
            deload_decision=DeloadDecision(reason="test deload", trigger="test"),
        )
    main = _item(prescription, "ssb_squat")
    assert main.set_groups == ()
    assert prescription.notes["top_set"]["applied"] is False
    assert "deload" in prescription.notes["top_set"]["reason"]


def test_ask_mode_does_not_apply_without_confirmation() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="squat"
        )
    main = _item(prescription, "ssb_squat")
    assert main.set_groups == ()
    assert prescription.notes["top_set"]["applied"] is False
    assert "awaiting confirmation" in prescription.notes["top_set"]["reason"]


def test_competition_taper_removes_the_top_set() -> None:
    with store_with(competition_date="2024-01-18") as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            top_set_requested=True,
        )
    assert prescription.notes["top_set"]["applied"] is False
    assert "taper" in prescription.notes["top_set"]["reason"]


def test_warmup_uses_the_final_throttled_top_set_load() -> None:
    with store_with() as store:
        baseline = build_prescription(
            store.connection, for_date="2024-01-15", session_type="squat",
            top_set_requested=True,
        )
        throttled = build_prescription(
            store.connection, for_date="2024-01-15", session_type="squat",
            top_set_requested=True, technique_throttle=True,
        )
    base_main = _item(baseline, "ssb_squat")
    throttle_main = _item(throttled, "ssb_squat")
    expected_top = loads.round_down(
        base_main.set_groups[0].load_kg * 0.90,
        throttle_main.rounding_increment_kg,
    )
    assert throttle_main.set_groups[0].load_kg == expected_top
    assert throttle_main.warmup
    assert throttle_main.warmup[0].load_kg < throttle_main.set_groups[0].load_kg
    assert throttle_main.warmup[0].load_kg == loads.round_down(
        expected_top * 0.50, throttle_main.rounding_increment_kg
    )


def test_hinge_maximal_is_allowed_and_warned() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="hinge",
            top_set_requested=True,
        )
    trap_bar = _item(prescription, "trap_bar_deadlift")
    assert (trap_bar.reps_low, trap_bar.reps_high) == (1, 3)
    assert trap_bar.set_groups
    assert trap_bar.set_groups[0].rir_target == 1
    assert any("maximal hinge allowed" in warning for warning in prescription.warnings)
