"""Active VBT target applicability and set comparison."""

from __future__ import annotations

import pytest

from strength_coach.features import vbt_analysis


def item(**overrides):
    value = {
        "order_index": 0,
        "exercise_id": "ssb_squat",
        "sets": 3,
        "reps_low": 3,
        "reps_high": 5,
        "load_kg": 100,
        "load_basis": "external",
        "rir_target": 2,
        "set_groups": [],
        "vbt": {
            "target_mps": 0.42,
            "low_mps": 0.39,
            "high_mps": 0.45,
            "rep_count": 3,
            "rir_low": 2,
            "rir_high": 3,
            "scope": "lift",
            "family": "squat",
            "n_sets": 18,
            "n_sessions": 3,
            "method_version": "1.0.0",
            "calibration_id": "vbt-test",
            "source": "computed",
        },
    }
    value.update(overrides)
    return value


def row(**overrides):
    value = {
        "set_id": 1,
        "set_index": 1,
        "exercise_id": "ssb_squat",
        "reps": 3,
        "rir": 2,
        "load_kg": 100,
        "velocity": 0.42,
        "prescription_item_index": 0,
        "set_role": None,
        "is_working_set": 1,
        "load_basis": "external",
        "flags": [],
    }
    value.update(overrides)
    return value


def test_a_comparable_set_reports_signed_and_relative_delta():
    result = vbt_analysis.compare_set([item()], row(velocity=0.44))

    assert result["comparable"] is True
    assert result["reasons"] == []
    assert result["target_mps"] == pytest.approx(0.42)
    assert result["actual_velocity_mps"] == pytest.approx(0.44)
    assert result["delta_mps"] == pytest.approx(0.02)
    assert result["delta_pct"] == pytest.approx(4.76)
    assert result["abs_error_mps"] == pytest.approx(0.02)
    assert result["within_calibration_band"] is True
    assert result["target"]["calibration_id"] == "vbt-test"


def test_rep_count_mismatch_is_never_comparable():
    result = vbt_analysis.compare_set([item()], row(reps=5))

    assert result["comparable"] is False
    assert "rep_mismatch" in result["reasons"]
    assert result["delta_mps"] == pytest.approx(0.0)


def test_missing_and_invalid_velocity_are_explicit():
    missing = vbt_analysis.compare_set([item()], row(velocity=None))
    invalid = vbt_analysis.compare_set([item()], row(velocity=0))
    assert missing["comparable"] is False and "missing_velocity" in missing["reasons"]
    assert invalid["comparable"] is False and "invalid_velocity" in invalid["reasons"]
    assert missing["actual_velocity_mps"] is None


def test_effort_outside_or_missing_is_context_not_a_valid_comparison():
    outside = vbt_analysis.compare_set([item()], row(rir=1))
    missing = vbt_analysis.compare_set([item()], row(rir=None))
    assert outside["comparable"] is False
    assert "actual_rir_outside_band" in outside["reasons"]
    assert missing["comparable"] is False
    assert "actual_rir_missing" in missing["reasons"]


def test_unknown_load_basis_and_warmups_are_excluded():
    unknown = vbt_analysis.compare_set([item(load_basis="unknown")], row())
    warmup = vbt_analysis.compare_set([item()], row(rir=6))
    assert unknown["comparable"] is False and "load_basis_unknown" in unknown["reasons"]
    assert warmup["comparable"] is False and "warm_up" in warmup["reasons"]


def test_set_group_rep_mismatch_and_ambiguous_role_are_explicit():
    groups = [
        {"role": "top_set", "sets": 1, "reps_low": 5, "reps_high": 5,
         "load_kg": 110, "rir_target": 1},
        {"role": "back_off", "sets": 2, "reps_low": 3, "reps_high": 5,
         "load_kg": 95, "rir_target": 2},
    ]
    mismatch = vbt_analysis.compare_set(
        [item(set_groups=groups)], row(set_role="top_set", reps=5, rir=1),
    )
    ambiguous = vbt_analysis.compare_set(
        [item(set_groups=groups)], row(set_role=None),
    )
    assert "group_rep_mismatch" in mismatch["reasons"]
    assert "ambiguous_set_role" in ambiguous["reasons"]
    assert mismatch["comparable"] is False and ambiguous["comparable"] is False


