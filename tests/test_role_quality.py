"""WP6 role-quality hierarchy: deterministic classes, neutral missing data, no composite."""

from __future__ import annotations

from dataclasses import replace

import pytest

from strength_coach.prescribe import role_quality, selection_tax, templates
from strength_coach.prescribe.models import Prescription, PrescriptionItem
from strength_coach.store import db
from strength_coach.utils import exercises

CFG = role_quality.RoleQualityConfig.load()
TAXONOMY = exercises.taxonomy().entities
TAX = selection_tax.TaxConfig.load()


def _item(order, slot, exercise, *, intensity=None):
    return PrescriptionItem(
        order_index=order,
        exercise_id=exercise,
        sets=slot.sets,
        reps_low=slot.reps_low,
        reps_high=slot.reps_high,
        load_kg=100.0,
        load_basis="external",
        rounding_increment_kg=2.5,
        rir_target=slot.rir_low,
        rest_s=slot.rest_s,
        essential=slot.essential,
        intensity=intensity,
        e1rm_quality="ok" if intensity is not None else None,
        e1rm_age_days=7 if intensity is not None else None,
    )


def _snapshot_with(
    *,
    base: templates.SessionTemplate,
    assignment: dict[str, str],
    panel: dict | None = None,
    band_penalty: int = 0,
    intent_penalty: int = 0,
) -> role_quality.RoleQualitySnapshot:
    items = tuple(
        _item(
            index,
            slot,
            assignment[slot.id],
            intensity=0.85 if index == 1 else None,
        )
        for index, slot in enumerate(base.slots)
    )
    notes = {"volume_panel": panel} if panel is not None else {}
    prescription = Prescription(
        for_date="2024-01-15",
        session_type=base.session_type,
        fallback_level="none",
        rule_document_version="test",
        items=items,
        notes=notes,
    )
    with db.Store(":memory:") as store:
        return role_quality.snapshot(
            conn=store.connection,
            for_date="2024-01-15",
            base=base,
            assignment=assignment,
            prescription=prescription,
            band_penalty=band_penalty,
            intent_penalty=intent_penalty,
        )


def _snapshot(*, band_penalty=0, intent_penalty=0):
    base = templates.SessionTemplate.load("squat")
    assignment = {slot.id: slot.exercises[0] for slot in base.slots}
    return _snapshot_with(
        base=base,
        assignment=assignment,
        panel={
            "band": {"low": 10.0, "high": 20.0},
            "after": 15.0,
            "groups": {},
        },
        band_penalty=band_penalty,
        intent_penalty=intent_penalty,
    )


def _reduced_template(*slot_ids: str) -> templates.SessionTemplate:
    base = templates.SessionTemplate.load("squat")
    slots = tuple(slot for slot in base.slots if slot.id in set(slot_ids))
    return replace(base, slots=slots)


def _secondary_assignment(support: str, accessory: str) -> tuple[templates.SessionTemplate, dict[str, str]]:
    base = _reduced_template("squat_main", "bench_support", "core_anti_extension")
    return base, {
        "squat_main": "ssb_squat",
        "bench_support": support,
        "core_anti_extension": accessory,
    }


# ---------------------------------------------------------------------------
# Complementarity
# ---------------------------------------------------------------------------


def test_complementarity_is_relative_to_the_selected_main_lift() -> None:
    # Different pattern and different family: genuinely complementary.
    assert role_quality._complementarity_class(
        "dumbbell_row", "ssb_squat", "squat", TAXONOMY, CFG
    ) == CFG.complementarity.value("complementary")
    # Same pattern and same ledger key: redundant, not a complement.
    assert role_quality._complementarity_class(
        "competition_squat", "ssb_squat", "squat", TAXONOMY, CFG
    ) == CFG.complementarity.value("same_pattern")
    # A related but differently named pattern is still the same volume family.
    assert role_quality._complementarity_class(
        "split_squat", "ssb_squat", "squat", TAXONOMY, CFG
    ) == CFG.complementarity.value("same_pattern")
    # Unknown taxonomy stays neutral.
    assert role_quality._complementarity_class(
        "chest_supported_row", "ssb_squat", "squat", TAXONOMY, CFG
    ) == CFG.complementarity.neutral
    assert role_quality._complementarity_class(
        "dumbbell_row", "ssb_squat", None, TAXONOMY, CFG
    ) == CFG.complementarity.neutral


