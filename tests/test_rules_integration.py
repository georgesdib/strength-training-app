"""The constitution against real history: phase 4's acceptance criterion.

Two rules must produce verdicts with evidence references on the stored export, and the
erector ramp must be `unknown` because neither of its inputs exists. Anything else would
mean the policy engine is guessing.
"""

from __future__ import annotations

import pytest

from strength_coach.rules import RuleContext, evaluate, load_document

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def document():
    return load_document()


def test_constitution_evaluates_against_real_history(populated_db, document):
    store, _report, _shas = populated_db
    context = RuleContext.from_store(store.connection)

    result = evaluate(document, context)

    rir = result.verdict("PRG-RIR-001")
    assert rir.verdict in {"pass", "fail"}
    assert rir.details["rated_sets"] > 0
    if rir.failed:
        assert rir.evidence, "a failure must cite the offending sets"
        assert all(item.ref.startswith("set:") for item in rir.evidence)

    spine = result.verdict("PRG-SPINE-001")
    assert spine.verdict in {"pass", "fail"}
    assert spine.details["weeks_with_spinal_work"] > 0
    if spine.failed:
        assert all(item.ref.startswith("week:") for item in spine.evidence)

    erec = result.verdict("PRG-EREC-001")
    assert erec.verdict == "unknown"
    assert set(erec.missing_inputs) == {"symptom.flare", "block.week_index"}

    # Nothing here may be reported as a clean pass while a rule is unassessable.
    assert result.outcome != "pass"
    assert set(result.unknown_rule_ids) >= {"PRG-EREC-001", "PRG-DP-001"}
