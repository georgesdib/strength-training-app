"""Reactive deload: selective PRG-SPINE-001 evaluation must not change the verdict."""

from __future__ import annotations

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import deload
from strength_coach.rules import RuleContext, evaluate, load_document
from strength_coach.store import db, importer


def trap_bar(day: str, sets: int = 3) -> list[dict]:
    return [
        {"Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "150", "RIR": "2"}
        for _ in range(sets)
    ]


def two_over_cap_weeks() -> list[dict]:
    rows: list[dict] = []
    for day in ("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"):
        rows += trap_bar(day)
    for day in ("2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"):
        rows += trap_bar(day)
    return rows


@pytest.fixture
def document():
    return load_document()


@pytest.fixture
def store(tmp_path):
    rows = two_over_cap_weeks()
    training = make_training(rows)
    readiness = make_readiness([{}])
    handle = db.Store(tmp_path / "coach.db")
    try:
        importer.import_export(
            handle.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield handle
    finally:
        handle.close()


def test_reactive_reason_matches_full_policy_on_the_same_rows(monkeypatch, store):
    real_evaluate = deload.evaluate

    def full_evaluate(document, context, **kwargs):
        # Simulate the pre-change behaviour: no rule filter.
        return real_evaluate(document, context)

    monkeypatch.setattr(deload, "evaluate", full_evaluate)
    before = deload.reactive_reason(store.connection, "2024-01-12")
    assert before is not None

    monkeypatch.setattr(deload, "evaluate", real_evaluate)
    after = deload.reactive_reason(store.connection, "2024-01-12")
    assert after == before


def test_reactive_reason_requests_only_the_spine_rule(monkeypatch, store):
    real_evaluate = deload.evaluate
    calls: list[tuple] = []

    def spy(document, context, **kwargs):
        calls.append(kwargs.get("rule_ids"))
        return real_evaluate(document, context, **kwargs)

    monkeypatch.setattr(deload, "evaluate", spy)
    deload.reactive_reason(store.connection, "2024-01-12")
    assert calls == [("PRG-SPINE-001",)]


def test_selective_and_full_evaluation_return_the_same_spine_verdict(document, tmp_path):
    rows = two_over_cap_weeks()
    training = make_training(rows)
    readiness = make_readiness([{}])
    handle = db.Store(tmp_path / "ctx.db")
    try:
        importer.import_export(
            handle.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        context = RuleContext.from_store(handle.connection, end="2024-01-12")
        full = evaluate(document, context)
        selective = evaluate(document, context, rule_ids=["PRG-SPINE-001"])
    finally:
        handle.close()

    full_verdict = full.verdict("PRG-SPINE-001")
    selective_verdict = selective.verdict("PRG-SPINE-001")
    assert full_verdict.verdict == selective_verdict.verdict
    assert full_verdict.details == selective_verdict.details
    assert full_verdict.evidence == selective_verdict.evidence
    # The full path still evaluates every rule; only the reactive deload caller filters.
    assert len(full.verdicts) == len(document.rules)
