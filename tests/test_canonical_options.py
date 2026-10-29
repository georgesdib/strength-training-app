"""Canonical athlete-state vocabulary and web validation contracts."""

from __future__ import annotations

import pytest

from strength_coach.domain import athlete_state
from strength_coach.web import options as options_mod
from strength_coach.web import validation


def test_athlete_state_constants_match_the_schema_check_values():
    assert set(athlete_state.GOALS) == {
        "strength", "hypertrophy", "body_comp", "pain_free", "longevity", "competition",
    }
    assert set(athlete_state.CONSTRAINT_KINDS) == {
        "injury", "contraindication", "mobility", "asymmetry",
    }
    assert set(athlete_state.SEVERITIES) == {"hard_exclude", "caution", "monitor"}


def test_canonical_options_are_derived_from_the_taxonomy_and_config():
    options = options_mod.canonical_options()
    assert [row["value"] for row in options["goals"]] == list(athlete_state.GOALS)
    assert {row["value"] for row in options["regions"]} >= {"low_back", "biceps", "knee"}
    assert "squat" in {row["value"] for row in options["patterns"]}
    assert "quadriceps" in {row["value"] for row in options["muscles"]}
    assert options["exercises"]
    assert "ssb_squat" in {row["value"] for row in options["exercises"]}


@pytest.mark.parametrize(("value", "allowed", "field"), [
    ("health", athlete_state.GOALS, "primary_goal"),
    ("Strength", athlete_state.GOALS, "primary_goal"),
    ("rom", athlete_state.CONSTRAINT_KINDS, "kind"),
    ("preference", athlete_state.CONSTRAINT_KINDS, "kind"),
    ("blocked", athlete_state.SEVERITIES, "severity"),
])
def test_choice_rejects_unknown_values(value, allowed, field):
    with pytest.raises(ValueError, match=field):
        validation.choice(value, allowed, field)


def test_choice_returns_the_canonical_value():
    assert validation.choice(" strength ", athlete_state.GOALS, "primary_goal") == "strength"


def test_list_choice_rejects_an_unknown_member():
    with pytest.raises(ValueError, match="forbidden_patterns"):
        validation.list_choice(["squat", "sqaut"], ("squat", "hinge"), "forbidden_patterns")


def test_exercise_id_requires_a_canonical_id():
    assert validation.exercise_id("ssb_squat") == "ssb_squat"
    with pytest.raises(ValueError, match="unknown exercise id"):
        validation.exercise_id("not_a_lift")


def test_exercise_ids_preserve_order():
    assert validation.exercise_ids(["ssb_squat", "bench_press"]) == [
        "ssb_squat", "bench_press",
    ]


def test_region_is_limited_to_configured_regions():
    assert validation.region("low_back") == "low_back"
    with pytest.raises(ValueError, match="region"):
        validation.region("elbow")
