"""Order-based classification and set-group selection shared by the analysis layers."""

from __future__ import annotations

from strength_coach.features import set_matching


def test_rir6_is_a_warm_up_and_missing_rir_stays_working() -> None:
    assert set_matching.classify_set({"rir": 6, "is_working_set": 1}) == "warm_up"
    assert set_matching.classify_set({"rir": 6, "set_role": "top_set"}) == "warm_up"
    assert set_matching.classify_set({"rir": 2}) == "working"
    assert set_matching.classify_set({"rir": None}) == "working"


def test_groups_are_selected_by_cumulative_working_order() -> None:
    item = {
        "set_groups": [
            {"group_index": 0, "sets": 1, "load_kg": 120},
            {"group_index": 1, "sets": 3, "load_kg": 100},
        ]
    }
    assert set_matching.group_index_for_ordinal(item, 0) == 0
    assert set_matching.group_index_for_ordinal(item, 1) == 1
    assert set_matching.group_index_for_ordinal(item, 3) == 1
    # The last group holds beyond the plan.
    assert set_matching.group_index_for_ordinal(item, 9) == 1


def test_straight_sets_have_no_group() -> None:
    assert set_matching.group_index_for_ordinal({"set_groups": []}, 0) is None
    assert set_matching.group_for_ordinal({}, 2) is None


def test_warm_ups_are_split_from_working_sets() -> None:
    rows = [{"rir": 6}, {"rir": 2}, {"rir": None}]
    assert len(set_matching.warm_up_sets(rows)) == 1
    assert len(set_matching.working_sets(rows)) == 2

