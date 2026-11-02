"""Step 4A: read-only evaluation of complete validated assignments."""

from __future__ import annotations

from contextlib import contextmanager

from conftest import make_readiness, make_training

from strength_coach.prescribe import (
    build_prescription,
    evaluator,
    templates,
)
from strength_coach.store import db, importer

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


def test_evaluation_does_not_write_a_prescription_or_workout() -> None:
    with store() as instance:
        before = {
            table: instance.connection.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
            ).fetchone()["n"]
            for table in ("prescription", "workout_session", "settings_profile")
        }
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=defaults(pool_map),
            candidate_pools=pool_map,
        )
        after = {
            table: instance.connection.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
            ).fetchone()["n"]
            for table in before
        }
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


def test_shared_input_contract_matches_the_direct_build() -> None:
    with store() as instance:
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        assignment = defaults(pool_map)
        inputs = evaluator.EvaluationInputs(
            technique_throttle=True,
            top_set_requested=True,
        )
        evaluated = evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=assignment,
            candidate_pools=pool_map,
            inputs=inputs,
        )
        direct = build_prescription(
            instance.connection,
            for_date="2024-01-15",
            session_type="squat",
            template=evaluator.assignment_template(base, assignment, pool_map),
            **inputs.as_build_kwargs(),
        )
    assert [item.load_kg for item in evaluated.prescription.items] == [
        item.load_kg for item in direct.items
    ]
    assert [item.set_groups for item in evaluated.prescription.items] == [
        item.set_groups for item in direct.items
    ]
