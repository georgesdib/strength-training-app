"""Step 3 engine integration: top-set structure and hinge maximal change."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach import settings_profile
from strength_coach.features.deload import DeloadDecision
from strength_coach.prescribe import build_prescription, engine, loads
from strength_coach.prescribe import top_set as top_set_mod
from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.prescribe.resolver_settings import ResolverSettings
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30",
     "RIR": "3", "Reps_Done": "8"},
    {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-15", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
]


@contextmanager
def store_with(block_start="2024-01-01", competition_date=None):
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        repositories.append_athlete_profile(
            store.connection,
            effective_from="2024-01-01",
            block_start_date=block_start,
            competition_date=competition_date,
        )
        yield store
    finally:
        store.close()


def _item(prescription, exercise_id):
    return next(item for item in prescription.items if item.exercise_id == exercise_id)


def test_top_set_applies_to_the_session_main_and_preserves_sets() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            top_set_intent="required",
        )
    main = _item(prescription, "ssb_squat")
    assert prescription.notes["top_set"]["status"] == "applied"
    assert prescription.notes["top_set"]["reason_code"] == "applied"
    assert [group.role for group in main.set_groups] == ["top_set", "back_off"]
    assert sum(group.sets for group in main.set_groups) == main.sets
    assert main.set_groups[0].rir_target == 1
    assert main.set_groups[0].load_kg > main.set_groups[1].load_kg
    assert main.warmup[0].load_kg < main.load_kg


def test_structured_intensity_is_the_set_weighted_mean() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            top_set_intent="required",
        )
    main = _item(prescription, "ssb_squat")
    assert main.set_groups
    weighted = sum(
        group.sets * group.load_kg for group in main.set_groups
    ) / main.sets
    assert main.intensity == pytest.approx(weighted / main.e1rm_kg)
    # The stored item load is the back-off load, so its ratio alone would understate the day.
    assert main.intensity > main.load_kg / main.e1rm_kg


def test_deload_suppresses_top_set_and_keeps_the_plan_executable() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            top_set_intent="required",
            deload_decision=DeloadDecision(reason="test deload", trigger="test"),
        )
    main = _item(prescription, "ssb_squat")
    assert main.set_groups == ()
    assert prescription.notes["top_set"]["status"] == "not_applicable"
    assert prescription.notes["top_set"]["reason_code"] == "blocked_by_design"
    assert "deload" in prescription.notes["top_set"]["reason"]


def test_default_off_builds_straight_sets() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="squat"
        )
    main = _item(prescription, "ssb_squat")
    assert main.set_groups == ()
    assert prescription.notes["top_set"]["status"] == "not_applicable"
    assert prescription.notes["top_set"]["reason_code"] == "intent_off"


def test_competition_taper_removes_the_top_set() -> None:
    with store_with(competition_date="2024-01-18") as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            top_set_intent="required",
        )
    assert prescription.notes["top_set"]["status"] == "not_applicable"
    assert prescription.notes["top_set"]["reason_code"] == "blocked_by_design"
    assert "taper" in prescription.notes["top_set"]["reason"]


def test_warmup_uses_the_final_throttled_top_set_load() -> None:
    with store_with() as store:
        baseline = build_prescription(
            store.connection, for_date="2024-01-15", session_type="squat",
            top_set_intent="required",
        )
        throttled = build_prescription(
            store.connection, for_date="2024-01-15", session_type="squat",
            top_set_intent="required", technique_throttle=True,
        )
    base_main = _item(baseline, "ssb_squat")
    throttle_main = _item(throttled, "ssb_squat")
    expected_top = loads.round_down(
        base_main.set_groups[0].load_kg * 0.90,
        throttle_main.rounding_increment_kg,
    )
    assert throttle_main.set_groups[0].load_kg == expected_top
    assert throttle_main.warmup
    assert throttle_main.warmup[0].load_kg == 20.0
    assert throttle_main.warmup[0].load_kg < throttle_main.set_groups[0].load_kg
    assert throttle_main.warmup[1].load_kg == loads.round_down(
        expected_top * 0.50, throttle_main.rounding_increment_kg
    )


def test_rir_provenance_separates_readiness_from_caution() -> None:
    # Only the readiness/floor step may be absorbed by the ceiling. Flare and continuity
    # bumps come from a safety signal and keep the straight-set fallback.
    assert engine._top_set_rir_bumps(2, 3, 3, 3) == (1, None)
    assert engine._top_set_rir_bumps(2, 4, 4, 4) == (2, None)
    assert engine._top_set_rir_bumps(2, 3, 4, 4) == (
        1,
        "back flare held the primary lift; straight sets",
    )
    assert engine._top_set_rir_bumps(2, 2, 2, 3) == (
        0,
        "continuity caution held the primary lift; straight sets",
    )
    assert engine._top_set_rir_bumps(None, 3, 3, 3) == (0, None)


def test_hinge_maximal_is_allowed_and_warned() -> None:
    with store_with() as store:
        prescription = build_prescription(
            store.connection,
            for_date="2024-01-15",
            session_type="hinge",
            top_set_intent="required",
        )
    trap_bar = _item(prescription, "trap_bar_deadlift")
    assert (trap_bar.reps_low, trap_bar.reps_high) == (1, 3)
    assert trap_bar.set_groups
    assert trap_bar.set_groups[0].rir_target == 1
    assert any("maximal hinge allowed" in warning for warning in prescription.warnings)


def _resolver_settings() -> ResolverSettings:
    return ResolverSettings.from_values(settings_profile.resolved_registry())


def _top_set_item(**overrides) -> PrescriptionItem:
    base: dict = {
        "order_index": 0,
        "exercise_id": "ssb_squat",
        "sets": 3,
        "reps_low": 3,
        "reps_high": 5,
        "load_kg": 100.0,
        "load_basis": "external",
        "rounding_increment_kg": 0.5,
        "rir_target": 2,
        "rest_s": 180,
        "essential": True,
        "e1rm_kg": 120.0,
    }
    base.update(overrides)
    return PrescriptionItem(**base)


def _plan(intent: str, item: PrescriptionItem):
    return top_set_mod.plan_top_set(
        item,
        settings=_resolver_settings(),
        eligible_lifts=("ssb_squat",),
        primary_exercise="ssb_squat",
        scheme="strength",
        competition_date=None,
        for_date="2024-01-15",
        deload=False,
        intent=intent,
    )


def test_preferred_applies_on_an_eligible_main() -> None:
    plan = _plan("preferred", _top_set_item())
    assert plan.status == "applied"
    assert plan.reason_code == "applied"
    assert plan.applied is True
    assert len(plan.groups) == 2


def test_off_intent_is_not_applicable_even_when_eligible() -> None:
    plan = _plan("off", _top_set_item())
    assert plan.status == "not_applicable"
    assert plan.reason_code == "intent_off"
    assert plan.applied is False
    assert plan.groups == ()


def test_preferred_falls_back_on_an_unexpected_blocker() -> None:
    plan = _plan("preferred", _top_set_item(load_kg=None, e1rm_kg=None))
    assert plan.status == "fallback"
    assert plan.reason_code == "no_usable_load"
    assert plan.applied is False


def test_required_marks_an_unexpected_blocker_unsatisfied() -> None:
    plan = _plan("required", _top_set_item(load_kg=None, e1rm_kg=None))
    assert plan.status == "unsatisfied"
    assert plan.reason_code == "no_usable_load"
    assert plan.applied is False
