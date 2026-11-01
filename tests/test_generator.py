"""Step 2 generator core: deterministic selection, eligibility and availability."""

from __future__ import annotations

import json

import pandas as pd
import pytest
import yaml

from strength_coach import settings_registry
from strength_coach.prescribe import generator, resolver_policy, templates
from strength_coach.prescribe.resolver_settings import ResolverSettings
from strength_coach.rules import RuleContext, loader
from strength_coach.store import db, repositories
from strength_coach.utils import exercises, paths


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


def _rate_defaults(conn, session_type: str, *, skip: tuple[str, ...] = ()) -> None:
    template = templates.SessionTemplate.load(session_type)
    seen: set[str] = set()
    for slot in template.slots:
        exercise_id = slot.exercises[0]
        if exercise_id in skip or exercise_id in seen:
            continue
        _rate(conn, exercise_id)
        seen.add(exercise_id)


def _history(
    conn,
    session_type: str,
    exercise_id: str,
    order_index: int = 1,
    *,
    for_date: str = "2026-10-30",
) -> None:
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
            for_date,
            session_type,
            json.dumps(plan),
            f"{for_date}T10:00:00Z",
            f"{for_date}T11:00:00Z",
        ),
    )


def _prescription(
    conn,
    prescription_id: str,
    exercise_id: str,
    *,
    for_date: str,
    order_index: int = 1,
) -> None:
    run = repositories.start_run(conn, input_hash=prescription_id, code_version="test")
    repositories.append_prescription(
        conn,
        prescription_id=prescription_id,
        run_id=run.run_id,
        for_date=for_date,
        session_type="squat",
        fallback_level="full",
        rule_document_version="test",
        calibration_ids=(),
        approved_by="deterministic",
        items=[
            {
                "order_index": order_index,
                "exercise_id": exercise_id,
                "sets": 3,
                "reps_low": 5,
                "reps_high": 5,
                "load_kg": 100.0,
                "load_basis": "absolute",
                "rounding_increment": 2.5,
                "rir_target": 2,
                "essential": True,
            }
        ],
    )


def test_require_can_do_false_allows_unrated_selection() -> None:
    store = db.Store(":memory:")
    try:
        session = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="squat",
            settings=_settings(
                **{"resolver.eligibility.auto_requires_can_do": False}
            ),
        )
        assert session.exercise_ids
        assert session.pending_ratings
    finally:
        store.close()


def test_generates_the_blueprint_defaults_when_defaults_are_rated() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat")
        session = generator.generate(
            store.connection, for_date="2026-11-01", session_type="squat"
        )
        template = templates.SessionTemplate.load("squat")
        assert session.exercise_ids == tuple(
            slot.exercises[0] for slot in template.slots
        )
        assert session.template.primary_exercise == "ssb_squat"
        assert session.pending_ratings == ()
        assert len(session.policy_digest) == 64
        assert len(session.catalogue_digest) == 64
    finally:
        store.close()


@pytest.mark.parametrize("session_type", templates.SESSION_TYPES)
def test_every_session_type_generates(session_type: str) -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, session_type)
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


def test_unrated_power_slot_fails_when_can_do_is_required() -> None:
    store = db.Store(":memory:")
    try:
        with pytest.raises(generator.GenerationError, match="fixed power exercise"):
            generator.generate(
                store.connection, for_date="2026-11-01", session_type="squat"
            )
    finally:
        store.close()


def test_power_slot_is_safety_checked() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat")
        repositories.append_athlete_constraint(
            store.connection,
            kind="injury",
            region="knee",
            severity="hard_exclude",
            forbidden_exercises=("box_jump",),
        )
        with pytest.raises(generator.GenerationError, match="fixed power exercise"):
            generator.generate(
                store.connection, for_date="2026-11-01", session_type="squat"
            )
    finally:
        store.close()


