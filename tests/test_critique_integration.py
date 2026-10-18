"""Phase 6 acceptance on the real export.

The rubric must produce measured scores with resolvable evidence, and the two metrics the
export cannot support must be stored as unmeasured rather than guessed.
"""

from __future__ import annotations

import pytest

from strength_coach.critique import build_facts, persist, score_session
from strength_coach.rules import policy as policy_mod
from strength_coach.trace import RunTrace

pytestmark = pytest.mark.integration

SESSION = "2026-10-05"   # the most recent session identified as day B


@pytest.fixture(scope="module")
def scored(populated_db):
    store, _report, _shas = populated_db
    facts = build_facts(store.connection, SESSION)
    critique = score_session(store.connection, SESSION, facts=facts)
    return store, facts, critique


def test_real_session_scores_with_evidence(scored):
    _store, facts, critique = scored
    assert critique.composite is not None and 0.0 <= critique.composite <= 1.0
    for item in critique.measurable_items:
        assert item.score is not None
        for ref in item.evidence_refs:
            assert policy_mod.resolve_reference(facts.context, ref), ref


def test_the_three_failure_patterns_are_covered(scored):
    _store, _facts, critique = scored
    keys = {item.key for item in critique.measurable_items}
    assert {"RIR_ADHERENCE", "REDUNDANCY", "ROTATION"} <= keys


def test_unsupported_metrics_are_unmeasured(scored):
    _store, _facts, critique = scored
    for key in ("SESSION_DURATION", "VELOCITY_LOSS"):
        item = critique.item(key)
        assert item.measurable is False
        assert item.score is None


def test_critique_persists_with_a_trace(scored):
    store, _facts, critique = scored
    with RunTrace.start(store.connection, input_hash="integration") as trace:
        critique_id = persist(store.connection, critique, run_id=trace.run_id)
        trace.event("artifact", {"critique": critique_id})

    row = store.connection.execute(
        "SELECT * FROM rubric_score WHERE critique_id = ? AND item = 'SESSION_DURATION'",
        (critique_id,),
    ).fetchone()
    assert row["measurable"] == 0
    assert row["score"] is None
    assert store.connection.execute(
        "SELECT status FROM run WHERE run_id = ?", (trace.run_id,)
    ).fetchone()["status"] == "ok"
