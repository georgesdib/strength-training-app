"""Weekly spinal exposure grouping: sets, intensity bands and exclusions."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from strength_coach.rules.context import RuleContext
from strength_coach.rules.registry import spinal_exposures
from strength_coach.utils import exercises

SET_FACTORS = [
    {"max": 3, "factor": 0.85},
    {"max": 5, "factor": 1.0},
    {"max": 1000, "factor": 1.15},
]
INTENSITY_FACTORS = [
    {"max": 0.75, "factor": 0.85},
    {"max": 0.85, "factor": 1.0},
    {"max": 10, "factor": 1.15},
]


def rule(excluded=()):
    return SimpleNamespace(params={
        "costs": {"trap_bar_deadlift": 2, "back_extension": 1},
        "set_factors": SET_FACTORS,
        "intensity_factors": INTENSITY_FACTORS,
        "excluded_patterns": list(excluded),
    })


def context(rows):
    return RuleContext(
        sets=pd.DataFrame(rows),
        sessions=pd.DataFrame(),
        entities=exercises.taxonomy().entities,
    )


def test_sets_and_intensity_bands_are_applied_per_week():
    exposures = spinal_exposures(rule(), context([
        {"date": pd.Timestamp("2024-01-02"), "session_id": "s1",
         "exercise_id": "trap_bar_deadlift", "is_working_set": True,
         "load_kg": 150.0, "e1rm_kg": 200.0},
        {"date": pd.Timestamp("2024-01-02"), "session_id": "s1",
         "exercise_id": "trap_bar_deadlift", "is_working_set": True,
         "load_kg": 150.0, "e1rm_kg": 200.0},
        {"date": pd.Timestamp("2024-01-09"), "session_id": "s2",
         "exercise_id": "trap_bar_deadlift", "is_working_set": True,
         "load_kg": 160.0, "e1rm_kg": 200.0},
    ]))

    # 2 sets at 75% e1RM: set band 0.85, intensity band 0.85, base cost 2.
    assert exposures["2024-W01"] == {("s1", "trap_bar_deadlift"): pytest.approx(1.445)}
    # one set at 80% e1RM: set band 0.85, intensity band 1.0, base cost 2.
    assert exposures["2024-W02"] == {("s2", "trap_bar_deadlift"): pytest.approx(1.7)}


def test_a_missing_e1rm_poisons_its_group_mean():
    exposures = spinal_exposures(rule(), context([
        {"date": pd.Timestamp("2024-01-16"), "session_id": "s3",
         "exercise_id": "trap_bar_deadlift", "is_working_set": True,
         "load_kg": 100.0, "e1rm_kg": float("nan")},
        {"date": pd.Timestamp("2024-01-16"), "session_id": "s3",
         "exercise_id": "trap_bar_deadlift", "is_working_set": True,
         "load_kg": 140.0, "e1rm_kg": 200.0},
        {"date": pd.Timestamp("2024-01-16"), "session_id": "s4",
         "exercise_id": "back_extension", "is_working_set": True,
         "load_kg": 14.0, "e1rm_kg": 20.0},
    ]))

    # NaN in the group mean falls back to the neutral intensity band, not to the 70% band.
    assert exposures["2024-W03"][("s3", "trap_bar_deadlift")] == pytest.approx(2.0 * 0.85 * 1.0)
    assert exposures["2024-W03"][("s4", "back_extension")] == pytest.approx(1.0 * 0.85 * 0.85)


def test_zero_load_and_non_spinal_work_are_ignored():
    exposures = spinal_exposures(rule(), context([
        {"date": pd.Timestamp("2024-01-23"), "session_id": "s5",
         "exercise_id": "trap_bar_deadlift", "is_working_set": True,
         "load_kg": 150.0, "e1rm_kg": 200.0},
        {"date": pd.Timestamp("2024-01-23"), "session_id": "s5",
         "exercise_id": "trap_bar_deadlift", "is_working_set": True,
         "load_kg": 0.0, "e1rm_kg": 0.0},
        {"date": pd.Timestamp("2024-01-23"), "session_id": "s5",
         "exercise_id": "bench_press", "is_working_set": True,
         "load_kg": 100.0, "e1rm_kg": 120.0},
        {"date": pd.Timestamp("2024-01-23"), "session_id": "s5",
         "exercise_id": "trap_bar_deadlift", "is_working_set": False,
         "load_kg": 150.0, "e1rm_kg": 200.0},
    ]))

    assert list(exposures) == ["2024-W04"]
    assert exposures["2024-W04"] == {("s5", "trap_bar_deadlift"): pytest.approx(2.0 * 0.85 * 0.85)}


def test_excluded_patterns_never_consume_a_slot():
    exposures = spinal_exposures(rule(excluded=["hinge"]), context([
        {"date": pd.Timestamp("2024-01-30"), "session_id": "s6",
         "exercise_id": "trap_bar_deadlift", "is_working_set": True,
         "load_kg": 150.0, "e1rm_kg": 200.0},
        {"date": pd.Timestamp("2024-01-30"), "session_id": "s6",
         "exercise_id": "back_extension", "is_working_set": True,
         "load_kg": 14.0, "e1rm_kg": 20.0},
    ]))

    assert "trap_bar_deadlift" not in {exercise for (_s, exercise) in exposures["2024-W05"]}
    assert ("s6", "back_extension") in exposures["2024-W05"]


def test_proposed_entries_are_added_alongside_stored_sets():
    exposures = spinal_exposures(
        rule(),
        context([]),
        extra=[("s7", "trap_bar_deadlift", "2024-02-06", 4, 0.9)],
    )

    # 4 sets: band 1.0; 90% e1RM: band 1.15; base cost 2.
    assert exposures["2024-W06"] == {("s7", "trap_bar_deadlift"): pytest.approx(2.0 * 1.0 * 1.15)}


def test_an_empty_frame_has_no_exposures():
    assert spinal_exposures(rule(), context([])) == {}
