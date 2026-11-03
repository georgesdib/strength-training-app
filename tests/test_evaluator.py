"""Step 4A: read-only evaluation of complete validated assignments."""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from conftest import make_readiness, make_training

from strength_coach.features.deload import DeloadDecision
from strength_coach.prescribe import (
    build_prescription,
    evaluator,
    templates,
)
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
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


def pools(template):
    return {slot.id: [slot.exercises[0]] for slot in template.slots}


def defaults(pool_map):
    return {slot_id: values[0] for slot_id, values in pool_map.items()}


def snapshot(conn):
    tables = [
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    counts = {
        table: int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
        for table in tables
    }
    return int(conn.total_changes), counts


ITEM_FIELDS = (
    "order_index",
    "exercise_id",
    "sets",
    "reps_low",
    "reps_high",
    "load_kg",
    "load_basis",
    "rounding_increment_kg",
    "rir_target",
    "rest_s",
    "essential",
    "rationale_refs",
    "substitution_for",
    "time_cap_s",
    "unknown_load_reason",
    "velocity_target",
    "vbt_basis",
    "e1rm_source_sets",
    "e1rm_kg",
    "e1rm_ref",
    "e1rm_quality",
    "e1rm_age_days",
    "intensity",
    "load_factor",
    "flare",
    "effort_model",
    "quality_stop",
    "warmup",
    "set_groups",
)


def assert_prescription_equal(left, right) -> None:
    for field in (
        "for_date",
        "session_type",
        "fallback_level",
        "rule_document_version",
        "time_cap_s",
        "warnings",
        "issues",
        "calibration_ids",
        "notes",
        "executable",
    ):
        assert getattr(left, field) == getattr(right, field), field
    assert len(left.items) == len(right.items)
    for left_item, right_item in zip(left.items, right.items, strict=True):
        for field in ITEM_FIELDS:
            assert getattr(left_item, field) == getattr(right_item, field), (
                f"{left_item.order_index}/{left_item.exercise_id}.{field}"
            )


def _parity(
    instance,
    *,
    for_date: str,
    base,
    pool_map,
    inputs=None,
):
    assignment = defaults(pool_map)
    evaluated = evaluator.evaluate_assignment(
        instance.connection,
        for_date=for_date,
        base_template=base,
        assignment=assignment,
        candidate_pools=pool_map,
        inputs=inputs,
    )
    direct = build_prescription(
        instance.connection,
        for_date=for_date,
        session_type=base.session_type,
        template=evaluator.assignment_template(base, assignment, pool_map),
        **(inputs or evaluator.EvaluationInputs()).as_build_kwargs(),
    )
    assert_prescription_equal(evaluated.prescription, direct)
    return evaluated, direct


def _default_assignment(base):
    return {slot.id: slot.exercises[0] for slot in base.slots}


def test_required_patterns_are_checked_on_the_complete_assignment() -> None:
    from strength_coach.prescribe import generator, resolver_policy
    from strength_coach.utils import exercises

    base = templates.SessionTemplate.load("squat")
    policy = resolver_policy.ResolverPolicy.load()
    taxonomy = exercises.taxonomy().entities
    assignment = _default_assignment(base)
    assert not generator.required_pattern_violations(
        base, assignment, policy, taxonomy
    )

    violating = None
    for slot in base.slots:
        for candidate in ("box_jump", "bench_press", "back_extension", "dumbbell_row"):
            if candidate in slot.exercises:
                continue
            changed = {**assignment, slot.id: candidate}
            if generator.required_pattern_violations(base, changed, policy, taxonomy):
                violating = changed
                break
        if violating is not None:
            break
    assert violating is not None
    assert generator.required_pattern_violations(base, violating, policy, taxonomy)

    with store() as instance:
        result = evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=violating,
            candidate_pools={
                slot_id: [exercise_id] for slot_id, exercise_id in violating.items()
            },
        )
    assert result.structural_violations
    assert result.feasible is False
    assert "required" in (result.infeasibility_reason or "")


def test_evaluation_matches_the_fixed_build_for_the_same_assignment() -> None:
    with store() as instance:
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        assignment = defaults(pool_map)
        evaluated = evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=assignment,
            candidate_pools=pool_map,
        )
        fixed = build_prescription(
            instance.connection, for_date="2024-01-15", session_type="squat"
        )
    assert evaluated.assignment == tuple(assignment.items())
    assert [item.exercise_id for item in evaluated.prescription.items] == [
        item.exercise_id for item in fixed.items
    ]
    assert [item.load_kg for item in evaluated.prescription.items] == [
        item.load_kg for item in fixed.items
    ]
    assert evaluated.components.volume_error >= 0
    assert evaluated.score >= 0


