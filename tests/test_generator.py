"""Step 2 generator core: deterministic selection, eligibility and availability."""

from __future__ import annotations

import json

import pytest
import yaml

from strength_coach import settings_registry
from strength_coach.prescribe import generator, resolver_policy, templates
from strength_coach.prescribe.resolver_settings import ResolverSettings
from strength_coach.store import db, repositories
from strength_coach.utils import paths


def _settings(**overrides) -> ResolverSettings:
    values = dict(settings_registry.snapshot().values)
    values.update(overrides)
    return ResolverSettings.from_values(values)


def _rate(
    conn,
    exercise_id: str,
    *,
    can_do: bool = True,
    will_do: bool = True,
    feels_bad: bool = False,
    rated_on: str = "2026-10-30",
) -> None:
    repositories.append_exercise_suitability(
        conn,
        exercise_id=exercise_id,
        rated_on=rated_on,
        can_do=can_do,
        will_do=will_do,
        feels_bad=feels_bad,
    )


def _history(conn, session_type: str, exercise_id: str, order_index: int = 1) -> None:
    plan = {"items": [{"order_index": order_index, "exercise_id": exercise_id}]}
    conn.execute(
        """
        INSERT INTO workout_session
            (workout_id, for_date, session_type, status, plan_json, readiness_json,
             started_at, ended_at)
        VALUES (?, ?, ?, 'completed', ?, '{}', ?, ?)
        """,
        (
            f"w-{session_type}-{exercise_id}",
            "2026-10-30",
            session_type,
            json.dumps(plan),
            "2026-10-30T10:00:00Z",
            "2026-10-30T11:00:00Z",
        ),
    )


def test_generates_the_blueprint_defaults_when_nothing_is_rated() -> None:
    store = db.Store(":memory:")
    try:
        session = generator.generate(
            store.connection, for_date="2026-11-01", session_type="squat"
        )
        template = templates.SessionTemplate.load("squat")
        assert session.exercise_ids == tuple(
            slot.exercises[0] for slot in template.slots
        )
        assert session.template.primary_exercise == "ssb_squat"
        assert "ssb_squat" in session.pending_ratings
        assert session.policy_digest
        assert session.warnings
    finally:
        store.close()


@pytest.mark.parametrize("session_type", templates.SESSION_TYPES)
def test_every_session_type_generates(session_type: str) -> None:
    store = db.Store(":memory:")
    try:
        session = generator.generate(
            store.connection, for_date="2026-11-01", session_type=session_type
        )
        assert session.session_type == session_type
        assert session.template.primary_exercise == templates.SessionTemplate.load(
            session_type
        ).primary_exercise
        assert len(session.slots) == len(session.template.slots)
    finally:
        store.close()


def test_can_do_replaces_a_vetoed_default() -> None:
    store = db.Store(":memory:")
    try:
        _rate(store.connection, "ssb_squat", can_do=False)
        _rate(store.connection, "competition_squat")
        session = generator.generate(
            store.connection, for_date="2026-11-01", session_type="squat"
        )
        assert session.template.primary_exercise == "competition_squat"
        main = next(slot for slot in session.slots if slot.slot_id == "squat_main")
        assert main.exercise_id == "competition_squat"
    finally:
        store.close()


def test_no_eligible_main_is_a_field_error() -> None:
    store = db.Store(":memory:")
    try:
        _rate(store.connection, "ssb_squat", can_do=False)
        with pytest.raises(generator.GenerationError, match="no eligible candidate"):
            generator.generate(
                store.connection, for_date="2026-11-01", session_type="squat"
            )
    finally:
        store.close()


def test_rotation_zero_keeps_the_last_choice_and_one_rotates() -> None:
    store = db.Store(":memory:")
    try:
        _rate(store.connection, "ssb_squat")
        _rate(store.connection, "competition_squat")
        _history(store.connection, "squat", "ssb_squat")
        zero = _settings(**{"resolver.rotation.main": 0.0})
        one = _settings(**{"resolver.rotation.main": 1.0})
        kept = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="squat",
            settings=zero,
        )
        rotated = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="squat",
            settings=one,
        )
        assert kept.template.primary_exercise == "ssb_squat"
        assert rotated.template.primary_exercise == "competition_squat"
    finally:
        store.close()


def test_hinge_main_pool_includes_sumo() -> None:
    store = db.Store(":memory:")
    try:
        _rate(store.connection, "trap_bar_deadlift")
        _rate(store.connection, "sumo_deadlift")
        _history(store.connection, "hinge", "trap_bar_deadlift")
        settings = _settings(**{"resolver.rotation.main": 1.0})
        session = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="hinge",
            settings=settings,
        )
        assert session.template.primary_exercise == "sumo_deadlift"
    finally:
        store.close()


def test_pattern_flexibility_can_change_a_core_slot() -> None:
    raw = yaml.safe_load(
        paths.template_resolver_yaml().read_text(encoding="utf-8")
    )
    raw["slot_pools"] = {"squat": {"core_anti_extension": ["ab_wheel", "pallof_press"]}}
    policy = resolver_policy.ResolverPolicy.from_text(
        yaml.safe_dump(raw, sort_keys=False)
    )
    store = db.Store(":memory:")
    try:
        _rate(store.connection, "pallof_press")
        session = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="squat",
            policy=policy,
        )
        core = next(
            slot for slot in session.slots if slot.slot_id == "core_anti_extension"
        )
        assert core.exercise_id == "pallof_press"
        assert core.pattern == "core_stability"
    finally:
        store.close()


def test_availability_is_pool_aware() -> None:
    store = db.Store(":memory:")
    try:
        repositories.append_athlete_constraint(
            store.connection,
            kind="injury",
            region="knee",
            severity="hard_exclude",
            forbidden_patterns=("squat",),
        )
        availability = generator.available_session_types(
            store.connection, "2026-11-01"
        )
        assert availability["squat"] is False
        assert availability["hinge"] is True
        assert availability["bench_squat"] is True
        assert availability["bench_hinge"] is True
    finally:
        store.close()
