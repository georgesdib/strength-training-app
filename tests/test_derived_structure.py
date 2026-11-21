"""WP5 derived actual structure: descriptive, confidence-bearing, no metric effect."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from strength_coach.features import derived_structure

FIXTURE = Path(__file__).parent / "fixtures" / "resolver_structure" / \
    "straight_set_plan_top_backoff_performance.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_worked_example_is_a_top_set_like_exposure_not_descending_only() -> None:
    fixture = _fixture()
    result = derived_structure.derive(
        fixture["performed"], item={"rounding_increment_kg": 2.5}
    )
    assert result["structure"] == fixture["expected"]["structure"]
    assert result["confidence"] == fixture["expected"]["confidence"]
    assert result["structure"] != fixture["expected"]["not"]
    assert result["working_sets"] == 4
    assert [segment["kind"] for segment in result["segments"]] == [
        "top_set_like_effort", "back_off_sequence"
    ]
    top = result["segments"][0]["evidence"]
    assert top["load_kg"] == 180
    assert top["rir"] == 1
    assert top["reps"] == 4
    assert top["gap_increments"] == 8


def test_straight_working_sets_are_constant() -> None:
    rows = [
        {"set_index": index, "load_kg": 100, "reps": 5, "rir": 2}
        for index in range(1, 5)
    ]
    result = derived_structure.derive(rows, item={"rounding_increment_kg": 2.5})
    assert result["structure"] == "straight_working_sets"
    assert result["load_shape"] == "constant"
    assert result["confidence"] == "high"


def test_missing_rir_lowers_confidence_and_missing_load_is_ambiguous() -> None:
    no_rir = [
        {"set_index": 1, "load_kg": 100, "reps": 5},
        {"set_index": 2, "load_kg": 100, "reps": 5},
    ]
    result = derived_structure.derive(no_rir, item={"rounding_increment_kg": 2.5})
    assert result["structure"] == "straight_working_sets"
    assert result["confidence"] == "medium"
    assert "missing_rir" in result["limitations"]

    no_load = [
        {"set_index": 1, "reps": 5, "rir": 2},
        {"set_index": 2, "reps": 5, "rir": 2},
    ]
    result = derived_structure.derive(no_load, item={"rounding_increment_kg": 2.5})
    assert result["structure"] == "ambiguous"
    assert result["confidence"] == "unknown"
    assert "missing_load" in result["limitations"]


def test_warm_ups_are_preparatory_and_never_working() -> None:
    rows = [
        {"set_index": 1, "load_kg": 40, "reps": 8, "rir": 6},
        {"set_index": 2, "load_kg": 80, "reps": 5, "rir": 6},
    ]
    result = derived_structure.derive(rows, item={"rounding_increment_kg": 2.5})
    assert result["structure"] == "insufficient_data"
    assert result["working_sets"] == 0
    assert result["warm_up_sets"] == 2
    assert result["segments"][0]["kind"] == "preparatory_progression"


def test_multiple_heavy_exposures_are_not_collapsed_to_straight() -> None:
    rows = [
        {"set_index": 1, "load_kg": 180, "reps": 4, "rir": 1},
        {"set_index": 2, "load_kg": 160, "reps": 5, "rir": 3},
        {"set_index": 3, "load_kg": 180, "reps": 4, "rir": 1},
        {"set_index": 4, "load_kg": 160, "reps": 5, "rir": 3},
    ]
    result = derived_structure.derive(rows, item={"rounding_increment_kg": 2.5})
    assert result["structure"] == "multiple_heavy_exposures"


def test_derivation_never_mutates_the_raw_rows() -> None:
    fixture = _fixture()
    rows = copy.deepcopy(fixture["performed"])
    before = copy.deepcopy(rows)
    derived_structure.derive(rows, item={"rounding_increment_kg": 2.5})
    assert rows == before


def test_config_is_versioned_and_has_the_approved_defaults() -> None:
    config = derived_structure.StructureConfig.load()
    assert config.version == 1
    assert config.load_tolerance_increments == 1
    assert config.rir_tolerance == 1
    assert config.min_load_gap_increments == 2
    assert config.min_back_off_sets == 2

