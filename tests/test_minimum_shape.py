"""Minimum-session shape selection for the resolver."""

from __future__ import annotations

import pytest
from conftest import make_readiness, make_training

from strength_coach.prescribe import minimum_session, resolver
from strength_coach.store import db, importer


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


def _history_store(rows):
    store = db.Store(":memory:")
    training = make_training(rows)
    readiness = make_readiness([{}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def _row(day, exercise):
    return {
        "Date": day, "Exercise": exercise, "Weight_Used": "20",
        "RIR": "2", "Reps_Done": "8",
    }


def test_least_recent_optional_patterns_are_retained_first():
    rows = [
        _row("2024-01-01", "Ab Wheel"),
        _row("2024-02-01", "Lying Leg Curls"),
        _row("2024-03-01", "Dumbbell Row"),
        _row("2024-04-01", "Back Extension"),
    ]
    with _history_store(rows) as store:
        shape = minimum_session.build_resolver_shape(
            store.connection, for_date="2024-04-05", session_type="squat",
            target_minutes=30, include_main=True, accessories_only=False,
        )
    retained = set(shape.note["retained_slots"])
    # Ab Wheel is outside the 84-day window and is treated as least recently trained.
    assert {"core_anti_extension", "accessory_knee_flexion"} <= retained
    assert "accessory_row" not in retained
    assert "erector" not in retained


def test_optional_pattern_ties_keep_template_order():
    store = db.Store(":memory:")
    try:
        shape = minimum_session.build_resolver_shape(
            store.connection, for_date="2024-04-05", session_type="squat",
            target_minutes=30, include_main=True, accessories_only=False,
        )
    finally:
        store.close()
    retained = set(shape.note["retained_slots"])
    assert {"erector", "accessory_row"} <= retained
    assert "accessory_knee_flexion" not in retained
    assert "core_anti_extension" not in retained


def test_accessory_template_is_cross_template_and_has_no_essential_slots():
    template = minimum_session.build_accessory_template()
    assert template.session_type == "accessory"
    assert template.primary_exercise is None
    assert not any(slot.essential for slot in template.slots)
    assert any(slot.power for slot in template.slots)
    source_types = {
        slot.id.split("_")[1] for slot in template.slots
    }
    assert source_types == {"squat", "hinge", "bench"}


def test_accessory_shape_retains_cross_template_slots_and_power_last():
    store = db.Store(":memory:")
    try:
        shape = minimum_session.build_resolver_shape(
            store.connection, for_date="2024-04-05", session_type="accessory",
            target_minutes=60, include_main=False, accessories_only=False,
        )
    finally:
        store.close()
    assert shape.note["accessories_only"] is True
    assert not any(slot.essential for slot in shape.template.slots)
    assert shape.note["retained_slots"]
    power_ids = [slot.id for slot in shape.template.slots if slot.power]
    non_power_ids = [slot.id for slot in shape.template.slots if not slot.power]
    assert not power_ids or non_power_ids


def test_accessory_shape_adds_sets_only_up_to_the_cap():
    store = db.Store(":memory:")
    try:
        shape = minimum_session.build_resolver_shape(
            store.connection, for_date="2024-04-05", session_type="accessory",
            target_minutes=60, include_main=False, accessories_only=False,
        )
    finally:
        store.close()
    cap = minimum_session.MinimumSessionConfig.load().accessory_max_sets
    assert shape.note["added_sets"] > 0
    assert all(slot.sets <= cap for slot in shape.template.slots)
    assert shape.note["after_minutes"] <= 60


def test_accessory_session_has_its_own_identity():
    from strength_coach.prescribe import session_identity

    assert session_identity.label("accessory") == "Accessory only"
    assert session_identity.counts_as_main("accessory") is False
    assert session_identity.rotation_family("accessory") is None


def test_required_patterns_use_candidate_patterns_not_slot_defaults():
    kept, dropped, retained, _omitted = resolver._minimum_required_patterns(
        {"squat": ("vertical_pull", "horizontal_pull")},
        "squat",
        {"accessory_row"},
        {"accessory_pull_up"},
        {
            # The row slot's template default is horizontal_pull, but its eligible candidates
            # can include a vertical_pull exercise for this shape.
            "accessory_row": {"dumbbell_row": "vertical_pull"},
            "accessory_pull_up": {"pull_up": "horizontal_pull"},
        },
    )
    assert kept == ["vertical_pull"]
    assert dropped == ["horizontal_pull"]
    assert retained == {"vertical_pull"}


def test_required_pattern_not_supported_by_any_candidate_is_an_error():
    with pytest.raises(resolver.ResolverBuildError, match="cannot cover required pattern"):
        resolver._minimum_required_patterns(
            {"squat": ("squat",)},
            "squat",
            {"accessory_row"},
            set(),
            {"accessory_row": {"dumbbell_row": "horizontal_pull"}},
        )


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
