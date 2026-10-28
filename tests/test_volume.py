"""Volume landmarks and the conservative MRV cap."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from strength_coach.features import volume
from strength_coach.prescribe.engine import _apply_under_mev, _apply_volume_cap
from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.rules import RuleContext
from strength_coach.utils import exercises


def _item(sets=3, essential=False):
    return PrescriptionItem(
        order_index=0, exercise_id="dumbbell_row", sets=sets, reps_low=8,
        reps_high=12, load_kg=20.0, load_basis="external",
        rounding_increment_kg=0.5, rir_target=2, rest_s=90, essential=essential,
    )


def test_mrv_cap_trims_only_non_essential_sets():
    rows = pd.DataFrame([
        {"date": pd.Timestamp("2026-10-14"), "exercise_id": "dumbbell_row",
         "is_working_set": True}
    ] * 10)
    context = RuleContext(
        sets=rows, sessions=pd.DataFrame(), entities=exercises.taxonomy().entities,
    )
    items, warnings, note = _apply_volume_cap(
        context, (_item(),), "2026-10-20"
    )
    assert items[0].sets == 2
    assert "MOD-VOL-001" in items[0].rationale_refs
    assert note["applied"] is True
    assert any("MOD-VOL-001" in warning for warning in warnings)


def test_mrv_cap_never_cuts_an_essential_item():
    rows = pd.DataFrame([
        {"date": pd.Timestamp("2026-10-14"), "exercise_id": "dumbbell_row",
         "is_working_set": True}
    ] * 20)
    context = RuleContext(
        sets=rows, sessions=pd.DataFrame(), entities=exercises.taxonomy().entities,
    )
    items, warnings, _ = _apply_volume_cap(
        context, (_item(essential=True),), "2026-10-20"
    )
    assert items[0].sets == 3
    assert any("no non-essential sets" in warning for warning in warnings)


def test_under_mev_adds_one_accessory_set():
    from strength_coach.prescribe.engine import _apply_under_mev

    rows = pd.DataFrame([
        {"date": pd.Timestamp("2026-10-14"), "exercise_id": "dumbbell_row",
         "is_working_set": True}
    ])
    context = RuleContext(
        sets=rows, sessions=pd.DataFrame(), entities=exercises.taxonomy().entities,
    )
    items, warnings, note = _apply_under_mev(
        context, (_item(sets=3),), "2026-10-20"
    )
    assert items[0].sets == 4
    assert "MOD-VOL-002" in items[0].rationale_refs
    assert note["applied"] is True
    assert any("under-MEV" in warning for warning in warnings)

# --- Ledger grouping (DEC-VOLUME-05) ---------------------------------------

WEEKS = ("2026-10-05", "2026-10-12", "2026-10-19")


def _frame(rows):
    return pd.DataFrame([
        {"date": pd.Timestamp(day), "exercise_id": exercise_id, "is_working_set": True}
        for day, exercise_id in rows
    ])


def _context(rows):
    return RuleContext(
        sets=_frame(rows), sessions=pd.DataFrame(), entities=exercises.taxonomy().entities,
    )


def _volume_item(exercise_id, sets=3):
    return PrescriptionItem(
        order_index=0, exercise_id=exercise_id, sets=sets, reps_low=8, reps_high=12,
        load_kg=10.0, load_basis="external", rounding_increment_kg=0.5, rir_target=2,
        rest_s=90, essential=False,
    )


def _three_week_report(rows):
    return volume.compute(
        _frame(rows), on_date="2026-10-20",
        config=replace(volume.VolumeConfig.load(), window_weeks=3),
    )


def test_the_ledger_judges_the_landmark_group_not_the_sub_pattern():
    # hanging_leg_raise alone is below core's MEV of 3, but the core *group* is not. Judging
    # the raw pattern against a merged landmark is what let a low core_flexion add a set to a
    # well-trained ab_wheel; the status now belongs to the group.
    rows = []
    for week in WEEKS:
        rows += [(week, "ab_wheel")] * 3 + [(week, "hanging_leg_raise")] * 2
    by_pattern = {row["pattern"]: row for row in _three_week_report(rows)["patterns"]}
    assert by_pattern["core_flexion"]["group"] == "core"
    assert by_pattern["core_flexion"]["average"] == 2.0
    assert by_pattern["core_flexion"]["group_average"] == 5.0
    assert by_pattern["core_flexion"]["status"] == "within"


def test_complete_coverage_zero_fills_and_resets_the_under_mev_clock():
    rows = [(day, "dumbbell_row") for day in ("2026-10-05", "2026-10-19") for _ in range(3)]
    complete = replace(
        volume.VolumeConfig.load(),
        window_weeks=3, ledger_coverage="complete",
    )
    observed_only = replace(complete, ledger_coverage="unknown")
    complete_report = volume.compute(_frame(rows), on_date="2026-10-20", config=complete)
    observed_report = volume.compute(_frame(rows), on_date="2026-10-20", config=observed_only)
    complete_row = next(
        row for row in complete_report["patterns"] if row["pattern"] == "horizontal_pull"
    )
    observed_row = next(
        row for row in observed_report["patterns"] if row["pattern"] == "horizontal_pull"
    )
    assert complete_report["coverage"]["denominator"] == 3
    assert complete_report["coverage"]["zero_weeks"]
    assert complete_report["coverage"]["training_weeks"] == 2
    assert complete_row["status"] == "insufficient_training"
    assert observed_report["coverage"]["denominator"] == 2
    assert observed_row["average"] > complete_row["average"]


def test_effective_accounting_credits_indirect_groups():
    rows = []
    for week in WEEKS:
        rows += [(week, "dumbbell_bench_press")] * 2
        rows += [(week, "dumbbell_row")] * 2
    hard = replace(volume.VolumeConfig.load(), window_weeks=3)
    effective = replace(hard, set_accounting="effective")
    hard_report = volume.compute(_frame(rows), on_date="2026-10-20", config=hard)
    effective_report = volume.compute(_frame(rows), on_date="2026-10-20", config=effective)
    assert all(
        row["group"] != "vertical_push" for row in hard_report["patterns"]
    )
    indirect_push = next(
        row for row in effective_report["patterns"] if row["group"] == "vertical_push"
    )
    indirect_pull = next(
        row for row in effective_report["patterns"] if row["group"] == "vertical_pull"
    )
    assert indirect_push["group_average"] == 0.5
    assert indirect_pull["group_average"] == 0.5


def test_under_mev_never_adds_a_set_to_a_sibling_pattern():
    rows = []
    for week in WEEKS:
        rows += [(week, "ab_wheel")] * 3 + [(week, "hanging_leg_raise")] * 2
    items, _warnings, note = _apply_under_mev(
        _context(rows), (_volume_item("ab_wheel"),), "2026-10-20"
    )
    assert items[0].sets == 3
    assert note["applied"] is False


def test_under_mev_adds_to_the_pattern_that_is_actually_under():
    rows = [(week, "hanging_leg_raise") for week in WEEKS]
    items, _warnings, note = _apply_under_mev(
        _context(rows), (_volume_item("hanging_leg_raise"),), "2026-10-20"
    )
    assert items[0].sets == 4
    assert "MOD-VOL-002" in items[0].rationale_refs
    assert note["changes"] == ["core:hanging_leg_raise+1"]


def test_erector_work_is_not_hinge_volume():
    # DEC-BACKEXT-02 / DEC-VOLUME-05: direct erector work has its own pattern key and no
    # landmark. It is dosed by PRG-EREC-001 and capped by PRG-SPINE-001, never counted as
    # hinge volume. This is the assertion that used to be an implication.
    rows = []
    for week in WEEKS:
        rows += [(week, "back_extension")] * 3 + [(week, "trap_bar_deadlift")] * 5
    by_pattern = {row["pattern"]: row for row in _three_week_report(rows)["patterns"]}
    assert by_pattern["erector_extension"]["group"] == "erector_extension"
    assert by_pattern["erector_extension"]["status"] == "untargeted"
    assert by_pattern["hinge"]["total"] == 15        # the trap bar only
    assert by_pattern["hinge"]["group"] == "hinge"


def test_unilateral_patterns_keep_the_documented_landmarks():
    # The mapping is asymmetric on purpose; tests make it a decision, not a fall-through.
    assert volume.volume_target_key("hinge_unilateral") == "hinge_unilateral"
    assert volume.volume_target_key("squat_unilateral") == "squat"
    assert volume.volume_target_key("erector_extension") == "erector_extension"
    # DEC-KNEEFLEX-01: a Nordic curl trains the same knee-flexion hamstring tissue as a leg
    # curl, so its sets must not fall outside the ledger.
    assert volume.volume_target_key("hamstring_eccentric") == "knee_flexion"