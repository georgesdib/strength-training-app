"""Continuity: a gap in training changes the prescription, and says so."""

from __future__ import annotations

from contextlib import contextmanager

from conftest import make_readiness, make_training
from strength_coach.prescribe import build_prescription
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
]


@contextmanager
def store_with(rows=ROWS, block_start=None):
    training = make_training(rows)
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
                store.connection, effective_from=block_start,
                primary_goal="longevity", goal_rank=["longevity", "strength"],
                focus_lifts=[], block_start_date=block_start,
            )
        yield store
    finally:
        store.close()


def item(prescription, exercise_id):
    return next(i for i in prescription.items if i.exercise_id == exercise_id)


def test_no_gap_leaves_the_session_alone():
    with store_with() as store:
        prescription = build_prescription(store.connection, for_date="2024-01-02",
                                          session_day="A")

    squat = item(prescription, "ssb_squat")
    assert squat.rir_target == 2
    assert "MOD-GAP-001" not in squat.rationale_refs
    assert prescription.notes["gap_days"] == 1


def test_a_short_gap_adds_one_rir_but_keeps_the_load():
    with store_with() as store:
        prescription = build_prescription(store.connection, for_date="2024-01-22",
                                          session_day="A")

    squat = item(prescription, "ssb_squat")
    assert squat.load_kg == 105.5
    assert squat.rir_target == 3
    assert "MOD-GAP-001" in squat.rationale_refs
    assert prescription.notes["gap_band"] == "short"
    assert any("21-day gap" in warning for warning in prescription.warnings)


def test_a_medium_gap_reduces_the_load():
    with store_with() as store:
        prescription = build_prescription(store.connection, for_date="2024-02-05",
                                          session_day="A")

    squat = item(prescription, "ssb_squat")
    assert squat.load_kg == 100.0          # 105.5 * 0.95 = 100.225, rounded down
    assert squat.rir_target == 3
    assert prescription.fallback_level == "fatigue_reduced"


def test_bodyweight_work_loses_a_set_instead_of_load():
    rows = ROWS + [
        {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "12"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-05",
                                          session_day="A")

    erector = item(prescription, "back_extension")
    assert erector.load_kg == 0.0
    assert erector.sets == 2               # was 3
    assert "MOD-GAP-001" in erector.rationale_refs


def test_missed_weeks_do_not_advance_the_cycle():
    rows = ROWS + [
        {"Date": "2024-01-15", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows, block_start="2024-01-01") as store:
        context = RuleContext.from_store(store.connection, end="2024-01-16")
        prescription = build_prescription(store.connection, for_date="2024-01-16",
                                          session_day="A")

    # Weeks 1 and 3 were trained; that is two trained weeks, not three calendar weeks.
    assert context.block_week_index == 2
    assert prescription.notes["undulation_week"] == 2


def test_a_measured_test_counts_as_a_trained_week():
    with store_with(block_start="2024-01-01") as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=154,
            effective_from="2024-01-08", source="measured", reason="3RM test",
        )
        context = RuleContext.from_store(conn, end="2024-01-09")

    assert context.block_week_index == 2   # week 1 session + week 2 test
