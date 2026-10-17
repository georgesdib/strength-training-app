"""Load resolution (DQ-BW-01) and rounding direction.

The rounding tests matter more than they look: rounding a prescription *up* would
prescribe more than the rules produced, so flooring is a safety property, not a
formatting preference.
"""

import pytest

from strength_coach.domain import load

BODYWEIGHT = 80.0


def test_plain_external_load_passes_through():
    resolved = load.resolve_load_basis(100.0, bodyweight_kg=BODYWEIGHT, is_bodyweight_type=False)
    assert resolved.basis == "external"
    assert resolved.external_load_kg == 100.0
    assert resolved.total_load_kg == 100.0


def test_zero_on_bodyweight_movement_is_unweighted():
    resolved = load.resolve_load_basis(0.0, bodyweight_kg=BODYWEIGHT, is_bodyweight_type=True)
    assert resolved.basis == "bodyweight_total"
    assert resolved.external_load_kg == 0.0
    assert resolved.total_load_kg == BODYWEIGHT


def test_bodyweight_captured_total_is_recognised():
    """A pull-up logged at total mass rather than added load: that is bodyweight_total."""
    resolved = load.resolve_load_basis(79.8, bodyweight_kg=BODYWEIGHT, is_bodyweight_type=True)
    assert resolved.basis == "bodyweight_total"
    assert resolved.external_load_kg == 0.0


def test_small_load_is_added_weight():
    """Chinese plank at 5 kg is a plate, not a bodyweight reading."""
    resolved = load.resolve_load_basis(5.0, bodyweight_kg=BODYWEIGHT, is_bodyweight_type=True)
    assert resolved.basis == "added"
    assert resolved.external_load_kg == 5.0
    assert resolved.total_load_kg == pytest.approx(BODYWEIGHT + 5.0)


def test_bodyweight_move_without_bodyweight_record_is_unknown():
    resolved = load.resolve_load_basis(79.8, bodyweight_kg=None, is_bodyweight_type=True)
    assert resolved.basis == "unknown"
    assert resolved.total_load_kg is None


def test_ratio_above_ceiling_is_unknown_not_guessed():
    resolved = load.resolve_load_basis(120.0, bodyweight_kg=BODYWEIGHT, is_bodyweight_type=True)
    assert resolved.basis == "unknown"


def test_time_based_movement_has_no_tonnage():
    resolved = load.resolve_load_basis(5.0, bodyweight_kg=BODYWEIGHT, is_bodyweight_type=True,
                                       is_time_based=True)
    assert resolved.total_load_kg is None


def test_round_down_floors_never_rounds_up():
    assert load.round_load_down(103.0, 2.5) == 102.5
    assert load.round_load_down(102.5, 2.5) == 102.5
    assert load.round_load_down(99.9, 2.5) == 97.5


def test_round_down_handles_float_noise():
    assert load.round_load_down(100.0, 2.5) == 100.0


def test_round_up_only_for_reporting():
    assert load.round_load_up(103.0, 2.5) == 105.0


def test_increment_scales_with_load():
    """Small lifts get smaller steps because the log contains 0.5/1/2.5 kg increments."""
    assert load.default_increment_kg(10) == 1.0
    assert load.default_increment_kg(30) == 2.0
    assert load.default_increment_kg(150) == 2.5


def test_rounding_rejects_non_positive_increment():
    with pytest.raises(ValueError):
        load.round_load_down(100, 0)


def test_none_input_returns_none():
    assert load.round_load_down(None) is None
    assert load.apply_percent_modifier(None, 0.9) is None


def test_fatigue_modifier():
    assert load.apply_percent_modifier(100.0, 0.9) == pytest.approx(90.0)