def test_unattributed_or_wrong_exercise_sets_cannot_borrow_a_target():
    unattributed = vbt_analysis.compare_set([item()], row(prescription_item_index=None))
    wrong = vbt_analysis.compare_set(
        [item()], row(exercise_id="competition_squat", prescription_item_index=0),
    )
    assert "unattributed_set" in unattributed["reasons"]
    assert "exercise_mismatch" in wrong["reasons"]
    assert unattributed["target_mps"] is None
    assert wrong["comparable"] is False


def test_no_target_and_legacy_target_are_honest():
    no_target = vbt_analysis.compare_set(
        [item(vbt=None, velocity_target=None)], row(),
    )
    legacy = vbt_analysis.compare_set(
        [item(vbt=None, velocity_target=0.40)], row(),
    )
    assert "no_target" in no_target["reasons"]
    assert "legacy_target" in legacy["reasons"]
    assert legacy["comparable"] is False
    assert legacy["target"]["metadata"] == "legacy"


def test_active_feedback_reports_target_and_comparability_counts():
    data = {
        "plan": {"items": [item()]},
        "sets": [row(velocity=0.44), row(set_id=2, set_index=2, reps=5)],
    }
    result = vbt_analysis.active_feedback(data)
    assert result["status"] == "available"
    assert result["quality"]["target_items"] == 1
    assert result["quality"]["logged_sets"] == 2
    assert result["quality"]["comparable_sets"] == 1
    assert result["sets"][0]["comparable"] is True
    assert result["sets"][1]["comparable"] is False
    assert "rep_mismatch" in result["sets"][1]["reasons"]


def test_active_feedback_without_any_target_is_unavailable():
    result = vbt_analysis.active_feedback({
        "plan": {"items": [item(vbt=None, velocity_target=None)]},
        "sets": [row()],
    })
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_vbt_target_issued"
    assert result["quality"]["comparable_sets"] == 0


def completed_data(final_items, original_items=None):
    return {
        "workout_id": "w1",
        "plan": {"items": final_items},
        "original_plan": {"items": original_items if original_items is not None else final_items},
    }


def test_completed_analysis_uses_clean_sets_and_aggregates_per_exercise():
    result = vbt_analysis.completed(
        completed_data([item()]),
        [
            row(set_id=1, set_index=1, velocity=0.44),
            row(set_id=2, set_index=2, velocity=0.40),
            row(set_id=3, set_index=3, reps=5, velocity=0.44),
        ],
    )

    assert result["status"] == "available"
    assert result["quality"]["working_sets"] == 3
    assert result["quality"]["sets_with_velocity"] == 3
    assert result["quality"]["comparable_sets"] == 2
    assert result["quality"]["excluded_sets"] == 1
    assert result["sets"][0]["workout_id"] == "w1"
    assert result["sets"][0]["load_basis"] == "external"
    assert result["sets"][0]["prescribed_load_basis"] == "external"
    assert result["sets"][0]["delta_mps"] == pytest.approx(0.02)
    assert result["sets"][2]["reasons"] == ["rep_mismatch"]

    exercise = result["exercises"][0]
    assert exercise["exercise_id"] == "ssb_squat"
    assert exercise["sets"] == 3
    assert exercise["comparable_sets"] == 2
    assert exercise["mean_signed_delta_mps"] == pytest.approx(0.0)
    assert exercise["median_signed_delta_mps"] == pytest.approx(0.0)
    assert exercise["mean_absolute_error_mps"] == pytest.approx(0.02)
    assert exercise["mean_relative_delta_pct"] == pytest.approx(0.0)
    assert exercise["mean_absolute_relative_error_pct"] == pytest.approx(4.76)
    assert exercise["within_calibration_band"]["ratio"] == pytest.approx(1.0)
    assert exercise["above_target"]["numerator"] == 1
    assert exercise["below_target"]["numerator"] == 1
    assert exercise["mean_actual_rir"] == pytest.approx(2.0)
    assert exercise["mean_prescribed_rir"] == pytest.approx(2.0)
    assert exercise["target"]["calibration_id"] == "vbt-test"
    assert exercise["target_sources"] == ["final_plan"]


