"""The deterministic prescription engine.

The acceptance criterion (V0-SCOPE §4.4) is executability: every load is a real multiple of an
available increment, every main-lift RIR is inside its window, no erector work on the hinge
day, and the weekly spinal cost stays inside the cap. These tests pin that, plus the two
honesty rules: no look-ahead, and no invented load when the e1RM is missing.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
import yaml

from conftest import make_readiness, make_training
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.prescribe import (
    DayTemplate,
    TemplateError,
    Thresholds,
    build_prescription,
    loads,
    validate_references,
)
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer


@contextmanager
def store_with(rows, readiness_rows=None):
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection,
            training,
            readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def week_sessions(*dates: str, exercise: str = "Competition Deadlift", reps: str = "5"):
    return [
        {"Date": date, "Exercise": exercise, "Weight_Used": "150", "RIR": "2", "Reps_Done": reps}
        for date in dates
    ]


BASE_HISTORY = [
    {"Date": "2024-01-01", "Exercise": "Competition Deadlift", "Weight_Used": "150", "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90", "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5", "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30", "RIR": "3", "Reps_Done": "8"},
]


# --- load arithmetic -------------------------------------------------------


def test_solve_load_inverts_the_e1rm_formula():
    e1rm = e1rm_mod.epley_rir_adjusted(150, 5, 2)
    solved = loads.solve_load(e1rm, reps=3, rir=2, increment_kg=0.5)
    # Forward check: the solved load must reproduce (at most) the target e1RM.
    assert solved <= e1rm_mod.load_for_reps(e1rm, 3, 2)
    assert e1rm_mod.epley_rir_adjusted(solved, 3, 2) <= e1rm + 1e-9


def test_rounding_never_goes_up():
    assert loads.round_down(158.57, 0.5) == 158.5
    assert loads.round_down(158.0, 0.5) == 158.0
    assert loads.round_down(0.3, 0.5) == 0.0


def test_multiple_check_survives_float_arithmetic():
    assert loads.is_multiple_of(158.5, 0.5)
    assert not loads.is_multiple_of(158.3, 0.5)
    assert loads.is_multiple_of(2.5, 0.5)


# --- config and templates --------------------------------------------------


def test_thresholds_come_from_config():
    thresholds = Thresholds.load()
    assert thresholds.increment_kg == 0.5      # the athlete's microplates
    assert thresholds.rounding == "down"
    assert thresholds.fatigue_load_multiplier == 0.95


def test_unsupported_rounding_mode_is_rejected(tmp_path):
    path = tmp_path / "thresholds.yaml"
    path.write_text(yaml.safe_dump({"load": {"rounding": "up"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported rounding"):
        Thresholds.load(path)


def test_day_b_template_has_no_erector_work():
    template = DayTemplate.load("B")
    exercises = [e for slot in template.slots for e in slot.exercises]
    assert "back_extension" not in exercises          # PRG-SCHED-001
    assert set(exercises) == {
        "trap_bar_deadlift", "bench_press_narrow", "bench_press_pause",
        "lateral_raise", "split_squat",
    }
    assert template.rep_ranges()["lateral_raise"] == (10, 12)
    assert template.time_cap_s == 4800


def test_template_without_prescription_block_is_rejected(tmp_path):
    path = tmp_path / "days.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": "1.0.0", "days": {"B": {"required_lifts": []}}}),
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="no prescription block"):
        DayTemplate.load("B", path)


def test_template_with_a_typo_in_reps_is_rejected(tmp_path):
    path = tmp_path / "days.yaml"
    path.write_text(
        yaml.safe_dump({
            "schema_version": "1.0.0",
            "days": {"B": {"prescription": {"slots": [
                {"id": "x", "exercise": "trap_bar_deadlift", "sets": 3,
                 "reps": {"low": 5, "high": 3}, "rir": {"low": 2, "high": 3}}
            ]}}},
        }),
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="reps.low > reps.high"):
        DayTemplate.load("B", path)


# --- the engine ------------------------------------------------------------


def test_engine_builds_an_executable_prescription():
    with store_with(BASE_HISTORY) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01")

    assert prescription.executable, prescription.issues
    assert [item.exercise_id for item in prescription.items][0] == "trap_bar_deadlift"
    assert all(item.load_kg is not None for item in prescription.items)
    for item in prescription.items:
        assert loads.is_multiple_of(item.load_kg, 0.5)
        assert item.rir_target == 2
        assert item.rationale_refs


def test_stale_e1rm_falls_back_to_the_last_working_load():
    # History older than the 84-day window: no e1RM, but a real load was managed before.
    rows = [
        {"Date": "2023-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2023-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "90",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2023-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
         "RIR": "2", "Reps_Done": "10"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01",
                                          session_day="A")

    assert prescription.executable, prescription.issues
    squat = next(i for i in prescription.items if i.exercise_id == "ssb_squat")
    assert squat.load_kg == 100.0
    assert any("no e1RM" in warning for warning in prescription.warnings)


def test_bodyweight_work_without_history_starts_at_bodyweight():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
         "RIR": "2", "Reps_Done": "10"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01",
                                          session_day="A")

    erector = next(i for i in prescription.items if i.exercise_id == "back_extension")
    assert erector.load_kg == 0.0
    assert erector.load_basis == "bodyweight_total"
    assert any("starting at bodyweight" in warning for warning in prescription.warnings)


def test_engine_does_not_look_ahead():
    with store_with(BASE_HISTORY) as store:
        before = build_prescription(store.connection, for_date="2024-02-01")

    future = BASE_HISTORY + [
        {"Date": "2024-03-01", "Exercise": "Competition Deadlift",
         "Weight_Used": "300", "RIR": "2", "Reps_Done": "1"},
    ]
    with store_with(future) as store:
        after = build_prescription(store.connection, for_date="2024-02-01")

    # A monster single in the future must not change today's load.
    assert [i.load_kg for i in before.items] == [i.load_kg for i in after.items]


def test_fatigue_modifier_reduces_loads_and_cites_readiness():
    with store_with(BASE_HISTORY, readiness_rows=[{"Date": "2024-02-01", "Sleep": "2"}]) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01")
        context = RuleContext.from_store(store.connection, end="2024-02-01")
        assert not validate_references(prescription, context, store.connection)

    assert prescription.fallback_level == "fatigue_reduced"
    assert any("MOD-FAT-001" in warning for warning in prescription.warnings)
    for item in prescription.items:
        assert "MOD-FAT-001" in item.rationale_refs
        assert "readiness:2024-02-01" in item.rationale_refs
        assert loads.is_multiple_of(item.load_kg, 0.5)


def test_a_missing_e1rm_is_reported_not_invented():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press",
         "Weight_Used": "90", "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01")

    bench = next(i for i in prescription.items if i.exercise_id.startswith("bench_press"))
    assert bench.load_kg is None
    assert "no usable e1RM" in bench.unknown_load_reason
    assert not prescription.executable
    assert any(issue.startswith("NO_LOAD:") for issue in prescription.issues)


def test_two_hinge_exposures_in_one_week_break_the_spinal_cap():
    # Q8 default: one exposure = exercise x session, weighted 2 per hinge session. A hinge
    # already trained on Monday plus the proposed Day B on Friday is 4 against a cap of 3.
    history = week_sessions("2024-01-29")
    with store_with(history) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-02")
        assert not prescription.executable
        assert any(issue.startswith("SPINAL_CAP:") for issue in prescription.issues)


def test_a_hinge_in_a_previous_week_does_not_consume_this_weeks_cap():
    history = week_sessions("2024-01-22")   # previous ISO week
    with store_with(history) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-29")
    assert not any(issue.startswith("SPINAL_CAP:") for issue in prescription.issues)


def test_variant_choice_prefers_the_most_recently_trained():
    rows = BASE_HISTORY + [
        {"Date": "2024-01-20", "Exercise": "Bench Press (2s pause)",
         "Weight_Used": "80", "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01")
    bench = next(i for i in prescription.items if i.exercise_id.startswith("bench_press"))
    assert bench.exercise_id == "bench_press_pause"


def test_accessories_progress_by_double_progression():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Lateral Raise",
         "Weight_Used": "12.5", "RIR": "2", "Reps_Done": "12"},   # top of 10-12 at RIR 2
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01")
    lateral = next(i for i in prescription.items if i.exercise_id == "lateral_raise")
    assert lateral.load_kg == 13.0
    assert "PRG-DP-001" in lateral.rationale_refs


def test_every_rationale_reference_resolves():
    with store_with(BASE_HISTORY) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01")
        context = RuleContext.from_store(store.connection, end="2024-02-01")
        assert validate_references(prescription, context, store.connection) == []
