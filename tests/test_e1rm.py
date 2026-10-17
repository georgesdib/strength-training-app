"""e1RM arithmetic: formula, rep caps, and provenance tagging."""

import pytest

from strength_coach.domain import e1rm


def test_epley_basic():
    # 100 kg x 5 reps -> 100 * (1 + 5/30) = 116.67
    assert e1rm.epley(100, 5) == pytest.approx(116.667, abs=0.01)


def test_epley_single_rep_is_the_load():
    assert e1rm.epley(150, 1) == pytest.approx(155.0)


def test_rir_adjusted_treats_rir_as_unperformed_reps():
    """2 reps in reserve means the set is treated as 2 reps closer to failure."""
    assert e1rm.epley_rir_adjusted(100, 5, 2) == pytest.approx(e1rm.epley(100, 7))


def test_rir_adjustment_always_exceeds_plain_estimate():
    assert e1rm.epley_rir_adjusted(100, 3, 3) > e1rm.epley(100, 3)


def test_estimate_uses_rir_when_available():
    estimate = e1rm.estimate_e1rm(100, 5, 2)
    assert estimate.method == "epley_plus_rir"
    assert estimate.rir_used == 2
    assert estimate.value_kg == pytest.approx(e1rm.epley_rir_adjusted(100, 5, 2))


def test_estimate_falls_back_when_rir_missing():
    estimate = e1rm.estimate_e1rm(100, 5, None)
    assert estimate.method == "epley"
    assert estimate.rir_used is None


def test_rir_6_is_not_used():
    """RIR 6 is a probable default bucket (DQ-SENT-03), so it must not inflate e1RM."""
    estimate = e1rm.estimate_e1rm(100, 3, 6)
    assert estimate.method == "epley"
    assert estimate.value_kg == pytest.approx(e1rm.epley(100, 3))


@pytest.mark.parametrize("reps", [11, 15, 20])
def test_high_reps_marked_degraded(reps):
    estimate = e1rm.estimate_e1rm(60, reps, 2)
    assert estimate.quality == "degraded"


def test_reps_at_or_below_cap_are_ok():
    assert e1rm.estimate_e1rm(60, e1rm.MAX_RELIABLE_REPS, 2).quality == "ok"


@pytest.mark.parametrize("load,reps", [(None, 5), (100, None), (0, 5), (-50, 5), (100, 0), (100, -3)])
def test_unusable_inputs_return_none(load, reps):
    """None, not 0.0 — a silent zero in an e1RM column is worse than a visible gap."""
    assert e1rm.estimate_e1rm(load, reps) is None


def test_absurd_rep_count_rejected():
    """The log contains a 1015-rep typo; it must not produce an estimate."""
    assert e1rm.estimate_e1rm(100, 1015) is None
    assert e1rm.estimate_e1rm(100, e1rm.MAX_USABLE_REPS + 1) is None


def test_percent_of_e1rm_guards_zero():
    assert e1rm.percent_of_e1rm(100, 200) == 0.5
    assert e1rm.percent_of_e1rm(100, 0) is None