def test_complementary_pattern_beats_same_pattern_redundancy() -> None:
    same = role_quality._complementarity_class(
        "competition_squat", "ssb_squat", "squat", TAXONOMY, CFG
    )
    complement = role_quality._complementarity_class(
        "dumbbell_row", "ssb_squat", "squat", TAXONOMY, CFG
    )
    assert complement > same


# ---------------------------------------------------------------------------
# Volume usefulness and productive volume
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scale_name", ["volume_usefulness", "productive_volume"])
def test_volume_class_uses_the_candidates_marginal_contribution(scale_name: str) -> None:
    scale = getattr(CFG, scale_name)
    # A genuine deficit without the candidate, filled without materially overshooting.
    assert role_quality._volume_contribution_class(10.0, 12.0, 3, scale) == scale.value("fills_deficit")
    # The pattern was already at target before this candidate: redundant.
    assert role_quality._volume_contribution_class(14.0, 12.0, 2, scale) == scale.value("redundant")
    # The candidate fills a deficit but pushes the pattern materially over target: no reward.
    assert role_quality._volume_contribution_class(15.0, 12.0, 4, scale) == scale.value("within_target")
    # Missing or unusable volume information is neutral, not a deficit or a surplus.
    assert role_quality._volume_contribution_class(0.0, 0.0, 3, scale) == scale.neutral
    assert role_quality._volume_contribution_class(10.0, 12.0, 0, scale) == scale.neutral


def test_secondary_volume_usefulness_can_decide_the_winner() -> None:
    # Both support candidates are complementary and non-redundant. The first adds volume to a
    # pattern that is already over target; the second fills a genuine deficit.
    base, assignment_a = _secondary_assignment("bench_press", "ab_wheel")
    assignment_b = {**assignment_a, "bench_support": "dumbbell_row"}
    panel = {
        "band": {"low": 0.0, "high": 999.0},
        "after": 0.0,
        "groups": {
            "horizontal_push": {"target": 12.0, "after": 15.0},
            "horizontal_pull": {"target": 9.0, "after": 9.0},
        },
    }
    a = _snapshot_with(base=base, assignment=assignment_a, panel=panel)
    b = _snapshot_with(base=base, assignment=assignment_b, panel=panel)
    assert a.roles["secondary"][0]["classes"]["volume_usefulness"] == CFG.volume_usefulness.value("within_target")
    assert b.roles["secondary"][0]["classes"]["volume_usefulness"] == CFG.volume_usefulness.value("fills_deficit")
    assert b.vector < a.vector


# ---------------------------------------------------------------------------
# Redundancy
# ---------------------------------------------------------------------------


def test_redundancy_compares_selected_work_not_set_count() -> None:
    # Same pattern as the main lift: redundant.
    assert role_quality._redundancy_class(
        "competition_squat", ("ssb_squat", "bench_press"), TAXONOMY, CFG
    ) == CFG.redundancy.value("duplicate")
    # Shares the main lift's erector stimulus without duplicating its pattern: partial.
    assert role_quality._redundancy_class(
        "back_extension", ("ssb_squat", "bench_press"), TAXONOMY, CFG
    ) == CFG.redundancy.value("partial_overlap")
    # A compound candidate that adds a different pattern is not penalised for being compound.
    assert role_quality._redundancy_class(
        "bench_press", ("ssb_squat",), TAXONOMY, CFG
    ) == CFG.redundancy.value("complementary")
    # Missing classification data is neutral.
    assert role_quality._redundancy_class(
        "chest_supported_row", ("ssb_squat",), TAXONOMY, CFG
    ) == CFG.redundancy.neutral


def test_redundancy_can_decide_between_equally_complementary_supports() -> None:
    base = _reduced_template("squat_main", "bench_support", "core_anti_extension")
    # The always-selected accessory duplicates any horizontal push support.
    base = replace(
        base,
        slots=tuple(
            replace(slot, id="support_push", exercise="bench_press_narrow", essential=False)
            if slot.id == "core_anti_extension" else slot
            for slot in base.slots
        ),
    )
    assignment_a = {
        "squat_main": "ssb_squat",
        "bench_support": "bench_press",
        "support_push": "bench_press_narrow",
    }
    assignment_b = {**assignment_a, "bench_support": "dumbbell_row"}
    a = _snapshot_with(base=base, assignment=assignment_a)
    b = _snapshot_with(base=base, assignment=assignment_b)
    assert a.roles["secondary"][0]["classes"]["complementarity"] == CFG.complementarity.value("complementary")
    assert b.roles["secondary"][0]["classes"]["complementarity"] == CFG.complementarity.value("complementary")
    assert a.roles["secondary"][0]["classes"]["redundancy"] == CFG.redundancy.value("duplicate")
    assert b.roles["secondary"][0]["classes"]["redundancy"] == CFG.redundancy.value("complementary")
    assert b.vector < a.vector


