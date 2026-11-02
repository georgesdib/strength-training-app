"""Step 4B: deterministic bounded beam over complete assignments."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
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


def pools(template):
    return {slot.id: [slot.exercises[0]] for slot in template.slots}


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


def test_beam_is_deterministic_and_never_exceeds_the_evaluation_budget() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    pool_map["squat_main"] = ["ssb_squat", "competition_squat"]
    pool_map["bench_support"] = ["bench_press", "incline_press"]
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
        candidates=pool_map, config=config, evaluator=fake,
    )
    first_calls = list(calls)
    calls.clear()
    second = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pool_map, config=config, evaluator=fake,
    )
    assert first.truncated is True
    assert first.evaluation_budget_applied is True
    assert first.final_assignments_pruned >= 1
    assert len(first.evaluated) <= 2
    assert first.best is not None and first.best.score == 0.0
    assert first_calls == calls
    assert first.best.assignment == second.best.assignment


def test_empty_candidate_pool_is_a_field_level_failure() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    pool_map["squat_main"] = []
    with pytest.raises(beam.BeamEligibilityError, match="squat_main"):
        beam.search(
            None, for_date="2024-01-15", base_template=base,
            candidates=pool_map,
        )


def test_missing_candidate_pool_is_a_field_level_failure() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    pool_map.pop("squat_main")
    with pytest.raises(beam.BeamEligibilityError, match="squat_main"):
        beam.search(
            None, for_date="2024-01-15", base_template=base,
            candidates=pool_map,
        )


def test_candidate_cap_is_reported_and_does_not_fall_back_to_blueprint() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    pool_map["squat_main"] = ["ssb_squat", "competition_squat"]

    def fake(conn, *, assignment, **kwargs):
        return SimpleNamespace(
            assignment=tuple(assignment.items()),
            score=0.0,
            feasible=True,
            prescription=None,
        )

    result = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pool_map, config=beam.BeamConfig(max_candidates_per_slot=1),
        evaluator=fake,
    )
    assert result.candidate_cap_applied is True
    assert result.truncated is True
    assert dict(result.best.assignment)["squat_main"] == "ssb_squat"


def test_no_feasible_result_is_reported_separately_from_a_diagnostic() -> None:
    base = templates.SessionTemplate.load("squat")

    def fake(conn, *, assignment, **kwargs):
        return SimpleNamespace(
            assignment=tuple(assignment.items()),
            score=1.0,
            feasible=False,
            prescription=None,
        )

    result = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pools(base), evaluator=fake,
    )
    assert result.best is None
    assert result.diagnostic is not None
    assert result.exhaustive is True
    assert "exhaustive" in result.reason


def test_beam_uses_the_real_evaluator_and_does_not_write() -> None:
    with store() as instance:
        before = snapshot(instance.connection)
        base = templates.SessionTemplate.load("squat")
        pool_map = pools(base)
        pool_map["squat_main"] = ["ssb_squat", "competition_squat"]
        result = beam.search(
            instance.connection, for_date="2024-01-15",
            base_template=base, candidates=pool_map,
        )
        after = snapshot(instance.connection)
    assert result.best is None
    assert result.diagnostic is not None
    assert result.diagnostic.prescription is not None
    assert dict(result.diagnostic.assignment)["squat_main"] == "ssb_squat"
    assert result.as_dict()["diagnostic"]["assignment"]["squat_main"] == "ssb_squat"
    assert before == after


def test_beam_finds_a_feasible_lower_ranked_alternative() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    pool_map["squat_main"] = ["ssb_squat", "competition_squat"]

    def fake(conn, *, assignment, **kwargs):
        feasible = assignment.get("squat_main") == "competition_squat"
        return SimpleNamespace(
            assignment=tuple(assignment.items()),
            score=0.0,
            feasible=feasible,
            prescription=None,
        )

    result = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pool_map, evaluator=fake,
    )
    assert result.best is not None
    assert dict(result.best.assignment)["squat_main"] == "competition_squat"
    assert result.diagnostic is not None


def test_beam_does_not_claim_exhaustion_when_it_pruned_alternatives() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    pool_map["squat_main"] = ["ssb_squat", "competition_squat"]

    def fake(conn, *, assignment, **kwargs):
        return SimpleNamespace(
            assignment=tuple(assignment.items()), score=1.0,
            feasible=False, prescription=None,
        )

    result = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pool_map, config=beam.BeamConfig(width=1), evaluator=fake,
    )
    assert result.best is None
    assert result.exhaustive is False
    assert result.pruned > 0
    assert "not exhaustive" in result.reason


def test_beam_tie_break_prefers_candidate_rank_not_lexical_id() -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    pool_map["squat_main"] = ["zzz_rank_first", "aaa_rank_second"]

    def fake(conn, *, assignment, **kwargs):
        return SimpleNamespace(
            assignment=tuple(assignment.items()), score=0.0,
            feasible=True, prescription=None,
        )

    result = beam.search(
        None, for_date="2024-01-15", base_template=base,
        candidates=pool_map, evaluator=fake,
    )
    assert dict(result.best.assignment)["squat_main"] == "zzz_rank_first"


@pytest.mark.parametrize(
    "bad",
    [None, "ssb_squat", [1], [None], [""], ["  "], ["ssb_squat", "ssb_squat"]],
)
def test_beam_rejects_malformed_candidate_ids(bad) -> None:
    base = templates.SessionTemplate.load("squat")
    pool_map = pools(base)
    pool_map["squat_main"] = bad
    with pytest.raises(beam.BeamEligibilityError, match="squat_main"):
        beam.search(
            None, for_date="2024-01-15", base_template=base,
            candidates=pool_map,
        )


def test_beam_default_budget_is_reachable() -> None:
    assert beam.DEFAULT_FULL_EVALUATION_BUDGET == beam.DEFAULT_BEAM_WIDTH


def test_beam_config_rejects_impossible_limits() -> None:
    for kwargs in (
        {"width": 0},
        {"max_candidates_per_slot": 0},
        {"max_full_evaluations": 0},
    ):
        try:
            beam.BeamConfig(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"BeamConfig should reject {kwargs}")
