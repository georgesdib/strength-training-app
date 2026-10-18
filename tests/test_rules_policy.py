"""Policy evaluation: what the constitution concludes about real rows.

The load-bearing assertions are about honesty rather than arithmetic:

* a rule whose inputs do not exist is `unknown`, never `pass`;
* every evidence reference resolves to a stored set or week;
* the aggregate outcome prefers the strongest effect (veto > downgrade > warn > unknown > pass).
"""

from __future__ import annotations

import dataclasses

import pytest

from conftest import make_readiness, make_training
from strength_coach.rules import RuleContext, evaluate, load_document, publish, resolve_reference
from strength_coach.rules import registry
from strength_coach.rules.policy import UnresolvedReference
from strength_coach.store import db, importer


@pytest.fixture(scope="module")
def document():
    return load_document()


def context(rows, *, readiness_rows=None, **kwargs) -> RuleContext:
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection,
            training,
            readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        return RuleContext.from_store(store.connection, **kwargs)
    finally:
        store.close()


def squat(rir: str, date: str = "2024-01-01", reps: str = "5") -> dict:
    return {"Date": date, "Exercise": "Safety Squat Bar", "Weight_Used": "100", "RIR": rir,
            "Reps_Done": reps}


def bench(rir: str, date: str = "2024-01-01", reps: str = "5", weight: str = "80") -> dict:
    return {"Date": date, "Exercise": "Competition Bench Press", "Weight_Used": weight,
            "RIR": rir, "Reps_Done": reps}


def trap_bar(date: str, sets: int = 3) -> list[dict]:
    return [
        {"Date": date, "Exercise": "Competition Deadlift", "Weight_Used": "150", "RIR": "2"}
        for _ in range(sets)
    ]


# --- PRG-RIR-001 -----------------------------------------------------------


def test_rir_floor_fails_with_resolvable_evidence(document):
    # RIR 0 is the forbidden grinding set; RIR 1 is inside the widened window (DEC-RIR-02).
    ctx = context([squat("0")])
    result = evaluate(document, ctx, rule_ids=["PRG-RIR-001"])
    verdict = result.verdict("PRG-RIR-001")

    assert verdict.verdict == "fail"
    assert verdict.code == "RIR_FLOOR"
    assert verdict.details["below_floor"] == 1
    assert verdict.evidence
    assert all(resolve_reference(ctx, item.ref) for item in verdict.evidence)


def test_warmup_sets_are_excluded_from_effort_scoring(document):
    # DEC-RIR-01: RIR 6 marks a warm-up, not a very easy set.
    ctx = context([squat("6")])
    verdict = evaluate(document, ctx, rule_ids=["PRG-RIR-001"]).verdict("PRG-RIR-001")
    assert verdict.verdict == "unknown"
    assert verdict.missing_inputs == ("set.rir",)


def test_effort_above_the_window_is_reported_but_does_not_fail(document):
    # RIR 4 is inside the window; 5 is above it but still only reported, not failed.
    ctx = context([squat("4"), squat("5")])
    verdict = evaluate(document, ctx, rule_ids=["PRG-RIR-001"]).verdict("PRG-RIR-001")
    assert verdict.verdict == "pass"
    assert verdict.details["above_ceiling"] == 1
    assert verdict.details["below_floor"] == 0


def test_rir_1_is_now_inside_the_allowed_window(document):
    ctx = context([squat("1")])
    verdict = evaluate(document, ctx, rule_ids=["PRG-RIR-001"]).verdict("PRG-RIR-001")
    assert verdict.verdict == "pass"
    assert verdict.details["below_floor"] == 0


def test_unknown_when_no_primary_compound_was_trained(document):
    ctx = context([{"Date": "2024-01-01", "Exercise": "Lateral Raise",
                    "Weight_Used": "10", "RIR": "2"}])
    verdict = evaluate(document, ctx, rule_ids=["PRG-RIR-001"]).verdict("PRG-RIR-001")
    assert verdict.verdict == "unknown"


def test_max_single_is_judged_against_multi_rep_history(document):
    rows = [bench("2", date="2024-01-01") for _ in range(4)]
    rows.append(bench("3", date="2024-01-02", reps="1", weight="95"))
    ctx = context(rows)
    verdict = evaluate(document, ctx, rule_ids=["PRG-RIR-001"]).verdict("PRG-RIR-001")
    assert verdict.verdict == "fail"
    assert verdict.details["max_singles"] == 1
    assert "single at" in verdict.evidence[-1].detail


