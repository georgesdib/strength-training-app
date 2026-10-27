"""Exercise taxonomy resolution.

These tests pin the two recorded user decisions, because both are easy to
"helpfully" undo later:

* DEC-TRAPBAR-02 — "Competition Deadlift" was a sumo pull before the 2026-08 switch and is
  the trap bar afterwards; identity is date-scoped, not a blanket alias.
* DEC-BACKEXT-02 — back extension == hyperextension, and historical rows count as
  equivalence must not be projected backwards onto historical rows.

They also pin the resolution *order*, since regex ordering is the fragile part.
"""

import pytest
import yaml

from strength_coach.utils import exercises, paths


@pytest.fixture(scope="module")
def taxonomy():
    return exercises.taxonomy()


def _shipped_taxonomy_entities() -> dict:
    """The checked-in taxonomy, without any local UI overrides."""
    raw = yaml.safe_load(paths.taxonomy_yaml().read_text(encoding="utf-8"))
    return raw.get("entities") or {}


# --- day_roles vocabulary (DEC-SESSION-01) ---------------------------------
def test_day_roles_use_canonical_session_types():
    """The retired A/B/C day labels must not survive in the taxonomy.

    Read the shipped YAML directly so a local UI override cannot make a public test fail.
    """
    from strength_coach.prescribe.schedule import SESSION_TYPES

    bad = {
        exercise_id: props.get("day_roles")
        for exercise_id, props in _shipped_taxonomy_entities().items()
        if props.get("day_roles") and not set(props["day_roles"]) <= set(SESSION_TYPES)
    }
    assert not bad, bad


def test_declared_day_roles_cover_every_template_that_prescribes_the_lift():
    """`day_roles` is descriptive, but it must not contradict the templates.

    A superset is allowed: direct erector work may be listed on both squat-emphasis types
    (PRG-SCHED-001) while the template fills only one to stay under the spinal cap.
    """
    from strength_coach.prescribe.schedule import SESSION_TYPES
    from strength_coach.prescribe.templates import SessionTemplate

    prescribed: dict[str, set[str]] = {}
    for session_type in SESSION_TYPES:
        for slot in SessionTemplate.load(session_type).slots:
            for exercise_id in slot.exercises:
                prescribed.setdefault(exercise_id, set()).add(session_type)

    for exercise_id, props in _shipped_taxonomy_entities().items():
        declared = set(props.get("day_roles") or ())
        if not declared:
            continue
        missing = prescribed.get(exercise_id, set()) - declared
        assert not missing, (
            f"{exercise_id}: templates prescribe {sorted(missing)}, day_roles {sorted(declared)}"
        )


# --- recorded decisions ----------------------------------------------------
def test_competition_deadlift_is_date_scoped(taxonomy):
    historical = taxonomy.resolve("Competition Deadlift", "2024-01-01")
    assert historical.id == "sumo_deadlift"
    assert historical.decision == "DEC-TRAPBAR-02"

    current = taxonomy.resolve("Competition Deadlift", "2026-09-01")
    assert current.id == "trap_bar_deadlift"
    assert current.applies_to_history is True


def test_cleaning_resolves_the_same_name_by_row_date():
    from conftest import make_readiness, make_training

    from strength_coach.ingest import clean as clean_mod

    rows = [
        {"Date": "2024-01-01", "Exercise": "Competition Deadlift"},
        {"Date": "2026-09-01", "Exercise": "Competition Deadlift"},
    ]
    result = clean_mod.build_clean_sets(make_training(rows), make_readiness([{}]))
    ids = list(result.sets.sort_values("date")["exercise_id"])
    assert ids == ["sumo_deadlift", "trap_bar_deadlift"]


def test_trap_bar_is_hinge_direct_erector_false(taxonomy):
    """Hinge loading is indirect erector work: it never satisfies the direct dose."""
    resolved = taxonomy.resolve("Trap Bar Deadlift")
    assert resolved.pattern == "hinge"
    assert resolved.is_high_fatigue_spinal is True
    assert resolved.is_direct_erector is False


def test_hyperextension_keeps_identity_but_counts_as_history(taxonomy):
    """DEC-BACKEXT-02: the row keeps its own id, but the movement is the same."""
    resolved = taxonomy.resolve("Hyperextensions")
    assert resolved.id == "hyperextension"
    assert resolved.id != "back_extension"
    assert resolved.counts_toward_back_extension_dose is True
    assert resolved.decision == "DEC-BACKEXT-02"

    assert set(exercises.history_equivalents("back_extension")) == {
        "back_extension", "hyperextension",
    }
    assert exercises.history_equivalents("ssb_squat") == ("ssb_squat",)


def test_back_extension_is_forward_only_but_history_counts(taxonomy):
    """New prescriptions say "back extension"; the old log name keeps its own identity."""
    resolved = taxonomy.resolve("Back Extension")
    assert resolved.id == "back_extension"
    assert resolved.applies_to_history is False
    assert resolved.counts_toward_back_extension_dose is True

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


def test_lat_pulldown_is_a_canonical_vertical_pull():
    # DEC-PULL-02: the pulldown is interchangeable with the pull-up in the vertical-pull slot,
    # so it must resolve to a real entity (with loadability), not a synthetic pattern slug.
    taxonomy = exercises.taxonomy()
    assert taxonomy.resolve("Lat Pulldown").id == "lat_pulldown"
    assert taxonomy.resolve("Close Grip Pulldown").id == "close_grip_pulldown"
    assert taxonomy.resolve("Straight-Arm Pulldown").pattern == "lat_isolation"


def test_box_jump_is_canonical_and_other_jumps_stay_synthetic():
    taxonomy = exercises.taxonomy()
    assert taxonomy.resolve("Box Jumps").id == "box_jump"
    assert taxonomy.resolve("Box Jumps").get("bodyweight_type") is True
    assert taxonomy.resolve("Jump Squats").pattern == "power_jump"


def test_approved_variant_pattern_and_muscle_corrections(taxonomy):
    assert taxonomy.resolve("Reverse Nordic Curl").pattern == "knee_extension"
    assert taxonomy.resolve("Split Squat").pattern == "squat_unilateral"
    assert taxonomy.resolve("Bulgarian Split Squat").pattern == "squat_unilateral"
    tib = taxonomy.resolve("Tib Bar Calves")
    assert tib.pattern == "dorsiflexion"
    assert tib.get("primary_muscles") == ["tibialis_anterior"]
    assert taxonomy.resolve("Face Pull ").get("primary_muscles") == ["rear_delts", "rotator_cuff"]
    assert taxonomy.resolve("T Bar Row").get("primary_muscles") == ["lats", "upper_back"]
    assert taxonomy.resolve("Speed Bench Press").get("primary_muscles") == [
        "chest", "triceps", "front_delts"
    ]


def test_tib_bar_has_a_dorsiflexion_readiness_category(taxonomy):
    from strength_coach.features import readiness_score

    assert readiness_score.category_for(
        "tib_bar_calves", taxonomy.entities["tib_bar_calves"]
    ) == "dorsiflexion"
