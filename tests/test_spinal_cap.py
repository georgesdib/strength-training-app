"""W9: every high-fatigue entity has an explicit cost, and the cap is visible."""

from __future__ import annotations

from test_prescribe import BASE_HISTORY, store_with

from strength_coach.prescribe import build_prescription
from strength_coach.utils import exercises


def test_every_high_fatigue_entity_has_an_explicit_cost():
    entities = exercises.taxonomy().entities
    missing = [
        key for key, value in entities.items()
        if value.get("high_fatigue_spinal") and value.get("spinal_cost") is None
    ]
    assert missing == []


def test_single_leg_rdl_is_explicitly_not_counted():
    entity = exercises.taxonomy().entities["single_leg_db_rdl"]
    assert entity.get("high_fatigue_spinal") is False
    assert entity.get("spinal_cost") == 0


def test_competition_squat_counts_as_one_exposure():
    entity = exercises.taxonomy().entities["competition_squat"]
    assert entity.get("high_fatigue_spinal") is True
    assert entity.get("spinal_cost") == 1


def test_bench_hinge_uses_sumo_deadlift():
    with store_with(BASE_HISTORY) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="bench_hinge",
        )
    assert "sumo_deadlift" in {item.exercise_id for item in prescription.items}


def test_prescription_exposes_spinal_cap_headroom():
    with store_with(BASE_HISTORY) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-15", session_type="hinge",
        )
    spinal = prescription.notes["spinal_cap"]
    assert spinal["cap"] == 6
    assert spinal["cost"] >= 0
    assert "headroom" in spinal
    assert "at_cap" in spinal
