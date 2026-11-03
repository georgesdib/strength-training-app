"""Generated-session snapshot validation."""

from __future__ import annotations

import pytest

from strength_coach.prescribe import generated


def _slot(slot_id="squat_main", exercise="ssb_squat", **overrides):
    data = {
        "id": slot_id,
        "exercise_id": exercise,
        "sets": 4,
        "reps_low": 5,
        "reps_high": 5,
        "rir_low": 2,
        "rir_high": 3,
        "rest_s": 180,
        "essential": True,
        "load_source": "e1rm",
        "power": False,
        "quality_stop": None,
    }
    data.update(overrides)
    return data


def _snapshot(*slots):
    return {
        "assignment": {slot["id"]: slot["exercise_id"] for slot in slots},
        "slots": list(slots),
    }


def test_valid_snapshot_is_returned_and_is_unique_by_exercise():
    specs = generated.slot_specs(_snapshot(_slot()))
    assert specs[0]["exercise_id"] == "ssb_squat"
    assert generated.slots_by_exercise(_snapshot(_slot()))["ssb_squat"]["sets"] == 4


def test_pre_step6_snapshot_without_slots_remains_legacy():
    assert generated.slot_specs({"assignment": {"squat_main": "ssb_squat"}}) == ()
    assert generated.slots_by_exercise({"assignment": {"squat_main": "ssb_squat"}}) == {}


def test_malformed_json_is_not_silently_treated_as_legacy():
    with pytest.raises(generated.SnapshotError, match="not valid JSON"):
        generated.load_snapshot("{not-json")


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"sets": 0}, "sets"),
        ({"sets": True}, "sets"),
        ({"reps_low": 6, "reps_high": 5}, "reps_low"),
        ({"essential": "yes"}, "essential"),
        ({"quality_stop": 3}, "quality_stop"),
    ],
)
def test_slot_fields_and_ranges_are_validated(overrides, message):
    with pytest.raises(generated.SnapshotError, match=message):
        generated.slot_specs(_snapshot(_slot(**overrides)))


def test_slot_ids_and_exercises_must_be_unique():
    with pytest.raises(generated.SnapshotError, match="slot IDs"):
        generated.slot_specs(_snapshot(_slot(), _slot(exercise="front_squat")))
    with pytest.raises(generated.SnapshotError, match="exercise assignments"):
        generated.slot_specs(_snapshot(_slot(), _slot("accessory")))


def test_slots_must_match_the_assignment_and_be_complete():
    with pytest.raises(generated.SnapshotError, match="exactly match"):
        generated.slot_specs({
            "assignment": {"squat_main": "ssb_squat", "accessory": "row"},
            "slots": [_slot()],
        })
    with pytest.raises(generated.SnapshotError, match="does not match"):
        generated.slot_specs({
            "assignment": {"squat_main": "front_squat"},
            "slots": [_slot()],
        })
    with pytest.raises(generated.SnapshotError, match="non-empty list"):
        generated.slot_specs({"assignment": {"squat_main": "ssb_squat"}, "slots": []})


def test_missing_required_field_is_rejected():
    slot = _slot()
    del slot["rest_s"]
    with pytest.raises(generated.SnapshotError, match="rest_s"):
        generated.slot_specs(_snapshot(slot))
