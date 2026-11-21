"""WP5: the shared order matcher and substitution attribution in adherence."""

from __future__ import annotations

import copy

from strength_coach import adherence


def _item(**overrides):
    item = {
        "order_index": 0,
        "exercise_id": "ssb_squat",
        "sets": 1,
        "reps_low": 4,
        "reps_high": 5,
        "load_kg": 160,
        "load_basis": "external",
        "rounding_increment_kg": 2.5,
        "rir_target": 2,
        "effort_model": "rir",
        "set_groups": [],
    }
    item.update(overrides)
    return item


def _set(set_id, *, load, reps, rir, exercise="ssb_squat", **extra):
    row = {
        "set_id": set_id,
        "set_index": set_id,
        "exercise_id": exercise,
        "load_kg": load,
        "reps": reps,
        "rir": rir,
        "is_working_set": 1,
        "prescription_item_index": 0,
        "load_basis": "external",
    }
    row.update(extra)
    return row


def _analyse(item, sets, execution=None):
    plan = {"items": [item]}
    return adherence.analyse({
        "original_plan": plan,
        "plan": plan,
        "plan_modified": False,
        "sets": sets,
        "readiness": {},
        "execution": execution or {"substitutions": []},
    })


def test_worked_example_is_attached_to_the_exercise_entry() -> None:
    rows = [
        _set(1, load=180, reps=4, rir=1),
        _set(2, load=160, reps=5, rir=3),
        _set(3, load=160, reps=5, rir=3),
        _set(4, load=160, reps=5, rir=3),
    ]
    result = _analyse(_item(sets=4), rows)
    structure = result["original"]["exercises"][0]["structure"]
    assert structure["structure"] == "top_set_like_plus_back_off"
    assert structure["confidence"] == "high"
    assert structure["working_sets"] == 4


def test_substitution_records_the_changed_slot_and_uses_the_prefill() -> None:
    execution = {
        "substitutions": [{
            "plan_item_index": 0,
            "exercise_id": "competition_squat",
            "prefill_load_kg": 120,
            "reps_low": 3,
            "reps_high": 5,
            "rir_target": 2,
            "prefill_reason": "solved",
        }]
    }
    rows = [_set(
        1, load=120, reps=5, rir=2,
        exercise="competition_squat", substitutes_plan_item_index=0,
    )]
    result = _analyse(_item(), rows, execution)["original"]
    entry = result["exercises"][0]
    assert entry["substituted"] is True
    assert entry["planned_exercise_id"] == "ssb_squat"
    assert entry["performed_exercise_id"] == "competition_squat"
    detail = entry["sets"][0]
    assert detail["substituted"] is True
    assert detail["load_target_kg"] == 120.0
    assert detail["load_status"] == "at_target"
    assert detail["reps_status"] == "within"
    assert detail["rir_status"] == "at_target"


def test_substitution_without_a_prefill_stays_visible_and_unscored() -> None:
    rows = [_set(
        1, load=120, reps=5, rir=2,
        exercise="competition_squat", substitutes_plan_item_index=0,
    )]
    result = _analyse(_item(), rows)["original"]
    entry = result["exercises"][0]
    assert entry["substituted"] is True
    detail = entry["sets"][0]
    assert "substituted_prefill_unavailable" in detail["limitations"]
    assert detail["load_status"] == "unavailable"


def test_rir6_wins_over_a_stored_working_flag() -> None:
    rows = [
        _set(1, load=100, reps=5, rir=6, set_role="top_set", is_working_set=1),
        _set(2, load=100, reps=5, rir=2),
    ]
    result = _analyse(_item(), rows)
    assert result["quality"]["warm_up_sets_excluded"] == 1
    assert result["quality"]["ambiguous_status_sets"] == 0
    assert result["original"]["performed_sets"] == 1


def test_analysis_does_not_mutate_the_input() -> None:
    rows = [_set(1, load=100, reps=5, rir=2)]
    data = {
        "original_plan": {"items": [_item()]},
        "plan": {"items": [_item()]},
        "plan_modified": False,
        "sets": rows,
        "readiness": {},
        "execution": {"substitutions": []},
    }
    before = copy.deepcopy(data)
    adherence.analyse(data)
    assert data == before

