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
