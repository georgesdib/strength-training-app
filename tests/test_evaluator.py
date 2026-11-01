"""Step 4A: read-only assignment evaluation through the real pipeline."""

from __future__ import annotations

from contextlib import contextmanager

from conftest import make_readiness, make_training

from strength_coach.prescribe import build_prescription, evaluator, templates
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


def defaults(template):
    return {slot.id: slot.exercises[0] for slot in template.slots}


def test_evaluation_matches_the_fixed_build_for_the_same_assignment() -> None:
    with store() as instance:
        base = templates.SessionTemplate.load("squat")
        assignment = defaults(base)
        evaluated = evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=assignment,
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
        evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=defaults(base),
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
        good = evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=defaults(base),
        )
        changed = defaults(base)
        changed["squat_main"] = "competition_squat"
        bad = evaluator.evaluate_assignment(
            instance.connection,
            for_date="2024-01-15",
            base_template=base,
            assignment=changed,
        )
    assert bad.components.unknown_loads >= 1
    assert bad.components.executable is False
    assert bad.score > good.score
    assert any("unknown load" in reason for reason in bad.reasons)


def test_assignment_template_is_deterministic_and_rejects_unknown_slots() -> None:
    base = templates.SessionTemplate.load("squat")
    one = evaluator.assignment_template(base, defaults(base))
    two = evaluator.assignment_template(base, defaults(base))
    assert one == two
    try:
        evaluator.assignment_template(base, {"not_a_slot": "ssb_squat"})
    except ValueError as exc:
        assert "unknown slot" in str(exc)
    else:
        raise AssertionError("unknown slot should fail")
