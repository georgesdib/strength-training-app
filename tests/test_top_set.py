"""Step 3 top-set/back-off model and pure planner."""

from __future__ import annotations

import pytest

from strength_coach import settings_registry
from strength_coach.prescribe import top_set
from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.prescribe.resolver_settings import ResolverSettings


def _settings(**overrides) -> ResolverSettings:
    values = dict(settings_registry.snapshot().values)
    values.update(overrides)
    return ResolverSettings.from_values(values)


def _item(**overrides) -> PrescriptionItem:
    values = {
        "order_index": 1,
        "exercise_id": "ssb_squat",
        "sets": 4,
        "reps_low": 5,
        "reps_high": 5,
        "load_kg": 100.0,
        "load_basis": "external",
        "rounding_increment_kg": 2.5,
        "rir_target": 2,
        "rest_s": 180,
        "essential": True,
        "e1rm_kg": 130.0,
    }
    values.update(overrides)
    return PrescriptionItem(**values)


def test_top_set_plan_preserves_total_sets_and_backoff_fraction() -> None:
    item = _item()
    plan = top_set.plan_top_set(
        item,
        settings=_settings(**{"resolver.top_set.mode": "on"}),
        eligible_lifts=("ssb_squat",),
        primary_exercise="ssb_squat",
        scheme="maximal",
        competition_date=None,
        for_date="2026-11-01",
        deload=False,
        requested=True,
    )
    assert plan.applied is True
    assert plan.top_set_rir == 1
    assert [group.role for group in plan.groups] == ["top_set", "back_off"]
    assert plan.groups[0].sets == 1
    assert plan.groups[1].sets == 3
    assert plan.groups[0].sets + plan.groups[1].sets == item.sets
    applied = top_set.apply_plan(item, plan)
    assert applied.sets == item.sets
    assert sum(group.sets for group in applied.set_groups) == applied.sets
    assert plan.groups[0].load_kg > plan.groups[1].load_kg
    assert plan.groups[1].percent_of_top == pytest.approx(0.85)


def test_top_set_requires_explicit_opt_in_in_ask_mode() -> None:
    plan = top_set.plan_top_set(
        _item(),
        settings=_settings(),
        eligible_lifts=("ssb_squat",),
        primary_exercise="ssb_squat",
        scheme="strength",
        competition_date=None,
        for_date="2026-11-01",
        deload=False,
        requested=None,
    )
    assert plan.applied is False
    assert "awaiting confirmation" in plan.reason


def test_top_set_rir_and_competition_windows() -> None:
    settings = _settings()
    assert top_set.resolved_top_set_rir(
        scheme="maximal", window="none", settings=settings
    )[0] == 1
    assert top_set.resolved_top_set_rir(
        scheme="strength", window="none", settings=settings
    )[0] == 2
    assert top_set.resolved_top_set_rir(
        scheme="off", window="none", settings=settings
    )[0] == 2
    assert top_set.resolved_top_set_rir(
        scheme="strength", window="peak", settings=settings
    )[0] == 1
    assert top_set.resolved_top_set_rir(
        scheme="strength", window="taper", settings=settings
    )[0] is None
    assert top_set.competition_window("2026-11-10", "2026-11-08", settings) == "taper"
    assert top_set.competition_window("2026-11-20", "2026-11-08", settings) == "peak"
    assert top_set.competition_window("2026-10-01", "2026-11-08", settings) == "none"


def test_top_set_falls_back_when_resolved_rir_is_too_high() -> None:
    settings = _settings(
        **{
            "resolver.top_set.mode": "on",
            "resolver.top_set.rir_by_main_scheme.maximal": 3,
        }
    )
    plan = top_set.plan_top_set(
        _item(),
        settings=settings,
        eligible_lifts=("ssb_squat",),
        primary_exercise="ssb_squat",
        scheme="maximal",
        competition_date=None,
        for_date="2026-11-01",
        deload=False,
        requested=True,
    )
    assert plan.applied is False
    assert "fallback threshold" in plan.reason


def test_top_set_is_disabled_on_deload_and_for_ineligible_lifts() -> None:
    settings = _settings(**{"resolver.top_set.mode": "on"})
    deload = top_set.plan_top_set(
        _item(),
        settings=settings,
        eligible_lifts=("ssb_squat",),
        primary_exercise="ssb_squat",
        scheme="strength",
        competition_date=None,
        for_date="2026-11-01",
        deload=True,
        requested=True,
    )
    ineligible = top_set.plan_top_set(
        _item(exercise_id="back_extension", essential=False),
        settings=settings,
        eligible_lifts=("ssb_squat",),
        primary_exercise="ssb_squat",
        scheme="strength",
        competition_date=None,
        for_date="2026-11-01",
        deload=False,
        requested=True,
    )
    assert deload.applied is False
    assert "deload" in deload.reason
    assert ineligible.applied is False


def test_apply_plan_uses_backoff_load_as_the_working_summary() -> None:
    plan = top_set.plan_top_set(
        _item(),
        settings=_settings(**{"resolver.top_set.mode": "on"}),
        eligible_lifts=("ssb_squat",),
        primary_exercise="ssb_squat",
        scheme="strength",
        competition_date=None,
        for_date="2026-11-01",
        deload=False,
        requested=True,
    )
    applied = top_set.apply_plan(_item(), plan)
    assert applied.load_kg == plan.backoff_load
    assert applied.set_groups == plan.groups