def test_removed_item_uses_the_original_issued_target():
    result = vbt_analysis.completed(
        completed_data([], [item()]),
        [row(velocity=0.44)],
    )
    comparison = result["sets"][0]
    assert comparison["target_source"] == "original_plan"
    assert comparison["target_mps"] == pytest.approx(0.42)
    assert comparison["comparable"] is True


def test_swapped_item_never_borrows_the_old_target():
    final = item(exercise_id="competition_squat", vbt=None, velocity_target=None)
    result = vbt_analysis.completed(
        completed_data([final], [item()]),
        [row(velocity=0.44)],
    )
    comparison = result["sets"][0]
    assert comparison["target_mps"] is None
    assert comparison["target_source"] is None
    assert "exercise_mismatch" in comparison["reasons"]
    assert comparison["comparable"] is False


def test_load_basis_mismatch_and_unknown_basis_are_explicit():
    mismatch = vbt_analysis.completed(
        completed_data([item()]), [row(load_basis="bodyweight_total")],
    )["sets"][0]
    unknown = vbt_analysis.completed(
        completed_data([item()]), [row(load_basis="unknown")],
    )["sets"][0]
    assert "load_basis_mismatch" in mismatch["reasons"]
    assert "load_basis_unknown" in unknown["reasons"]
    assert mismatch["comparable"] is False and unknown["comparable"] is False


def test_extra_set_is_flagged_but_kept_in_the_analysis():
    result = vbt_analysis.completed(
        completed_data([item(sets=1)]), [row(set_id=1, set_index=2, velocity=0.44)],
    )
    comparison = result["sets"][0]
    assert comparison["extra_set"] is True
    assert comparison["comparable"] is True
    assert result["quality"]["extra_sets"] == 1


def test_quarantined_flag_and_time_based_movement_are_excluded():
    flagged = vbt_analysis.completed(
        completed_data([item()]), [row(flags=["REPS_TYPO"])],
    )["sets"][0]
    assert "data_quality_flag" in flagged["reasons"]
    assert flagged["comparable"] is False


def test_latest_mean_override_wins_for_completed_analysis():
    result = vbt_analysis.completed(
        completed_data([item()]),
        [row(velocity=0.40)],
        overrides={1: {"velocity_mps": 0.44, "source": "manual"}},
    )
    comparison = result["sets"][0]
    assert comparison["actual_velocity_mps"] == pytest.approx(0.44)
    assert comparison["velocity_source"] == "override"
    assert comparison["delta_mps"] == pytest.approx(0.02)


def test_completed_no_target_and_legacy_target_are_honest():
    no_target = vbt_analysis.completed(
        completed_data([item(vbt=None, velocity_target=None)]), [row()],
    )
    legacy = vbt_analysis.completed(
        completed_data([item(vbt=None, velocity_target=0.40)]), [row()],
    )
    assert no_target["status"] == "unavailable"
    assert no_target["sets"][0]["target_metadata"] == "missing"
    assert no_target["sets"][0]["reasons"] == ["no_target"]
    assert legacy["sets"][0]["target_metadata"] == "legacy"
    assert "legacy_target" in legacy["sets"][0]["reasons"]
    assert legacy["sets"][0]["comparable"] is False


def test_completed_unattributed_set_is_kept_with_a_reason():
    result = vbt_analysis.completed(
        completed_data([item()]), [row(prescription_item_index=None)],
    )
    comparison = result["sets"][0]
    assert comparison["target_mps"] is None
    assert "unattributed_set" in comparison["reasons"]
    assert result["quality"]["excluded_sets"] == 1


def test_completed_exposes_prescribed_and_actual_rir_context():
    result = vbt_analysis.completed(
        completed_data([item()]), [row(rir=1, velocity=0.44)],
    )
    comparison = result["sets"][0]
    assert comparison["actual_rir"] == 1
    assert comparison["prescribed_rir"] == 2
    assert comparison["target_rir_low"] == 2
    assert comparison["target_rir_high"] == 3
    assert "actual_rir_outside_band" in comparison["reasons"]
    assert comparison["comparable"] is False
