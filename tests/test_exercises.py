"""Exercise taxonomy resolution.

These tests pin the two recorded user decisions, because both are easy to
"helpfully" undo later:

* DEC-TRAPBAR-01 — the app logs the trap-bar pull as "Competition Deadlift".
* DEC-BACKEXT-01 — back extension == hyperextension *going forward only*; the
  equivalence must not be projected backwards onto historical rows.

They also pin the resolution *order*, since regex ordering is the fragile part.
"""

import pytest

from strength_coach.utils import exercises


@pytest.fixture(scope="module")
def taxonomy():
    return exercises.taxonomy()


# --- recorded decisions ----------------------------------------------------
def test_competition_deadlift_is_trap_bar(taxonomy):
    resolved = taxonomy.resolve("Competition Deadlift")
    assert resolved.id == "trap_bar_deadlift"
    assert resolved.decision == "DEC-TRAPBAR-01"
    assert resolved.applies_to_history is True


def test_trap_bar_is_hinge_direct_erector_false(taxonomy):
    """Hinge loading is indirect erector work: it never satisfies the direct dose."""
    resolved = taxonomy.resolve("Competition Deadlift")
    assert resolved.pattern == "hinge"
    assert resolved.is_high_fatigue_spinal is True
    assert resolved.is_direct_erector is False


def test_historical_hyperextension_is_not_back_extension(taxonomy):
    resolved = taxonomy.resolve("Hyperextensions")
    assert resolved.id == "hyperextension"
    assert resolved.id != "back_extension"
    assert resolved.counts_toward_back_extension_dose is False
    assert resolved.decision == "DEC-BACKEXT-01"


def test_back_extension_forward_only(taxonomy):
    resolved = taxonomy.resolve("Back Extension")
    assert resolved.id == "back_extension"
    assert resolved.applies_to_history is False
    assert resolved.counts_toward_back_extension_dose is True


def test_forward_name_redirects_history_to_canonical():
    """A prescription may say 'back extension' for a lift historically logged as
    'Hyperextensions', while the historical row keeps its own identity."""
    assert exercises.canonical_id("Hyperextensions") == "hyperextension"
    assert exercises.forward_name("Hyperextensions") == "back_extension"


# --- resolution order ------------------------------------------------------
def test_jump_squat_is_power_not_squat(taxonomy):
    assert taxonomy.resolve("Jump Squats").pattern == "power_jump"


def test_flat_bench_situps_are_core_not_bench(taxonomy):
    assert taxonomy.resolve("Flat-bench Sit-ups").pattern == "core"


def test_leg_curls_are_knee_flexion_not_biceps(taxonomy):
    assert taxonomy.resolve("Lying Leg Curls").pattern == "knee_flexion"
    assert taxonomy.resolve("Barbell Curl").pattern == "elbow_flexion"


def test_jefferson_curl_is_not_a_biceps_curl(taxonomy):
    assert taxonomy.resolve("Jefferson Curl").id == "jefferson_curl"


def test_reverse_hyperextension_is_not_hyperextension(taxonomy):
    assert taxonomy.resolve("Reverse Hyperextensions").id == "reverse_hyperextension"


def test_specific_deadlift_variant_keeps_hinge_properties(taxonomy):
    resolved = taxonomy.resolve("Deadlift (w/chains)")
    assert resolved.pattern == "hinge"
    assert resolved.is_high_fatigue_spinal is True


def test_single_leg_rdl_is_not_romanian_deadlift(taxonomy):
    assert taxonomy.resolve("Single Leg DB RDL").pattern == "hinge_unilateral"


# --- unit semantics --------------------------------------------------------
def test_planks_log_seconds_not_reps(taxonomy):
    """Chinese Plank values of 80-110 in Reps_Done are seconds (DQ-REPS-01)."""
    resolved = taxonomy.resolve("Chinese Plank")
    assert resolved.rep_semantics == "seconds"
    assert resolved.is_time_based is True


def test_normal_lift_logs_reps(taxonomy):
    assert taxonomy.resolve("Safety Squat Bar").rep_semantics == "reps"


# --- failure behaviour -----------------------------------------------------
def test_unknown_name_returns_none_never_guesses(taxonomy):
    """Names that match no pattern resolve to nothing rather than a guess.

    Note that a name merely *containing* "squat" does resolve — the broad patterns
    are intentional, so unknown lifting vocabulary still lands in the right family.
    """
    assert taxonomy.resolve("Zercher Thingamajig") is None


def test_blank_and_none_return_none(taxonomy):
    assert taxonomy.resolve("") is None
    assert taxonomy.resolve(None) is None


def test_unmatched_reports_only_misses(taxonomy):
    assert taxonomy.unmatched(["Safety Squat Bar", "Made Up Lift"]) == ["Made Up Lift"]


def test_whitespace_and_tabs_are_stripped(taxonomy):
    assert taxonomy.resolve("  Bird dog \t") is not None


# --- integration against the real log --------------------------------------
@pytest.mark.integration
def test_every_real_exercise_name_resolves(taxonomy, training_frame):
    """All 147 distinct names in the log must resolve; an unresolved name means
    silently dropped volume in every downstream metric."""
    names = training_frame["Exercise"].unique()
    assert taxonomy.unmatched(names) == []


@pytest.mark.integration
def test_classify_adds_traceable_columns(taxonomy, training_frame):
    out = taxonomy.classify(training_frame.head(50))
    for column in ("exercise_id", "exercise_matched_by", "exercise_decision"):
        assert column in out.columns
    assert out["exercise_id"].notna().all()