def test_evaluation_does_not_write_any_database_state() -> None:
    with store() as instance:
        before = snapshot(instance.connection)
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=defaults(pool_map),
            candidate_pools=pool_map,
        )
        after = snapshot(instance.connection)
    assert before == after


def test_unknown_load_assignment_scores_worse_and_is_explained() -> None:
    with store() as instance:
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        pool_map["squat_main"] = ["ssb_squat", "competition_squat"]
        good = evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=defaults(pool_map),
            candidate_pools=pool_map,
        )
        changed = defaults(pool_map)
        changed["squat_main"] = "competition_squat"
        bad = evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=changed,
            candidate_pools=pool_map,
        )
    assert bad.components.unknown_loads >= 1
    assert bad.components.executable is False
    assert bad.score > good.score
    assert any("unknown load" in reason for reason in bad.reasons)


def test_assignment_template_is_deterministic_and_rejects_unknown_slots() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    assignment = defaults(pool_map)
    one = evaluator.assignment_template(base, assignment, pool_map)
    two = evaluator.assignment_template(base, assignment, pool_map)
    assert one == two
    try:
        evaluator.assignment_template(
            base, {**assignment, "not_a_slot": "ssb_squat"}, pool_map
        )
    except ValueError as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("unknown slot should fail")


def test_assignment_requires_exact_slot_coverage_and_membership() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    assignment = defaults(pool_map)

    missing = dict(assignment)
    missing.pop("squat_main")
    for bad in (
        missing,
        {**assignment, "squat_main": ""},
        {**assignment, "squat_main": "competition_squat"},
    ):
        try:
            evaluator.validate_assignment(base, bad, pool_map)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid assignment accepted: {bad!r}")

    no_pool = dict(pool_map)
    no_pool["squat_main"] = []
    try:
        evaluator.validate_assignment(base, assignment, no_pool)
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty eligible pool should fail")


def test_shared_input_contract_covers_every_build_input() -> None:
    assert set(evaluator.EvaluationInputs().as_build_kwargs()) == {
        "document",
        "thresholds",
        "undulation",
        "history",
        "vbt",
        "readiness_config",
        "apply_selection",
        "selection_chooser",
        "selection_confirmed",
        "minimum_session",
        "minimum_target_minutes",
        "minimum_include_main",
        "technique_throttle",
        "technique_throttle_pattern",
        "deload_decision",
        "drop_confirmed",
        "top_set_requested",
        "projected_items",
        "projected_sessions",
    }


def test_selection_inputs_are_rejected_by_resolver_evaluation() -> None:
    with store() as instance:
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        assignment = defaults(pool_map)
        for inputs in (
            evaluator.EvaluationInputs(apply_selection=True),
            evaluator.EvaluationInputs(selection_confirmed=True),
            evaluator.EvaluationInputs(selection_chooser=lambda **kwargs: None),
        ):
            with pytest.raises(ValueError, match="cannot apply selection"):
                evaluator.evaluate_assignment(
                    instance.connection,
                    for_date="2024-01-15",
                    base_template=base,
                    assignment=assignment,
                    candidate_pools=pool_map,
                    inputs=inputs,
                )


def test_candidate_pool_ids_are_strict_and_shared() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    assignment = defaults(pool_map)
    for bad in (None, "ssb_squat", [1], [None], [""], ["  "], ["ssb_squat", "ssb_squat"]):
        candidate_pools = dict(pool_map)
        candidate_pools["squat_main"] = bad
        with pytest.raises(ValueError):
            evaluator.validate_assignment(base, assignment, candidate_pools)


def test_session_replacement_is_explicit_and_infeasible(monkeypatch) -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    assignment = defaults(pool_map)

    def replaced(*args, **kwargs):
        return SimpleNamespace(
            session_type="volume_fill_squat",
            executable=False,
            issues=(),
            notes={},
            warnings=(),
            items=(),
        )

    monkeypatch.setattr(evaluator, "build_prescription", replaced)
    result = evaluator.evaluate_assignment(
        None,
        for_date="2024-01-15",
        base_template=base,
        assignment=assignment,
        candidate_pools=pool_map,
    )
    assert result.session_replaced is True
    assert result.assignment_preserved is False
    assert result.feasible is False
    assert "replaced" in (result.infeasibility_reason or "")
    assert result.as_dict()["session_replaced"] is True
    assert result.as_dict()["infeasibility_reason"]


