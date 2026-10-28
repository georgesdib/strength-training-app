"""The deterministic prescription engine.

The acceptance criterion (V0-SCOPE §4.4) is executability: every load is a real multiple of an
available increment, every main-lift RIR is inside its window, no erector work on the hinge
day, and the weekly spinal cost stays inside the cap. These tests pin that, plus the two
honesty rules: no look-ahead, and no invented load when the e1RM is missing.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest
import yaml
from conftest import make_readiness, make_training

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.prescribe import (
    SessionTemplate,
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


def week_sessions(*dates: str, exercise: str = "Trap Bar Deadlift", reps: str = "5"):
    return [
        {"Date": date, "Exercise": exercise, "Weight_Used": "150", "RIR": "2", "Reps_Done": reps}
        for date in dates
    ]


BASE_HISTORY = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90", "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5", "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30", "RIR": "3", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Pull-ups (wide grip)", "Weight_Used": "0", "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Dumbbell Row", "Weight_Used": "30", "RIR": "2", "Reps_Done": "10"},
    # DEC-KNEEFLEX-01: the knee-flexion accessory needs history or the session is not executable.
    {"Date": "2024-01-01", "Exercise": "Lying Leg Curls", "Weight_Used": "30", "RIR": "2", "Reps_Done": "10"},
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
    template = SessionTemplate.load("hinge")
    exercises = [e for slot in template.slots for e in slot.exercises]
    assert "back_extension" not in exercises          # PRG-SCHED-001
    assert set(exercises) == {
        "trap_bar_deadlift", "bench_press_narrow", "bench_press_pause",
        "split_squat", "pull_up", "lat_pulldown", "dumbbell_row",
        "lying_leg_curls", "nordic_curl",
    }
    assert template.rep_ranges()["split_squat"] == (8, 10)
    assert template.time_cap_s == 4800


def test_template_without_prescription_block_is_rejected(tmp_path):
    path = tmp_path / "session-types.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": "1.0.0",
                        "session_types": {"hinge": {"required_lifts": []}}}),
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="no prescription block"):
        SessionTemplate.load("hinge", path)


def test_template_with_a_typo_in_reps_is_rejected(tmp_path):
    path = tmp_path / "session-types.yaml"
    path.write_text(
        yaml.safe_dump({
            "schema_version": "1.0.0",
            "session_types": {"hinge": {"prescription": {"slots": [
                {"id": "x", "exercise": "trap_bar_deadlift", "sets": 3,
                 "reps": {"low": 5, "high": 3}, "rir": {"low": 2, "high": 3}}
            ]}}},
        }),
        encoding="utf-8",
    )
    with pytest.raises(TemplateError, match="reps.low > reps.high"):
        SessionTemplate.load("hinge", path)


# --- the engine ------------------------------------------------------------


def test_engine_builds_an_executable_prescription():
    with store_with(BASE_HISTORY) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08")

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
        {"Date": "2024-01-07", "Exercise": "Dumbbell Row", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "10"},
        {"Date": "2024-01-07", "Exercise": "Lying Leg Curls", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "10"},
        # A recent session for a lift the test does not inspect, so the gap is not the variable
        # under test (continuity is covered in test_continuity.py).
        {"Date": "2024-01-07", "Exercise": "Competition Bench Press", "Weight_Used": "90",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08",
                                          session_type="squat")

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
        prescription = build_prescription(store.connection, for_date="2024-01-08",
                                          session_type="squat")

    erector = next(i for i in prescription.items if i.exercise_id == "back_extension")
    assert erector.load_kg == 0.0
    assert erector.load_basis == "bodyweight_total"
    assert any("starting at bodyweight" in warning for warning in prescription.warnings)


def test_engine_does_not_look_ahead():
    with store_with(BASE_HISTORY) as store:
        before = build_prescription(store.connection, for_date="2024-01-08")

    future = BASE_HISTORY + [
        {"Date": "2024-03-01", "Exercise": "Trap Bar Deadlift",
         "Weight_Used": "300", "RIR": "2", "Reps_Done": "1"},
    ]
    with store_with(future) as store:
        after = build_prescription(store.connection, for_date="2024-01-08")

    # A monster single in the future must not change today's load.
    assert [i.load_kg for i in before.items] == [i.load_kg for i in after.items]


def test_fatigue_modifier_reduces_loads_and_cites_readiness():
    with store_with(BASE_HISTORY, readiness_rows=[{"Date": "2024-01-08", "Sleep": "2"}]) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08")
        context = RuleContext.from_store(store.connection, end="2024-01-08")
        assert not validate_references(prescription, context, store.connection)

    assert prescription.fallback_level == "fatigue_reduced"
    assert any("MOD-FAT-001" in warning for warning in prescription.warnings)
    for item in prescription.items:
        assert "MOD-FAT-001" in item.rationale_refs
        assert "readiness:2024-01-08" in item.rationale_refs
        assert loads.is_multiple_of(item.load_kg, 0.5)


def test_a_missing_e1rm_is_reported_not_invented():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press",
         "Weight_Used": "90", "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08")

    bench = next(i for i in prescription.items if i.exercise_id.startswith("bench_press"))
    assert bench.load_kg is None
    assert "no usable e1RM" in bench.unknown_load_reason
    assert not prescription.executable
    assert any(issue.startswith("NO_LOAD:") for issue in prescription.issues)


def test_four_hinge_exposures_in_one_week_break_the_spinal_cap():
    # One exposure = exercise x session, weighted 2 per hinge session. Three performed
    # sessions (6) plus the proposed Friday session (2) exceed the raised cap of 6.
    history = week_sessions("2024-01-29", "2024-01-30", "2024-01-31")
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
        {"Date": "2024-01-05", "Exercise": "Bench Press (2s pause)",
         "Weight_Used": "80", "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08")
    bench = next(i for i in prescription.items if i.exercise_id.startswith("bench_press"))
    assert bench.exercise_id == "bench_press_pause"


def test_accessories_progress_by_double_progression():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Dumbbell Row",
         "Weight_Used": "12.5", "RIR": "2", "Reps_Done": "12"},   # top of 8-12 at RIR 2
    ]
    with store_with(rows) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="bench_squat"
        )
    row = next(i for i in prescription.items if i.exercise_id == "dumbbell_row")
    assert row.load_kg == 13.0
    assert "PRG-DP-001" in row.rationale_refs


def test_core_work_is_prescribed_on_the_strength_days_only():
    # DEC-CORE-01 / docs/CORE-TRAINING.md: two reps-based core slots, never on the hinge day,
    # and never time-based (progressing a plank "top of range" would mean holding longer).
    squat = [e for slot in SessionTemplate.load("squat").slots for e in slot.exercises]
    bench_squat = [e for slot in SessionTemplate.load("bench_squat").slots
                    for e in slot.exercises]
    bench_hinge = [e for slot in SessionTemplate.load("bench_hinge").slots
                    for e in slot.exercises]
    assert "ab_wheel" in squat and "ab_wheel" in bench_squat
    assert "hanging_leg_raise" in bench_hinge
    assert "ab_wheel" not in bench_hinge and "hanging_leg_raise" not in squat
    assert "plank" not in squat + bench_squat + bench_hinge


def test_rep_ranges_are_pooled_across_every_day():
    # PRG-DP-001 scopes the whole accessory collection; a per-day map left it unassessable
    # (OPEN-QUESTIONS Q16, now answered).
    from strength_coach.prescribe import templates

    ranges = templates.all_rep_ranges()
    assert {"back_extension", "split_squat", "ab_wheel", "hanging_leg_raise"} <= set(ranges)


def test_double_progression_is_assessable_on_every_day():
    rows = BASE_HISTORY + [
        {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "10",
         "RIR": "2", "Reps_Done": "12"},
        {"Date": "2024-01-01", "Exercise": "Ab Wheel", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "8"},
        {"Date": "2024-01-01", "Exercise": "Hanging Leg Raise", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "10"},
        {"Date": "2024-01-01", "Exercise": "Pull-ups (wide grip)", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "8"},
    ]
    with store_with(rows) as store:
        for session_type in ("squat", "hinge", "bench_squat", "bench_hinge"):
            prescription = build_prescription(
                store.connection, for_date="2024-01-08", session_type=session_type
            )
            assert not any(
                "PRG-DP-001 not assessable" in warning for warning in prescription.warnings
            ), session_type


def test_every_rationale_reference_resolves():
    with store_with(BASE_HISTORY) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08")
        context = RuleContext.from_store(store.connection, end="2024-02-01")
        assert validate_references(prescription, context, store.connection) == []


def test_vertical_pull_slot_accepts_pull_up_or_lat_pulldown():
    # DEC-PULL-02: the slot is a variant; the most recently trained option wins and the
    # loads are never compared between them.
    rows = BASE_HISTORY + [
        {"Date": "2024-01-03", "Exercise": "Lat Pulldown", "Weight_Used": "60",
         "RIR": "2", "Reps_Done": "10"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08")
    pull = next(
        item for item in prescription.items
        if item.exercise_id in {"pull_up", "lat_pulldown"}
    )
    assert pull.exercise_id == "lat_pulldown"
    # 10 reps at RIR 2 is the top of the range, so the double-progression rule adds 0.5 kg.
    assert pull.load_kg == 60.5


def test_day_a_opens_with_power_work_and_no_load_progression_citation():
    rows = BASE_HISTORY + [
        {"Date": "2024-01-01", "Exercise": "Box Jumps", "Weight_Used": "0",
         "RIR": "4", "Reps_Done": "4"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="squat"
        )

    first = prescription.items[0]
    assert first.exercise_id == "box_jump"
    assert first.load_basis == "bodyweight_total"
    assert first.rationale_refs == ()          # power is intent, not a rule
    assert any("power work" in warning for warning in prescription.warnings)


def test_power_slot_ignores_external_load_history():
    rows = BASE_HISTORY + [
        {"Date": "2024-01-01", "Exercise": "Box Jumps", "Weight_Used": "20",
         "RIR": "4", "Reps_Done": "4"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="squat"
        )

    first = prescription.items[0]
    assert first.exercise_id == "box_jump"
    assert first.load_kg == 0.0
    assert first.load_basis == "bodyweight_total"
    assert "PRG-DP-001" not in first.rationale_refs
    assert "MOD-E1RM-001" not in first.rationale_refs


def test_recent_stress_is_attached_as_an_advisory_only():
    rows = BASE_HISTORY + [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(10)
    ]
    with store_with(rows) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-02", session_type="squat"
        )

    stress = prescription.notes["recent_stress"]["ssb_squat"]
    assert stress["status"] == "high"
    assert any("recent stress: ssb_squat high" in w for w in prescription.warnings)
    # The advisory did not add a load modifier or a rule citation.
    assert not any("MOD-FAT" in ref for item in prescription.items for ref in item.rationale_refs)


def test_selection_b_requires_confirmation():
    from unittest.mock import patch

    from strength_coach.prescribe import selection as selection_mod

    def fake_select(conn, context, on_date, day, **kwargs):
        return [selection_mod.SlotSelection(
            slot_id="bench_main",
            current="bench_press_narrow",
            suggested="bench_press_pause",
            changed=True,
            source="python",
            reason="test substitution",
            candidates=(),
            comparison_class="B",
            requires_confirmation=True,
        )]

    rows = BASE_HISTORY + [
        {"Date": "2024-01-08", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with (
        store_with(rows) as store,
        patch("strength_coach.prescribe.engine.selection_mod.select", fake_select),
    ):
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            apply_selection=True,
        )
    ids = {item.exercise_id for item in prescription.items}
    assert "bench_press_pause" not in ids
    assert "bench_press_narrow" in ids
    assert any("requires confirmation" in warning for warning in prescription.warnings)
    assert prescription.notes["selection"]["applied"] is False
    assert prescription.notes["selection"]["requested"] is True


def test_selection_c_is_never_automatic():
    from strength_coach.prescribe import selection as selection_mod

    def fake_select(conn, context, on_date, day, **kwargs):
        return [selection_mod.SlotSelection(
            slot_id="accessory_pull_up",
            current="lat_pulldown",
            suggested="pull_up",
            changed=True,
            source="python",
            reason="test substitution",
            candidates=(),
            comparison_class="C",
            requires_confirmation=True,
        )]

    rows = BASE_HISTORY + [
        {"Date": "2024-01-08", "Exercise": "Lat Pulldown", "Weight_Used": "60",
         "RIR": "2", "Reps_Done": "10"},
    ]
    with store_with(rows) as store:
        from unittest.mock import patch
        with patch("strength_coach.prescribe.engine.selection_mod.select", fake_select):
            prescription = build_prescription(
                store.connection, for_date="2024-01-15", session_type="hinge",
                apply_selection=True, selection_confirmed=True,
            )
        assert "pull_up" not in {item.exercise_id for item in prescription.items}
        assert "lat_pulldown" in {item.exercise_id for item in prescription.items}
        assert any("different lift/load basis" in warning for warning in prescription.warnings)
        assert prescription.notes["selection"]["slots"][0]["blocked_reason"]
        assert prescription.notes["selection"]["applied"] is False


def test_per_lift_readiness_can_only_lower_a_load():
    rows = BASE_HISTORY + [
        {"Date": "2024-01-06", "Exercise": "Trap Bar Deadlift", "Weight_Used": "100",
         "RIR": "0", "Reps_Done": "5"},
    ]
    readiness = [{"Date": "2024-01-08", "Sleep": "4", "Energy": "4", "Mood": "4",
                  "Stress": "4", "Soreness": "4"}]
    with store_with(rows, readiness_rows=readiness) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="hinge"
        )

    entry = prescription.notes["per_lift_readiness"]["trap_bar_deadlift"]
    assert entry["score"] < 0.8
    assert any("MOD-FAT-001" in warning for warning in prescription.warnings)
    assert any("per-lift readiness applied" in warning for warning in prescription.warnings)


def test_apply_selection_rebuilds_the_item_and_cites_mod_select(monkeypatch):
    from strength_coach.prescribe import selection as selection_mod
    from strength_coach.prescribe.engine import validate_references

    def fake_select(conn, context, on_date, day, **kwargs):
        return [selection_mod.SlotSelection(
            slot_id="bench_main",
            current="bench_press_narrow",
            suggested="bench_press_pause",
            changed=True,
            source="python",
            reason="test substitution",
            candidates=(),
            comparison_class="B",
            requires_confirmation=True,
        )]

    monkeypatch.setattr("strength_coach.prescribe.engine.selection_mod.select", fake_select)
    rows = BASE_HISTORY + [
        {"Date": "2024-01-08", "Exercise": "Lat Pulldown", "Weight_Used": "60",
         "RIR": "2", "Reps_Done": "10"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            apply_selection=True, selection_confirmed=True,
        )
        item = next(i for i in prescription.items if i.exercise_id == "bench_press_pause")
        assert "MOD-SELECT-001" in item.rationale_refs
        assert prescription.notes["selection"]["applied"] is True
        assert prescription.notes["selection"]["slots"][0]["applied"] is True
        context = RuleContext.from_store(store.connection, end="2024-01-15")
        assert validate_references(prescription, context, store.connection) == []


def test_poor_readiness_reduces_accessory_sets_by_default():
    rows = BASE_HISTORY
    readiness = [{"Date": "2024-01-02", "Sleep": "1", "Energy": "1",
                  "Mood": "1", "Soreness": "1", "Stress": "1"}]
    with store_with(rows, readiness_rows=readiness) as store:
        plain = build_prescription(store.connection, for_date="2024-01-02", session_type="squat")
    with store_with(rows, readiness_rows=readiness) as store:
        # The same date with a deliberately disabled valve is the control.
        from strength_coach.features import readiness as readiness_mod
        cfg = readiness_mod.ReadinessConfig.load()
        cfg = replace(cfg, set_reduction_enabled=False)
        control = build_prescription(
            store.connection, for_date="2024-01-02", session_type="squat",
            readiness_config=cfg,
        )
    plain_sets = {i.exercise_id: i.sets for i in plain.items}
    control_sets = {i.exercise_id: i.sets for i in control.items}
    accessory = next(i for i in plain.items if not i.essential)
    main = next(i for i in plain.items if i.essential)
    assert plain_sets[accessory.exercise_id] == control_sets[accessory.exercise_id] - 1
    assert plain_sets[main.exercise_id] == control_sets[main.exercise_id]
    assert "sets reduced" in " ".join(plain.warnings)


def test_main_lift_reduction_requires_explicit_opt_in():
    rows = BASE_HISTORY
    readiness = [{"Date": "2024-01-02", "Sleep": "1", "Energy": "1",
                  "Mood": "1", "Soreness": "1", "Stress": "1"}]
    with store_with(rows, readiness_rows=readiness) as store:
        from strength_coach.features import readiness as readiness_mod
        cfg = replace(
            readiness_mod.ReadinessConfig.load(),
            set_reduction_include_essential=True,
        )
        opted_in = build_prescription(
            store.connection, for_date="2024-01-02", session_type="squat",
            readiness_config=cfg,
        )
    main = next(i for i in opted_in.items if i.essential)
    assert "sets reduced" in " ".join(opted_in.warnings)
    assert main.sets < 5


def test_main_lifts_carry_a_standardised_warmup_ramp():
    with store_with(BASE_HISTORY) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
        )
    main = next(item for item in prescription.items if item.essential and item.load_kg)
    assert [w.percent for w in main.warmup] == [0.50, 0.70, 0.85]
    assert [w.reps for w in main.warmup] == [5, 3, 2]
    assert all(0 < w.load_kg <= main.load_kg for w in main.warmup)
    accessory = next(item for item in prescription.items if not item.essential)
    assert accessory.warmup == ()


def test_minimum_session_is_optional_volume_only_and_keeps_main_lifts_by_default():
    with store_with(BASE_HISTORY) as store:
        normal = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
        )
    with store_with(BASE_HISTORY) as store:
        minimum = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            minimum_session=True, minimum_target_minutes=30,
        )
    note = minimum.notes.get("minimum_session")
    assert note is not None
    assert note["requested"] is True
    by_normal = {item.exercise_id: item for item in normal.items}
    for item in minimum.items:
        original = by_normal[item.exercise_id]
        assert item.load_kg == original.load_kg
        assert item.rir_target == original.rir_target
        if item.essential:
            assert item.sets == original.sets
    assert "MOD-MIN-001" in " ".join(minimum.warnings)


def test_minimum_session_refuses_a_hard_constraint_veto():
    from strength_coach.store import repositories

    with store_with(BASE_HISTORY) as store:
        repositories.append_athlete_constraint(
            store.connection, kind="injury", region="low_back", severity="hard_exclude",
            forbidden_exercises=["trap_bar_deadlift"],
        )
        minimum = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
            minimum_session=True, minimum_target_minutes=30,
        )
    note = minimum.notes["minimum_session"]
    assert note["status"] == "unavailable"
    assert note["applied"] is False
    assert "CONSTRAINT_VETO" in note["reason"]


def test_profile_max_session_minutes_consumes_planned_cap_without_cutting_sets():
    from strength_coach.store import repositories

    with store_with(BASE_HISTORY) as store:
        repositories.append_athlete_profile(
            store.connection, effective_from="2024-01-01", primary_goal="strength",
            goal_rank=["strength"], focus_lifts=["ssb_squat"],
            sessions_per_week_target=3, max_session_minutes=45,
        )
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
        )
    assert prescription.time_cap_s == 45 * 60
    assert prescription.notes["session_time"]["planned_minutes"] == 45
    assert prescription.notes["session_time"]["hard_ceiling_minutes"] == 90
    assert any("session time" in warning for warning in prescription.warnings)


def test_e1rm_source_width_is_exposed_on_the_item():
    rows = week_sessions("2024-01-01", "2024-01-03")
    with store_with(rows) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="hinge"
        )
    item = next(i for i in prescription.items if i.exercise_id == "trap_bar_deadlift")
    assert item.e1rm_source_sets == 2
    assert not any("one eligible set" in warning for warning in prescription.warnings)


# --- MOD-SPINE-001: trim non-essential spinal work -------------------------


def test_weighted_spinal_cost_keeps_a_fitting_nonessential_exposure():
    # The weighted policy lowers the same exposures enough that the squat session fits; the
    # erector slot stays because the effective weekly cost no longer exceeds the cap.
    history = [
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "12"},
        {"Date": "2024-01-02", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-02", "Exercise": "Back Extension", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "12"},
        # The squat session needs its own e1RM and its accessories need history, or it would
        # be rejected for NO_LOAD before the spinal question is reached.
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "120",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "90",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Dumbbell Row", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "10"},
        {"Date": "2024-01-01", "Exercise": "Lying Leg Curls", "Weight_Used": "30",
         "RIR": "2", "Reps_Done": "10"},
    ]
    with store_with(history) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-03", session_type="squat"
        )

    assert prescription.executable
    assert any(item.exercise_id == "back_extension" for item in prescription.items)
    assert prescription.notes["spinal_trim"]["applied"] is False
    assert prescription.notes["spinal_cap"]["cost"] <= prescription.notes["spinal_cap"]["cap"]


def test_the_spinal_veto_survives_when_essential_work_causes_the_overage():
    # Three performed hinge sessions already cost 6. A fourth in the same week cannot be
    # fixed by dropping an accessory: the trap bar is essential, so the veto must stand and
    # the issue must name the exposures.
    history = [
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-02", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-03", "Exercise": "Back Extension", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "12"},
        {"Date": "2024-01-03", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(history) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-04", session_type="hinge"
        )

    assert not prescription.executable
    assert prescription.notes["spinal_trim"]["applied"] is False
    cap_issues = [issue for issue in prescription.issues if issue.startswith("SPINAL_CAP:")]
    assert cap_issues
    assert "trap_bar_deadlift" in cap_issues[0]
    assert "back_extension" in cap_issues[0]
