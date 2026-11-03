"""Step 4C: resolver dispatch into the real prescription path."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace

import pytest
from conftest import make_readiness, make_training

from strength_coach import settings_profile
from strength_coach.prescribe import (
    build_prescription,
    generator,
    resolver,
    resolver_policy,
    templates,
)
from strength_coach.prescribe import (
    persistence as prescription_persistence,
)
from strength_coach.prescribe.evaluator import EvaluationInputs
from strength_coach.store import db, importer, repositories
from strength_coach.web import server

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
]

DROP_ROWS = [
    {"Date": "2026-10-26", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "5"}
    for _ in range(10)
]


@contextmanager
def store():
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    instance = db.Store(":memory:")
    try:
        importer.import_export(
            instance.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield instance
    finally:
        instance.close()


@contextmanager
def drop_store():
    training = make_training(DROP_ROWS)
    readiness = make_readiness([{}])
    instance = db.Store(":memory:")
    try:
        importer.import_export(
            instance.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield instance
    finally:
        instance.close()


def _pools(session_type: str = "squat"):
    base = templates.SessionTemplate.load(session_type)
    main_id = "squat_main" if session_type == "squat" else "hinge_main"
    slots = tuple(slot for slot in base.slots if slot.id in {"power", main_id})
    main_exercise = "ssb_squat" if session_type == "squat" else "trap_bar_deadlift"
    return generator.CandidatePools(
        template=replace(base, slots=slots),
        pools={
            "power": ("box_jump",),
            main_id: (main_exercise,),
        },
        main_slot=next(slot for slot in slots if slot.id == main_id),
        policy_digest="p" * 64,
        catalogue_digest="c" * 64,
    )


def _without_required_patterns(monkeypatch):
    policy = resolver_policy.ResolverPolicy.load()
    empty = replace(
        policy,
        required_patterns=MappingProxyType(
            {session: () for session in templates.SESSION_TYPES}
        ),
    )
    monkeypatch.setattr(
        resolver_policy.ResolverPolicy,
        "load",
        classmethod(lambda cls, path=None: empty),
    )
    return empty


def test_enabled_resolver_dispatches_and_attaches_provenance(monkeypatch) -> None:
    _without_required_patterns(monkeypatch)
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        monkeypatch.setattr(
            resolver.generator, "candidate_pools", lambda *args, **kwargs: _pools()
        )
        prescription = build_prescription(
            instance.connection, for_date="2024-01-15", session_type="squat"
        )
    assert [item.exercise_id for item in prescription.items] == [
        "box_jump", "ssb_squat"
    ]
    metadata = prescription.notes["resolver"]
    assert metadata["assignment"]["squat_main"] == "ssb_squat"
    assert metadata["template_digest"]
    assert metadata["policy_digest"] == "p" * 64
    assert metadata["catalogue_digest"] == "c" * 64
    assert metadata["input_hash"]
    assert metadata["generated_session"]["assignment"]["squat_main"] == "ssb_squat"
    assert metadata["beam"]["best"]["feasible"] is True
    payload = server.prescription_dict(prescription)
    assert payload["generated_session"] == metadata["generated_session"]
    assert payload["policy_digest"] == "p" * 64
    assert payload["input_hash"] == metadata["input_hash"]
    with store() as instance:
        prescription_id = prescription_persistence.store_plan(instance.connection, payload)
        row = instance.connection.execute(
            "SELECT template_digest, policy_digest, input_hash, generated_session_json "
            "FROM prescription WHERE prescription_id = ?",
            (prescription_id,),
        ).fetchone()
    assert row["template_digest"] == metadata["template_digest"]
    assert row["policy_digest"] == metadata["policy_digest"]
    assert row["input_hash"] == metadata["input_hash"]
    assert row["generated_session_json"]


def test_enabled_resolver_rejects_selection_override(monkeypatch) -> None:
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        monkeypatch.setattr(
            resolver.generator, "candidate_pools", lambda *args, **kwargs: _pools()
        )
        try:
            build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                apply_selection=True,
            )
        except ValueError as exc:
            assert "cannot apply selection" in str(exc)
        else:
            raise AssertionError("resolver must reject selection override")


def test_explicit_resolver_mode_cannot_silently_fall_back() -> None:
    with store() as instance, pytest.raises(ValueError, match="resolver.enabled is false"):
        build_prescription(
            instance.connection,
            for_date="2024-01-15",
            session_type="squat",
            use_resolver=True,
        )


def test_explicit_resolver_mode_rejects_a_template() -> None:
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        base = templates.SessionTemplate.load("squat")
        with pytest.raises(ValueError, match="cannot accept an explicit template"):
            build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                template=base,
                use_resolver=True,
            )
        with pytest.raises(ValueError, match="explicit template"):
            build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                template=base,
            )


def test_false_mode_stays_on_fixed_path_even_when_enabled() -> None:
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        prescription = build_prescription(
            instance.connection,
            for_date="2024-01-15",
            session_type="squat",
            use_resolver=False,
        )
    assert "resolver" not in prescription.notes


def test_flag_off_public_serialization_is_identical() -> None:
    cases = (
        {},
        {"technique_throttle": True},
        {"top_set_requested": True},
        {"minimum_session": True, "minimum_target_minutes": 30},
    )
    with store() as instance:
        for inputs in cases:
            default = build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                **inputs,
            )
            explicit = build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                use_resolver=False,
                **inputs,
            )
            assert server.prescription_dict(default) == server.prescription_dict(explicit)
            assert default.as_rows() == explicit.as_rows()


def test_assignment_search_failure_has_a_stage(monkeypatch) -> None:
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        monkeypatch.setattr(
            resolver.generator, "candidate_pools", lambda *args, **kwargs: _pools()
        )
        monkeypatch.setattr(
            resolver.beam_mod,
            "search",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("beam boom")),
        )
        with pytest.raises(resolver.ResolverBuildError) as caught:
            build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                use_resolver=True,
            )
    assert caught.value.stage == "assignment_search"
    assert caught.value.beam_result is None
    assert "beam boom" in str(caught.value)


def test_invalid_resolver_failure_stage_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown resolver failure stage"):
        resolver.ResolverBuildError("not-a-stage", "boom")


def test_actual_volume_drop_is_not_a_successful_assignment(monkeypatch) -> None:
    with drop_store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={
                "resolver.enabled": True,
                "resolver.eligibility.auto_requires_can_do": False,
            },
            resolver_enable_confirmed=True,
            effective_from="2026-10-01",
        )
        repositories.append_athlete_profile(
            instance.connection,
            effective_from="2026-10-29",
            competition_date="2026-11-01",
            sessions_per_week_target=1,
            max_session_minutes=80,
            volume_budget_enabled=True,
            main_lift_policy="drop",
        )
        monkeypatch.setattr(
            resolver.generator,
            "candidate_pools",
            lambda *args, **kwargs: _pools("hinge"),
        )
        with pytest.raises(resolver.ResolverBuildError) as caught:
            build_prescription(
                instance.connection,
                for_date="2026-10-29",
                session_type="hinge",
                drop_confirmed=True,
                use_resolver=True,
            )
    assert caught.value.stage == "assignment_search"
    assert caught.value.beam_result is not None
    assert caught.value.beam_result.diagnostic is not None
    assert caught.value.beam_result.diagnostic.session_replaced is True


def test_final_structural_integrity_is_rechecked(monkeypatch) -> None:
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        monkeypatch.setattr(
            resolver.generator, "candidate_pools", lambda *args, **kwargs: _pools()
        )
        invalid = SimpleNamespace(
            assignment=(("power", "box_jump"), ("squat_main", "ssb_squat")),
            assignment_preserved=True,
            session_replaced=False,
        )
        monkeypatch.setattr(
            resolver.beam_mod,
            "search",
            lambda *args, **kwargs: SimpleNamespace(best=invalid, reason="fake"),
        )
        with pytest.raises(resolver.ResolverBuildError) as caught:
            build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                use_resolver=True,
            )
    assert caught.value.stage == "final_integrity"
    assert "required patterns" in str(caught.value)


def test_evaluation_exception_has_the_evaluation_stage(monkeypatch) -> None:
    _without_required_patterns(monkeypatch)
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        monkeypatch.setattr(
            resolver.generator, "candidate_pools", lambda *args, **kwargs: _pools()
        )
        monkeypatch.setattr(
            resolver,
            "evaluate_assignment",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("eval boom")),
        )
        with pytest.raises(resolver.ResolverBuildError) as caught:
            build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                use_resolver=True,
            )
    assert caught.value.stage == "prescription_evaluation"
    assert type(caught.value.cause).__name__ == "RuntimeError"
    assert "eval boom" in str(caught.value)


def test_flag_off_volume_drop_serialization_is_identical() -> None:
    with store() as instance:
        repositories.append_athlete_profile(
            instance.connection,
            effective_from="2024-01-01",
            volume_budget_enabled=True,
        )
        default = build_prescription(
            instance.connection,
            for_date="2024-01-15",
            session_type="squat",
            drop_confirmed=True,
        )
        explicit = build_prescription(
            instance.connection,
            for_date="2024-01-15",
            session_type="squat",
            drop_confirmed=True,
            use_resolver=False,
        )
        assert server.prescription_dict(default) == server.prescription_dict(explicit)
        assert default.as_rows() == explicit.as_rows()


def test_prescription_fingerprint_canonical_and_material() -> None:
    base = resolver.prescription_input_fingerprint(
        for_date="2024-01-15",
        session_type="squat",
        assignment=(("power", "box_jump"), ("squat_main", "ssb_squat")),
        template_digest="t" * 64,
        policy_digest="p" * 64,
        catalogue_digest="c" * 64,
        inputs=EvaluationInputs(minimum_target_minutes=30, top_set_requested=True),
        resolved={"b": 2, "a": 1, "nested": {"y": 2, "x": 1}},
        resolver_settings={"rotation": 0.2, "enabled": True},
        candidate_pools={"squat_main": ("ssb_squat",), "power": ("box_jump",)},
    )
    equivalent = resolver.prescription_input_fingerprint(
        for_date="2024-01-15",
        session_type="squat",
        assignment=(("power", "box_jump"), ("squat_main", "ssb_squat")),
        template_digest="t" * 64,
        policy_digest="p" * 64,
        catalogue_digest="c" * 64,
        inputs=EvaluationInputs(minimum_target_minutes=30, top_set_requested=True),
        resolved={"a": 1, "nested": {"x": 1, "y": 2}, "b": 2},
        resolver_settings={"enabled": True, "rotation": 0.2},
        candidate_pools={"power": ("box_jump",), "squat_main": ("ssb_squat",)},
    )
    assert base == equivalent

    variants = (
        {"assignment": (("power", "box_jump"), ("squat_main", "competition_squat"))},
        {"assignment": (("squat_main", "ssb_squat"), ("power", "box_jump"))},
        {"policy_digest": "q" * 64},
        {"catalogue_digest": "d" * 64},
        {"inputs": EvaluationInputs(minimum_target_minutes=31, top_set_requested=True)},
        {"inputs": EvaluationInputs(minimum_target_minutes=30, top_set_requested=False)},
        {"resolved": {"b": 2, "a": 1, "nested": {"y": 2, "x": 3}}},
        {"resolver_settings": {"rotation": 0.3, "enabled": True}},
        {"candidate_pools": {"squat_main": ("ssb_squat", "competition_squat")}},
        {"beam_config": resolver.beam_mod.BeamConfig(width=5)},
        {"beam_config": resolver.beam_mod.BeamConfig(max_candidates_per_slot=7)},
        {"beam_config": resolver.beam_mod.BeamConfig(max_full_evaluations=3)},
    )
    for change in variants:
        altered = {**{
            "for_date": "2024-01-15",
            "session_type": "squat",
            "assignment": (("power", "box_jump"), ("squat_main", "ssb_squat")),
            "template_digest": "t" * 64,
            "policy_digest": "p" * 64,
            "catalogue_digest": "c" * 64,
            "inputs": EvaluationInputs(minimum_target_minutes=30, top_set_requested=True),
            "resolved": {"a": 1, "nested": {"x": 1, "y": 2}, "b": 2},
            "resolver_settings": {"enabled": True, "rotation": 0.2},
            "candidate_pools": {"power": ("box_jump",), "squat_main": ("ssb_squat",)},
        }, **change}
        assert resolver.prescription_input_fingerprint(**altered) != base

    with pytest.raises(TypeError, match="unsupported fingerprint input"):
        resolver.prescription_input_fingerprint(
            for_date="2024-01-15",
            session_type="squat",
            assignment=(("power", "box_jump"),),
            template_digest="t" * 64,
            policy_digest="p" * 64,
            catalogue_digest="c" * 64,
            inputs=EvaluationInputs(selection_chooser=object()),
            resolved={},
            resolver_settings={},
            candidate_pools={},
        )


def test_fingerprint_nonfinite_and_dataframe_schema_are_distinct() -> None:
    import pandas as pd

    assert resolver._canonical(float("nan")) != resolver._canonical("__nan__")
    assert resolver._canonical(float("inf")) != resolver._canonical("__inf__")
    assert resolver._canonical(float("-inf")) != resolver._canonical("__-inf__")
    assert resolver._canonical(-0.0) != resolver._canonical(0.0)
    assert resolver._canonical(-0.0) != resolver._canonical("__-0.0")

    int64 = pd.DataFrame({"value": [1, 2]}, dtype="int64")
    nullable = pd.DataFrame({"value": [1, 2]}, dtype="Int64")
    category = pd.DataFrame({"value": pd.Categorical(["a", "b"])})
    assert resolver._canonical(int64) != resolver._canonical(nullable)
    assert resolver._canonical(category) != resolver._canonical(
        pd.DataFrame({"value": ["a", "b"]})
    )


def test_resolver_failure_has_a_structured_stage(monkeypatch) -> None:
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        monkeypatch.setattr(
            resolver.generator,
            "candidate_pools",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pool boom")),
        )
        with pytest.raises(resolver.ResolverBuildError) as caught:
            build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                use_resolver=True,
            )
    assert caught.value.stage == "pool_generation"
    assert type(caught.value.cause).__name__ == "RuntimeError"
    assert caught.value.as_dict()["cause"]["message"] == "pool boom"