def test_a_submaximal_single_does_not_fail(document):
    rows = [bench("2", date="2024-01-01") for _ in range(4)]
    rows.append(bench("3", date="2024-01-02", reps="1", weight="70"))
    ctx = context(rows)
    verdict = evaluate(document, ctx, rule_ids=["PRG-RIR-001"]).verdict("PRG-RIR-001")
    assert verdict.details["max_singles"] == 0


# --- PRG-SPINE-001 ---------------------------------------------------------


def test_spinal_cap_fires_on_accumulated_exposures(document):
    # Two hinge sessions in one ISO week: 2 x spinal_cost 2 = 4 > cap 3.
    ctx = context(trap_bar("2024-01-01") + trap_bar("2024-01-03"))
    verdict = evaluate(document, ctx, rule_ids=["PRG-SPINE-001"]).verdict("PRG-SPINE-001")
    assert verdict.verdict == "fail"
    assert verdict.evidence[0].ref.startswith("week:")


def test_one_hinge_session_stays_under_the_cap(document):
    ctx = context(trap_bar("2024-01-01"))
    verdict = evaluate(document, ctx, rule_ids=["PRG-SPINE-001"]).verdict("PRG-SPINE-001")
    assert verdict.verdict == "pass"
    assert verdict.details["weighted_costs"] == {"2024-W01": 2.0}


def test_sets_do_not_multiply_an_exposure(document):
    # Same session, many sets: still one exposure. Counting per set would fire the cap
    # on every trap-bar day, which is the failure mode the rule notes warn about.
    ctx = context(trap_bar("2024-01-01", sets=12))
    verdict = evaluate(document, ctx, rule_ids=["PRG-SPINE-001"]).verdict("PRG-SPINE-001")
    assert verdict.verdict == "pass"
    assert verdict.details["weighted_costs"] == {"2024-W01": 2.0}


def test_weeks_are_independent(document):
    ctx = context(trap_bar("2024-01-01") + trap_bar("2024-01-08"))
    verdict = evaluate(document, ctx, rule_ids=["PRG-SPINE-001"]).verdict("PRG-SPINE-001")
    assert verdict.verdict == "pass"
    assert len(verdict.details["weighted_costs"]) == 2


def test_no_spinal_work_is_a_pass_not_an_unknown(document):
    ctx = context([bench("2")])
    verdict = evaluate(document, ctx, rule_ids=["PRG-SPINE-001"]).verdict("PRG-SPINE-001")
    assert verdict.verdict == "pass"
    assert verdict.details["weeks_with_spinal_work"] == 0


# --- PRG-EREC-001 ----------------------------------------------------------


def test_erector_ramp_is_unknown_and_names_both_missing_inputs(document):
    ctx = context([squat("2")])
    verdict = evaluate(document, ctx, rule_ids=["PRG-EREC-001"]).verdict("PRG-EREC-001")
    assert verdict.verdict == "unknown"
    assert set(verdict.missing_inputs) == {"symptom.flare", "block.week_index"}


def test_symptom_input_alone_still_leaves_the_ramp_unanchored(document):
    ctx = context([squat("2")], symptom_flare=False)
    verdict = evaluate(document, ctx, rule_ids=["PRG-EREC-001"]).verdict("PRG-EREC-001")
    assert verdict.verdict == "unknown"
    assert verdict.missing_inputs == ("block.week_index",)


# --- PRG-SCHED-001 ---------------------------------------------------------


def test_hinge_stacked_with_erector_work_fails(document):
    rows = trap_bar("2024-01-01") + [
        {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "0", "RIR": "3"}
    ]
    ctx = context(rows)
    verdict = evaluate(document, ctx, rule_ids=["PRG-SCHED-001"]).verdict("PRG-SCHED-001")
    assert verdict.verdict == "fail"
    assert "stacked with a hinge" in verdict.evidence[0].detail


def test_a_normal_squat_and_bench_session_passes(document):
    ctx = context([squat("2"), bench("2")])
    verdict = evaluate(document, ctx, rule_ids=["PRG-SCHED-001"]).verdict("PRG-SCHED-001")
    assert verdict.verdict == "pass"
    assert verdict.details["sessions_with_erector"] == 0


# --- PRG-DP-001 ------------------------------------------------------------


