"""Minimum-session shape selection for the resolver."""

from __future__ import annotations

from strength_coach.prescribe import minimum_session
from strength_coach.store import db


def test_main_lift_shape_keeps_essential_slots_and_trims_optional_slots():
    store = db.Store(":memory:")
    try:
        shape = minimum_session.build_resolver_shape(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            target_minutes=30,
            include_main=False,
            accessories_only=False,
        )
    finally:
        store.close()
    assert shape.note["status"] == "partial"
    assert "squat_main" in shape.note["retained_slots"]
    assert "bench_support" in shape.note["retained_slots"]
    assert "power" in shape.note["omitted_slots"]
    assert "squat" in shape.retained_patterns


def test_include_main_reduces_main_sets_to_floor():
    store = db.Store(":memory:")
    try:
        shape = minimum_session.build_resolver_shape(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            target_minutes=45,
            include_main=True,
            accessories_only=False,
        )
    finally:
        store.close()
    slots = {slot.id: slot for slot in shape.template.slots}
    assert slots["squat_main"].sets == 2
    assert slots["bench_support"].sets == 2


def test_accessories_only_removes_all_essential_slots():
    store = db.Store(":memory:")
    try:
        shape = minimum_session.build_resolver_shape(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            target_minutes=45,
            include_main=False,
            accessories_only=True,
        )
    finally:
        store.close()
    assert shape.note["accessories_only"] is True
    assert not any(slot.essential for slot in shape.template.slots)
    assert "squat_main" in shape.note["omitted_slots"]
    assert "bench_support" in shape.note["omitted_slots"]
    assert shape.note["retained_slots"]


def test_optional_slots_are_ordered_by_least_recent_pattern():
    store = db.Store(":memory:")
    try:
        shape = minimum_session.build_resolver_shape(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            target_minutes=60,
            include_main=False,
            accessories_only=False,
        )
    finally:
        store.close()
    # With no history every optional slot ties; the retained list must still be deterministic.
    assert shape.note["retained_slots"] == [
        "squat_main", "bench_support", "erector", "accessory_row",
        "accessory_knee_flexion", "core_anti_extension",
    ]
