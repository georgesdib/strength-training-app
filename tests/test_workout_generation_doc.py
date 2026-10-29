"""The workout-generation worked example must be an actual engine output.

The document is a user-facing explanation, but its numbers are still claims about the engine.
They previously drifted because they were hand-written. The renderer in
tools/workout_generation_example.py builds the example from a fixed synthetic fixture; this
test is the anti-drift contract, and the pinned assertions below also prove the renderer is
looking at a meaningful engine result rather than an empty run.
"""

from __future__ import annotations

from pathlib import Path

from test_prescribe import BASE_HISTORY

from tools import workout_generation_example as example

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "WORKOUT-GENERATION.md"


def test_the_fixture_is_the_prescribe_base_history():
    assert example.load_fixture()["history"] == BASE_HISTORY


def test_the_documented_block_is_generated_from_the_engine():
    text = DOC.read_text(encoding="utf-8")
    assert example.extract(text) == example.render()
    assert "<!-- END GENERATED WORKOUT EXAMPLE -->" in text


def test_the_example_pins_the_current_hinge_result():
    normal, poor = example.build()

    assert normal.session_type == "hinge"
    assert normal.fallback_level == "full"
    assert normal.executable
    assert normal.time_cap_s == 4800
    assert [
        (item.exercise_id, item.sets, item.load_kg, item.rir_target)
        for item in normal.items
    ] == [
        ("trap_bar_deadlift", 5, 158.5, 2),
        ("bench_press_narrow", 4, 95.0, 2),
        ("pull_up", 4, 0.0, 2),
        ("dumbbell_row", 4, 30.0, 2),
        ("split_squat", 4, 30.0, 2),
        ("lying_leg_curls", 4, 30.0, 2),
    ]
    # The extra accessory set comes from the under-MEV rule, not from the template.
    assert "MOD-VOL-002" in next(
        item for item in normal.items if item.exercise_id == "dumbbell_row"
    ).rationale_refs
    assert any("readiness unknown" in warning for warning in normal.warnings)
    assert any("one eligible set" in warning for warning in normal.warnings)

    assert poor.fallback_level == "fatigue_reduced"
    assert [item.sets for item in poor.items] == [5, 4, 2, 2, 2, 2]
    assert [item.load_kg for item in poor.items] == [146.0, 87.5, 0.0, 27.5, 27.5, 27.5]
    assert all(item.rir_target == 3 for item in poor.items)
    assert poor.notes["under_mev"]["applied"] is False


def test_the_example_block_round_trips():
    text = DOC.read_text(encoding="utf-8")
    block = example.render()
    assert example.replace(text, block) == text


def test_the_example_source_digest_is_stable():
    assert example.source_digest() == example.source_digest()
    assert example.render() == example.render()
