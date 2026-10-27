"""MOD-MIN-001: user-selected, volume-only, with an explicit deeper tier."""

from __future__ import annotations

from strength_coach.prescribe.minimum_session import (
    MinimumSessionConfig,
    apply,
    estimate_minutes,
)
from strength_coach.prescribe.models import PrescriptionItem


def _item(index, exercise, sets, *, essential, rest=180, load=100):
    return PrescriptionItem(
        order_index=index, exercise_id=exercise, sets=sets, reps_low=5, reps_high=5,
        load_kg=load, load_basis="external", rounding_increment_kg=2.5, rir_target=2,
        rest_s=rest, essential=essential,
    )


def test_the_estimate_reads_the_persisted_plan_form():
    # The ended-workout view recomputes the estimate from plan_json, so dict items must work:
    # 4 sets x (30 s set + 120 s rest) + 2 warm-up sets x 30 s = 660 s.
    assert estimate_minutes([{"sets": 4, "rest_s": 120, "warmup": [1, 2]}]) == 11.0


def _items():
    return (
        _item(0, "main_lift", 5, essential=True),
        _item(1, "accessory_a", 3, essential=False, rest=90),
        _item(2, "accessory_b", 3, essential=False, rest=90),
        _item(3, "accessory_c", 3, essential=False, rest=90),
        _item(4, "accessory_d", 3, essential=False, rest=90),
    )


def test_accessory_tier_keeps_main_lift_sets_and_load():
    before = _items()
    result = apply(before, target_minutes=30)
    assert result["status"] == "applied"
    main = next(item for item in result["items"] if item.essential)
    assert main.sets == 5
    assert main.load_kg == 100
    assert result["removed_sets"] > 0
    assert all(item.load_kg == original.load_kg
               for item, original in zip(result["items"], before, strict=False))
    assert estimate_minutes(result["items"]) <= 30


def test_deeper_tier_can_reduce_main_lift_to_floor():
    before = _items()
    cfg = MinimumSessionConfig(targets_minutes=(15,), default_target_minutes=15)
    result = apply(before, target_minutes=15, include_main=True, config=cfg)
    main = next(item for item in result["items"] if item.essential)
    assert main.sets == 2
    assert main.load_kg == 100
    assert "MOD-MIN-001" in main.rationale_refs


def test_target_already_met_is_a_noop():
    result = apply(_items(), target_minutes=60)
    assert result["status"] == "already_short"
    assert result["applied"] is False
    assert result["removed_sets"] == 0


def test_unexecutable_plan_is_refused():
    before = list(_items())
    before[0] = _item(0, "main_lift", 5, essential=True, load=None)
    result = apply(before, target_minutes=30)
    assert result["status"] == "unavailable"
    assert result["applied"] is False
    assert "no executable load" in result["reason"]
