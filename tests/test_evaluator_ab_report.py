"""The synthetic A/B review produces one deterministic row per case."""

from __future__ import annotations

import pytest

from strength_coach.prescribe import evaluator_ab


@pytest.mark.parametrize("name", sorted(evaluator_ab.CASES))
def test_each_review_case_has_a_safe_quality_choice(name: str) -> None:
    case = evaluator_ab._run_case(name)
    assert case["evaluated"] >= 1
    assert case["quality_feasible"] is True
    assert case["quality"] is not None
    assert case["band_penalty"] == 0
    assert case["volume_error"] == 0.0
    assert case["time_over"] == 0.0

