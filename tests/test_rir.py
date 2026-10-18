"""RIR semantics, including the warm-up decision (DEC-RIR-01).

DEC-RIR-01: the athlete confirmed `RIR = 6` marks a WARM-UP set. That is stronger than
"unknown" and it changes what the value may influence, so it is pinned by tests.
"""

import pytest
import yaml

from strength_coach.domain import rir
from strength_coach.utils import paths


def test_six_is_a_warmup_not_an_effort_rating():
    reading = rir.classify(6)
    assert reading.klass == "warmup"
    assert reading.source == "logged_warmup"
    assert reading.value == 6          # preserved, not erased
    assert reading.suspect is False
    assert not rir.within_window(6, 2, 3)


def test_zero_is_effort_but_suspect():
    """RIR 0-1 must stay visible: the hard rule needs to see them."""
    reading = rir.classify(0)
    assert reading.klass == "effort"
    assert reading.suspect is True


def test_zero_rir_still_counts_as_a_working_set():
    """A suspected value is not a warm-up. Conflating the two would hide violations."""
    assert rir.is_working_set(0) is True
    assert rir.is_warmup(0) is False


def test_missing_rir_is_not_a_warmup():
    """Accessories are often logged without RIR and are still real work (asymmetry)."""
    assert rir.classify(None).klass == "missing"
    assert rir.is_working_set(None) is True
    assert rir.is_effort(None) is False


@pytest.mark.parametrize("value", [2, 3, 4, 5])
def test_mid_values_are_effort_and_not_suspect(value):
    reading = rir.classify(value)
    assert reading.klass == "effort"
    assert reading.suspect is False


def test_four_is_a_legitimate_value():
    """RIR 4 may be rare, but it is on the scale and must not be special-cased."""
    assert rir.classify(4).klass == "effort"


@pytest.mark.parametrize("value", [7, -1, "abc", float("nan")])
def test_off_scale_values_are_missing_not_guessed(value):
    assert rir.classify(value).klass == "missing"


def test_float_and_string_inputs_are_accepted():
    assert rir.classify(2.0).klass == "effort"
    assert rir.classify("3").klass == "effort"
    assert rir.classify("6").klass == "warmup"


def test_default_window_applies_to_every_compound():
    """DEC-WINDOW-01: the trap bar no longer carries a tighter window."""
    assert rir.target_for("bench_press") == (2, 3)
    assert rir.target_for("trap_bar_deadlift") == (2, 3)
    assert rir.target_for("ssb_squat") == (2, 3)


def test_override_mechanism_still_works(monkeypatch):
    """The per-lift window survives as config, so amending it again is not a code change."""
    monkeypatch.setitem(rir.PER_EXERCISE_RIR_TARGET, "trap_bar_deadlift", (3, 4))
    assert rir.target_for("trap_bar_deadlift") == (3, 4)
    assert rir.target_for("bench_press") == (2, 3)


def test_window_membership():
    assert rir.within_window(2, 2, 3)
    assert rir.within_window(3, 2, 3)
    assert not rir.within_window(4, 2, 3)
    assert not rir.within_window(None, 2, 3)


def test_warmup_fraction():
    assert rir.warmup_fraction([6, 6, 2, 3]) == 0.5
    assert rir.warmup_fraction([]) == 0.0


def test_rule_document_and_code_agree():
    """The rule YAML and domain.rir must not drift apart."""
    with paths.programme_rules_yaml().open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    rule = next(r for r in document["rules"] if r["id"] == "PRG-RIR-001")
    params = rule["params"]
    # The rule allows RIR 1-4 (DEC-RIR-02); the *target* band stays narrower (2-3) and is what
    # VBT calibration accepts as a clean set.
    assert tuple(params["default_rir"].values()) == rir.ALLOWED_RIR_WINDOW
    assert rir.DEFAULT_RIR_TARGET == (2, 3)
    assert rir.ALLOWED_RIR_WINDOW[0] <= rir.DEFAULT_RIR_TARGET[0]
    assert rir.ALLOWED_RIR_WINDOW[1] >= rir.DEFAULT_RIR_TARGET[1]
    # The YAML override map and the code override map must be the same set of lifts.
    assert set(params.get("per_exercise_rir") or {}) == set(rir.PER_EXERCISE_RIR_TARGET)
    for exercise_id, window in (params.get("per_exercise_rir") or {}).items():
        assert tuple(window.values()) == rir.target_for(exercise_id)
    assert params["warmup_rir_value"] == rir.WARMUP_RIR