# ---------------------------------------------------------------------------
# Accessory coverage
# ---------------------------------------------------------------------------


def test_coverage_excludes_the_candidate_itself() -> None:
    # The candidate is the only selected exercise with its pattern; coverage must not count it.
    assert role_quality._coverage_class(
        "dumbbell_row", ("ssb_squat", "bench_press"), TAXONOMY, CFG
    ) == CFG.coverage.value("uncovered")
    # Another selected exercise already covers the pattern.
    assert role_quality._coverage_class(
        "bench_press_narrow", ("ssb_squat", "bench_press"), TAXONOMY, CFG
    ) == CFG.coverage.value("covered")
    # Missing taxonomy is neutral, never a new uncovered pattern.
    assert role_quality._coverage_class(
        "chest_supported_row", ("ssb_squat",), TAXONOMY, CFG
    ) == CFG.coverage.neutral
    assert role_quality._coverage_class(
        "dumbbell_row", (), TAXONOMY, CFG
    ) == CFG.coverage.neutral


def test_multiple_accessories_are_evaluated_symmetrically() -> None:
    # Each accessory sees the other as covering horizontal pull, so neither is uniquely
    # uncovered and the result does not depend on slot order.
    first = role_quality._coverage_class(
        "dumbbell_row", ("ssb_squat", "bent_over_row"), TAXONOMY, CFG
    )
    second = role_quality._coverage_class(
        "bent_over_row", ("ssb_squat", "dumbbell_row"), TAXONOMY, CFG
    )
    assert first == second == CFG.coverage.value("covered")


def test_accessory_coverage_can_decide_the_winner() -> None:
    base, assignment_a = _secondary_assignment("bench_press", "dumbbell_row")
    assignment_b = {**assignment_a, "core_anti_extension": "bench_press_narrow"}
    a = _snapshot_with(base=base, assignment=assignment_a)
    b = _snapshot_with(base=base, assignment=assignment_b)
    assert a.roles["accessory"][0]["classes"]["coverage"] == CFG.coverage.value("uncovered")
    assert b.roles["accessory"][0]["classes"]["coverage"] == CFG.coverage.value("covered")
    assert a.vector < b.vector


# ---------------------------------------------------------------------------
# Accessory stimulus-to-fatigue
# ---------------------------------------------------------------------------


def test_stimulus_to_fatigue_uses_role_specific_mandatory_tax_axes() -> None:
    assert CFG.tax_mandatory_axes["accessory"] == ("axial", "skill")
    assert CFG.tax_mandatory_axes["essential"] == ("axial", "systemic", "skill")
    # The two inputs are recorded independently, then mapped through the configured matrix.
    assert role_quality._stimulus_inputs("ab_wheel", False, TAX, CFG) == (2, 1)
    assert role_quality._stimulus_to_fatigue_class(
        "ab_wheel", False, TAX, CFG
    ) == CFG.stimulus_to_fatigue.value("moderate_low")
    assert role_quality._stimulus_to_fatigue_class(
        "dumbbell_row", False, TAX, CFG
    ) == CFG.stimulus_to_fatigue.value("high_moderate")
    assert role_quality._stimulus_to_fatigue_class(
        "front_squat", False, TAX, CFG
    ) == CFG.stimulus_to_fatigue.value("high_high")
    # Missing tax data is neutral; it is not assumed to be lower cost.
    assert role_quality._stimulus_inputs("lying_leg_curls", False, TAX, CFG) == (2, None)
    assert role_quality._stimulus_to_fatigue_class(
        "lying_leg_curls", False, TAX, CFG
    ) == CFG.stimulus_to_fatigue.neutral
    # Missing stimulus is neutral even when the tax is known.
    assert role_quality._stimulus_inputs("chest_supported_row", False, TAX, CFG) == (None, None)
    assert role_quality._stimulus_to_fatigue_class(
        "chest_supported_row", False, TAX, CFG
    ) == CFG.stimulus_to_fatigue.neutral