def test_feasibility_is_hard_only_and_score_has_reasons() -> None:
    components = evaluator.EvaluationComponents(
        executable=True,
        issues=0,
        unknown_loads=0,
        volume_error=0.25,
        spinal_over_cap=False,
        spinal_headroom=1.0,
        time_over_planned=True,
        time_over_minutes=10.0,
        warnings=2,
    )
    score, reasons = evaluator.score_components(components)
    assert score > 0
    assert any("time" in reason for reason in reasons)
    assert any("volume" in reason for reason in reasons)
    assert any("warning" in reason for reason in reasons)
    result = evaluator.AssignmentEvaluation(
        assignment=(),
        score=score,
        components=components,
        prescription=SimpleNamespace(
            executable=True, issues=(), warnings=(), items=()
        ),
        reasons=reasons,
    )
    # Soft objectives do not make the assignment infeasible.
    assert result.feasible is True


def test_score_ordering_prioritises_hard_failures() -> None:
    base = evaluator.EvaluationComponents(
        executable=True,
        issues=0,
        unknown_loads=0,
        volume_error=0.0,
        spinal_over_cap=False,
        spinal_headroom=1.0,
        time_over_planned=False,
        time_over_minutes=0.0,
        warnings=0,
    )
    soft = evaluator.EvaluationComponents(
        **{
            **base.__dict__,
            "volume_error": 1.0,
            "time_over_planned": True,
            "time_over_minutes": 30.0,
            "warnings": 4,
        }
    )
    hard = evaluator.EvaluationComponents(
        **{**base.__dict__, "executable": False, "issues": 1}
    )
    assert evaluator.score_components(base)[0] < evaluator.score_components(soft)[0]
    assert evaluator.score_components(soft)[0] < evaluator.score_components(hard)[0]
    assert evaluator.score_components(hard)[1]


def test_shared_input_contract_matches_build_signature() -> None:
    signature = inspect.signature(build_prescription)
    optional = {
        name
        for name, parameter in signature.parameters.items()
        if name not in {"conn", "for_date", "session_type", "template", "use_resolver"}
    }
    assert set(evaluator.EvaluationInputs().as_build_kwargs()) == optional


def test_parity_with_readiness_and_continuity() -> None:
    with store() as instance:
        base = templates.SessionTemplate.load("squat")
        _parity(
            instance,
            for_date="2024-01-15",
            base=base,
            pool_map=pools(base),
            inputs=evaluator.EvaluationInputs(),
        )


def test_parity_with_drop_planning_input() -> None:
    with store() as instance:
        repositories.append_athlete_profile(
            instance.connection,
            effective_from="2024-01-01",
            volume_budget_enabled=True,
        )
        base = templates.SessionTemplate.load("squat")
        _parity(
            instance,
            for_date="2024-01-15",
            base=base,
            pool_map=pools(base),
            inputs=evaluator.EvaluationInputs(drop_confirmed=True),
        )


def test_shared_input_contract_matches_the_direct_build() -> None:
    with store() as instance:
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        _parity(
            instance,
            for_date="2024-01-15",
            base=base,
            pool_map=pool_map,
            inputs=evaluator.EvaluationInputs(
                technique_throttle=True,
                top_set_requested=True,
            ),
        )


def test_parity_with_minimum_session_and_deload() -> None:
    with store() as instance:
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        _parity(
            instance,
            for_date="2024-01-15",
            base=base,
            pool_map=pool_map,
            inputs=evaluator.EvaluationInputs(
                minimum_session=True,
                minimum_target_minutes=30,
                deload_decision=DeloadDecision("test deload", "scheduled"),
            ),
        )


def test_parity_with_volume_budget_and_projected_context() -> None:
    with store() as instance:
        repositories.append_athlete_profile(
            instance.connection,
            effective_from="2024-01-01",
            volume_budget_enabled=True,
        )
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        evaluated, direct = _parity(
            instance,
            for_date="2024-01-15",
            base=base,
            pool_map=pool_map,
            inputs=evaluator.EvaluationInputs(
                projected_sessions=1,
                drop_confirmed=False,
            ),
        )
    assert evaluated.assignment_preserved is True
    assert evaluated.session_replaced is False
    assert direct.notes == evaluated.prescription.notes