def test_can_do_replaces_a_vetoed_default() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat")
        _rate(store.connection, "ssb_squat", can_do=False, rated_on="2026-10-31")
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
        _rate_defaults(store.connection, "squat")
        _rate(store.connection, "ssb_squat", can_do=False, rated_on="2026-10-31")
        with pytest.raises(
            generator.GenerationError, match="no automatically eligible candidate"
        ):
            generator.generate(
                store.connection, for_date="2026-11-01", session_type="squat"
            )
    finally:
        store.close()


def test_rotation_zero_keeps_the_last_choice_and_one_rotates() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat")
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


def test_rotation_one_warns_when_no_alternative_exists() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat")
        _rate(store.connection, "competition_squat", can_do=False)
        _history(store.connection, "squat", "ssb_squat")
        session = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="squat",
            settings=_settings(**{"resolver.rotation.main": 1.0}),
        )
        assert session.template.primary_exercise == "ssb_squat"
        assert any("could not change exercise" in warning for warning in session.warnings)
    finally:
        store.close()


def test_hinge_main_pool_includes_sumo() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "hinge")
        _rate(store.connection, "sumo_deadlift")
        _history(store.connection, "hinge", "trap_bar_deadlift")
        session = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="hinge",
            settings=_settings(**{"resolver.rotation.main": 1.0}),
        )
        assert session.template.primary_exercise == "sumo_deadlift"
    finally:
        store.close()


def test_pattern_flexibility_can_change_a_core_slot() -> None:
    raw = yaml.safe_load(paths.template_resolver_yaml().read_text(encoding="utf-8"))
    raw["slot_pools"] = {
        "squat": {"core_anti_extension": ["ab_wheel", "pallof_press"]}
    }
    policy = resolver_policy.ResolverPolicy.from_text(
        yaml.safe_dump(raw, sort_keys=False)
    )
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat", skip=("ab_wheel",))
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


def test_required_pattern_repair_uses_a_fallback_candidate() -> None:
    raw = yaml.safe_load(paths.template_resolver_yaml().read_text(encoding="utf-8"))
    raw["slot_pools"] = {
        "hinge": {
            "hinge_main": ["trap_bar_deadlift", "sumo_deadlift"],
            "accessory_pull_up": ["dumbbell_row"],
            "accessory_row": ["dumbbell_row", "pull_up"],
        }
    }
    policy = resolver_policy.ResolverPolicy.from_text(
        yaml.safe_dump(raw, sort_keys=False)
    )
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "hinge")
        _history(store.connection, "hinge", "dumbbell_row", order_index=4)
        session = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="hinge",
            policy=policy,
        )
        by_slot = {slot.slot_id: slot.exercise_id for slot in session.slots}
        assert by_slot["accessory_row"] == "pull_up"
        assert by_slot["accessory_pull_up"] == "dumbbell_row"
    finally:
        store.close()


def test_will_do_and_feels_bad_are_suggestion_only() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat")
        _rate(store.connection, "front_squat", will_do=False)
        session = generator.generate(
            store.connection, for_date="2026-11-01", session_type="squat"
        )
        assert session.template.primary_exercise == "ssb_squat"
        assert "front_squat" in session.suggestions
    finally:
        store.close()


def test_unrated_confirm_surfaces_suggestions_but_does_not_select_them() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat")
        session = generator.generate(
            store.connection, for_date="2026-11-01", session_type="squat"
        )
        assert "front_squat" in session.suggestions
        assert "front_squat" not in session.exercise_ids
    finally:
        store.close()


def test_unrated_exclude_hides_candidates() -> None:
    store = db.Store(":memory:")
    try:
        _rate_defaults(store.connection, "squat")
        session = generator.generate(
            store.connection,
            for_date="2026-11-01",
            session_type="squat",
            settings=_settings(**{"resolver.eligibility.unrated_mode": "exclude"}),
        )
        assert "front_squat" not in session.suggestions
    finally:
        store.close()


def test_availability_checks_main_and_secondary() -> None:
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
        assert availability["bench_squat"] is False
        assert availability["hinge"] is True
        assert availability["bench_hinge"] is True
    finally:
        store.close()