def test_stimulus_matrix_prefers_dominance_not_a_ratio() -> None:
    high_low = CFG.stimulus_to_fatigue.value("high_low")
    high_moderate = CFG.stimulus_to_fatigue.value("high_moderate")
    high_high = CFG.stimulus_to_fatigue.value("high_high")
    moderate_low = CFG.stimulus_to_fatigue.value("moderate_low")
    moderate_moderate = CFG.stimulus_to_fatigue.value("moderate_moderate")
    moderate_high = CFG.stimulus_to_fatigue.value("moderate_high")
    low_high = CFG.stimulus_to_fatigue.value("low_high")
    assert high_low > high_moderate > high_high
    assert moderate_low > moderate_moderate > moderate_high
    assert high_low > moderate_low
    assert high_high == moderate_moderate == CFG.stimulus_to_fatigue.value("low_low")
    assert moderate_high == CFG.stimulus_to_fatigue.value("low_moderate")
    assert low_high < moderate_high


def test_stimulus_to_fatigue_can_decide_between_equally_covering_accessories() -> None:
    base, assignment_a = _secondary_assignment("bench_press", "lat_pulldown")
    assignment_b = {**assignment_a, "core_anti_extension": "pull_up"}
    a = _snapshot_with(base=base, assignment=assignment_a)
    b = _snapshot_with(base=base, assignment=assignment_b)
    # Both cover vertical pull; the moderate-stimulus/low-cost option wins, and the snapshot
    # records that its stimulus rating is provisional.
    assert a.roles["accessory"][0]["classes"]["coverage"] == CFG.coverage.value("uncovered")
    assert b.roles["accessory"][0]["classes"]["coverage"] == CFG.coverage.value("uncovered")
    assert a.roles["accessory"][0]["classes"]["stimulus_to_fatigue"] == (
        CFG.stimulus_to_fatigue.value("moderate_low")
    )
    assert b.roles["accessory"][0]["classes"]["stimulus_to_fatigue"] == (
        CFG.stimulus_to_fatigue.value("moderate_moderate")
    )
    assert a.vector < b.vector
    assert role_quality.STIMULUS_PROVISIONAL in a.limitations


# ---------------------------------------------------------------------------
# Snapshot invariants
# ---------------------------------------------------------------------------


def test_role_quality_snapshot_has_roles_and_a_lexicographic_vector() -> None:
    snapshot = _snapshot()
    assert snapshot.roles["main"]
    assert snapshot.roles["secondary"]
    assert snapshot.vector[0:2] == (0, 0)
    assert len(snapshot.vector) > 2
    assert snapshot.as_dict()["version"] == role_quality.VERSION


def test_accessory_snapshot_reports_its_own_pattern_as_uncovered() -> None:
    snapshot = _snapshot()
    by_slot = {
        entry["slot_id"]: entry["classes"]
        for entry in snapshot.roles["accessory"]
    }
    # These accessory patterns are not duplicated by the other selected roles in the
    # default squat assignment; the old self-inclusive set made every one of them "covered".
    assert by_slot["accessory_row"]["coverage"] == CFG.coverage.value("uncovered")
    assert by_slot["accessory_knee_flexion"]["coverage"] == CFG.coverage.value("uncovered")
    assert role_quality.STIMULUS_PROVISIONAL in snapshot.limitations
    # lying_leg_curls has a stimulus rating but no tax entry, so the snapshot says the input
    # is missing rather than guessing a cost.
    assert role_quality.STIMULUS_MISSING in snapshot.limitations


def test_band_and_intent_penalties_change_the_first_vector_positions() -> None:
    clean = _snapshot()
    gated = _snapshot(band_penalty=1, intent_penalty=1)
    assert gated.vector[:2] == (1, 1)
    assert gated.vector[:2] != clean.vector[:2]
    assert clean.vector[2:] == gated.vector[2:]


def test_missing_exposure_is_neutral_not_zero() -> None:
    base = templates.SessionTemplate.load("squat")
    assignment = {slot.id: slot.exercises[0] for slot in base.slots}
    items = tuple(
        _item(index, slot, slot.exercises[0], intensity=None)
        for index, slot in enumerate(base.slots)
    )
    prescription = Prescription(
        for_date="2024-01-15",
        session_type=base.session_type,
        fallback_level="none",
        rule_document_version="test",
        items=items,
    )
    with db.Store(":memory:") as store:
        snapshot = role_quality.snapshot(
            conn=store.connection,
            for_date="2024-01-15",
            base=base,
            assignment=assignment,
            prescription=prescription,
            band_penalty=0,
            intent_penalty=0,
        )
    main = snapshot.roles["main"][0]["classes"]
    assert main["exposure"] == 1
    assert "missing_item" not in snapshot.limitations
