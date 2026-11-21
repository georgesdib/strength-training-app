"""The synthetic A/B review produces one deterministic row per case."""

from __future__ import annotations

import pytest

from strength_coach.prescribe import evaluator_ab


@pytest.mark.parametrize("name", sorted(evaluator_ab.CASES))
def test_each_review_case_has_a_safe_quality_choice(name: str) -> None:
    case = evaluator_ab._run_case(name)
    assert case["evidence"] == "synthetic"
    assert case["evaluated"] >= 1
    assert case["quality_feasible"] is True
    assert case["quality"] is not None
    assert case["band_penalty"] == 0
    assert case["volume_error"] >= 0.0
    assert case["time_over"] == 0.0


@pytest.mark.parametrize(
    ("name", "slot"),
    [
        ("secondary_redundancy", "bench_support"),
        ("accessory_coverage", "accessory_row"),
        ("accessory_stimulus", "accessory_vertical_press"),
    ],
)
def test_full_cases_show_the_role_choice_change(name: str, slot: str) -> None:
    case = evaluator_ab._run_case(name)
    assert slot in case["changed_slots"]
    assert case["classic"][slot] != case["quality"][slot]
    assert case["quality_classes"] is not None
    assert case["classic_feasible"] is True
    assert case["quality_feasible"] is True


@pytest.mark.parametrize("name", ["substitution", "secondary_complementarity"])
def test_hierarchy_can_leave_the_choice_unchanged(name: str) -> None:
    case = evaluator_ab._run_case(name)
    assert case["changed"] is False
    assert case["classic"] == case["quality"]


def test_full_cases_cover_secondary_and_accessory_changes() -> None:
    secondary = evaluator_ab._run_case("secondary_redundancy")
    coverage = evaluator_ab._run_case("accessory_coverage")
    stimulus = evaluator_ab._run_case("accessory_stimulus")
    assert secondary["changed_slots"] == ["bench_support"]
    assert coverage["changed_slots"] == ["accessory_row"]
    assert stimulus["changed_slots"] == ["accessory_vertical_press"]