def test_history_merges_workout_and_prescription_by_date() -> None:
    store = db.Store(":memory:")
    try:
        _history(store.connection, "squat", "ssb_squat")
        _prescription(
            store.connection,
            "p-same-date",
            "front_squat",
            for_date="2026-10-30",
        )
        _prescription(
            store.connection,
            "p-older",
            "competition_squat",
            for_date="2026-10-29",
        )
        history = generator._choice_history(
            store.connection, "squat", "2026-11-01"
        )
        assert history[0][1] == "ssb_squat"
        assert history[1][1] == "competition_squat"
        assert all(entry.get(1) != "front_squat" for entry in history)
        assert generator._last_choice(history, 1) == ("ssb_squat", 1)
        assert generator._last_choice([{0: "x"}, {1: "y"}], 1) == ("y", 1)
        assert generator._last_choice([{0: "x"}], 1) == (None, 0)
    finally:
        store.close()


def test_catalogue_digest_tracks_validated_content() -> None:
    first = {"squat": {"main": ("ssb_squat", "competition_squat")}}
    second = {"squat": {"main": ("ssb_squat", "competition_squat")}}
    changed = {"squat": {"main": ("ssb_squat",)}}
    assert resolver_policy.candidate_catalogue_digest(first) == (
        resolver_policy.candidate_catalogue_digest(second)
    )
    assert resolver_policy.candidate_catalogue_digest(first) != (
        resolver_policy.candidate_catalogue_digest(changed)
    )


def test_rotation_default_is_used_for_secondary_slots() -> None:
    settings = _settings(**{"resolver.rotation.default": 0.0})
    assert settings.rotation_for(role="main") == 0.2
    assert settings.rotation_for(role="secondary") == 0.0
    assert settings.rotation_for(role="accessory") == 0.5


def test_pattern_level_injury_exclusions_match_candidates() -> None:
    taxonomy = exercises.taxonomy().entities
    assert generator._injury_excludes(
        "box_jump", {"pattern:power_jump"}, taxonomy
    )
    assert not generator._injury_excludes(
        "box_jump", {"pattern:squat"}, taxonomy
    )
    auto, suggestions = generator._classify_candidates(
        ["box_jump"],
        {"power_jump"},
        set(),
        {"pattern:power_jump"},
        {},
        _settings(),
        taxonomy,
    )
    assert auto == []
    assert suggestions == []


def test_injury_score_is_candidate_specific_for_low_back() -> None:
    from types import SimpleNamespace

    region = SimpleNamespace(
        status="review",
        linked_exercises=("pattern:squat",),
        region="low_back",
    )
    injury = SimpleNamespace(region=lambda name: region if name == "low_back" else None)
    taxonomy = exercises.taxonomy().entities
    assert generator._injury_component(injury, "ssb_squat", taxonomy) < 1.0
    assert generator._injury_component(injury, "bench_press", taxonomy) == 1.0


def test_provisional_spinal_cost_respects_the_authoritative_override() -> None:
    rule = loader.load_document().rule("PRG-SPINE-001")
    entities = exercises.taxonomy().entities
    low = RuleContext(
        sets=pd.DataFrame(),
        sessions=pd.DataFrame(),
        entities=entities,
        spinal_costs={"competition_squat": 1.0},
    )
    high = RuleContext(
        sets=pd.DataFrame(),
        sessions=pd.DataFrame(),
        entities=entities,
        spinal_costs={"competition_squat": 9.0},
    )
    low_delta = generator._provisional_spinal_delta(
        rule, low, "2026-10-26", "competition_squat", 5, 0.0
    )
    high_delta = generator._provisional_spinal_delta(
        rule, high, "2026-10-26", "competition_squat", 5, 0.0
    )
    assert low_delta > 0
    assert high_delta > low_delta


def test_registry_rotation_default_is_used_for_secondary() -> None:
    assert settings_registry.snapshot().get("resolver.rotation.default") == 0.2