def test_double_progression_is_unknown_without_rep_ranges(document):
    ctx = context([{"Date": "2024-01-01", "Exercise": "Back Extension",
                    "Weight_Used": "0", "RIR": "2"}])
    verdict = evaluate(document, ctx, rule_ids=["PRG-DP-001"]).verdict("PRG-DP-001")
    assert verdict.verdict == "unknown"
    assert all(item.startswith("rep_range.") for item in verdict.missing_inputs)


def test_double_progression_decides_when_ranges_are_supplied(document):
    rows = [
        {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "12"},
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "10",
         "RIR": "2", "Reps_Done": "15"},
        {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "20",
         "RIR": "3", "Reps_Done": "10"},
    ]
    ctx = context(
        rows,
        rep_ranges={"back_extension": (8, 12), "lateral_raise": (12, 15), "split_squat": (8, 10)},
    )
    verdict = evaluate(document, ctx, rule_ids=["PRG-DP-001"]).verdict("PRG-DP-001")
    assert verdict.verdict == "pass"
    assert verdict.details["decisions"]["back_extension"]["decision"] == "add_increment"
    assert verdict.details["decisions"]["split_squat"]["increment_kg"] == 2.5


# --- aggregate policy ------------------------------------------------------


def test_unknown_outranks_pass(document):
    ctx = context([squat("6")])  # only warm-ups: the RIR rule cannot be assessed
    result = evaluate(document, ctx)
    assert result.outcome == "unknown"
    assert "PRG-EREC-001" in result.unknown_rule_ids


def test_veto_outranks_unknown(document):
    ctx = context([squat("0")])
    result = evaluate(document, ctx)
    assert result.outcome == "veto"
    assert result.vetoes and result.vetoes[0].rule_id == "PRG-RIR-001"
    assert result.unknowns


def test_unresolvable_evidence_is_rejected(document, monkeypatch):
    def bad_predicate(document, rule, context):
        return registry.Evaluation(
            registry.FAIL,
            rule.fail_code,
            (registry.Evidence(ref="set:1999-01-01/999", detail="invented"),),
        )

    monkeypatch.setitem(registry._REGISTRY, "primary_compound_rir_window", bad_predicate)
    ctx = context([squat("1")])
    with pytest.raises(UnresolvedReference, match="unresolvable evidence"):
        evaluate(document, ctx, rule_ids=["PRG-RIR-001"])


def test_reference_resolution(document):
    ctx = context([squat("2")])
    set_id = int(ctx.sets["set_id"].iloc[0])
    session_id = str(ctx.sets["session_id"].iloc[0])

    assert resolve_reference(ctx, f"set:{session_id}/{set_id}")
    assert resolve_reference(ctx, f"session:{session_id}")
    assert resolve_reference(ctx, "week:2024-W01")
    assert not resolve_reference(ctx, "set:1999-01-01/1")
    assert not resolve_reference(ctx, "nonsense:1")


# --- publishing ------------------------------------------------------------


def test_the_draft_constitution_is_refused_at_publish():
    # It has no effective_from, and inventing one would make "what was in force on date X"
    # answerable wrongly.
    document = load_document()
    with db.Store(":memory:") as store:
        with pytest.raises(ValueError, match="no effective_from"):
            publish(store.connection, document)
        assert store.connection.execute(
            "SELECT COUNT(*) AS c FROM rule_document"
        ).fetchone()["c"] == 0


def test_publishing_records_the_document_and_its_rules():
    document = dataclasses.replace(load_document(), effective_from="2026-10-17")
    with db.Store(":memory:") as store:
        assert publish(store.connection, document) is True
        assert publish(store.connection, document) is False  # idempotent

        row = store.connection.execute("SELECT * FROM rule_document").fetchone()
        assert row["document_id"] == document.document_id
        assert row["source_hash"] == document.source_hash
        assert store.connection.execute("SELECT COUNT(*) AS c FROM rule").fetchone()["c"] == len(
            document.rules
        )
        severities = {
            r["rule_id"]: r["severity"]
            for r in store.connection.execute("SELECT rule_id, severity FROM rule")
        }
        assert severities["PRG-RIR-001"] == "veto"


def test_publishing_a_changed_document_under_the_same_version_is_refused():
    document = dataclasses.replace(load_document(), effective_from="2026-10-17")
    with db.Store(":memory:") as store:
        publish(store.connection, document)
        tampered = dataclasses.replace(document, source_hash="0" * 64)
        with pytest.raises(ValueError, match="bump the version"):
            publish(store.connection, tampered)
