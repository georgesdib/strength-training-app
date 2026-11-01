"""Step 4B: deterministic bounded beam over complete assignments."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from conftest import make_readiness, make_training

from strength_coach.prescribe import beam, templates
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
    return {slot.id: [slot.exercises[0]] for slot in template.slots}


def test_beam_is_deterministic_and_never_exceeds_the_evaluation_budget() -> None:
    base = templates.SessionTemplate.load("squat")
    pools = defaults(base)
    pools["squat_main"] = ["ssb_squat", "competition_squat"]
    pools["bench_support"] = ["bench_press", "incline_press"]
    calls: list[dict[str, str]] = []

    def fake(conn, *, assignment, **kwargs):
        calls.append(dict(assignment))
        bad = assignment.get("squat_main") == "competition_squat"
        return SimpleNamespace(
            assignment=tuple(assignment.items()),
            score=10.0 if bad else 0.0,
            feasible=True,
            prescription=None,
        )

    config = beam.BeamConfig(width=4, max_full_evaluations=2)
    first = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pools, config=config, evaluator=fake,
    )
    first_calls = list(calls)
    calls.clear()
    second = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pools, config=config, evaluator=fake,
    )
    assert first.truncated is True
    assert len(first.evaluated) <= 2
    assert first.best.score == 0.0
    assert first_calls == calls
    assert first.best.assignment == second.best.assignment


def test_beam_falls_back_to_the_blueprint_default_for_an_empty_pool() -> None:
    base = templates.SessionTemplate.load("squat")
    pools = defaults(base)
    pools["squat_main"] = []
    seen: list[dict[str, str]] = []

    def fake(conn, *, assignment, **kwargs):
        seen.append(dict(assignment))
        return SimpleNamespace(
            assignment=tuple(assignment.items()),
            score=0.0,
            feasible=True,
            prescription=None,
        )

    result = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pools, evaluator=fake,
    )
    assert result.best.assignment == tuple(
        (slot.id, slot.exercises[0]) for slot in base.slots
    )
    assert "fallback" in result.reason
    assert seen


def test_beam_uses_the_real_evaluator_and_does_not_write() -> None:
    with store() as instance:
        before = {
            table: instance.connection.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
            ).fetchone()["n"]
            for table in ("prescription", "workout_session", "settings_profile")
        }
        base = templates.SessionTemplate.load("squat")
        pools = defaults(base)
        pools["squat_main"] = ["ssb_squat", "competition_squat"]
        result = beam.search(
            instance.connection, for_date="2024-01-15",
            base_template=base, candidates=pools,
        )
        after = {
            table: instance.connection.execute(
                f"SELECT COUNT(*) AS n FROM {table}"
            ).fetchone()["n"]
            for table in before
        }
    assert result.best is not None
    assert result.best.prescription is not None
    assert result.best.assignment[1] == ("squat_main", "ssb_squat")
    assert before == after


def test_beam_config_rejects_impossible_limits() -> None:
    for kwargs in ({"width": 0}, {"max_candidates_per_slot": 0}, {"max_full_evaluations": 0}):
        try:
            beam.BeamConfig(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"BeamConfig should reject {kwargs}")
