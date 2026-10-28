"""Structured LLM proposals: parsed strictly, judged by the engine, applied only if valid."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach import cli
from strength_coach.agents import LLMResponse
from strength_coach.agents import proposal as proposal_mod
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe.config import Thresholds
from strength_coach.rules import RuleContext, evaluate, load_document
from strength_coach.store import db, importer

DAY_A = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "12"},
    {"Date": "2024-01-01", "Exercise": "Dumbbell Row", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Lying Leg Curls", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "10"},
]

DAY_C = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "12"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30",
     "RIR": "3", "Reps_Done": "8"},
]


@contextmanager
def store_with(rows, readiness_rows=None):
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def context_for(conn, date="2024-01-08"):
    return RuleContext.from_store(conn, end=date)


def decisions_for(conn, context):
    return evaluate(load_document(), context).verdict("PRG-DP-001").details.get(
        "decisions", {}
    )


# --- parsing ---------------------------------------------------------------


def test_parse_accepts_a_fenced_json_block():
    text = "\u0060\u0060\u0060json\n" + json.dumps({
        "summary": "simplify",
        "changes": [{"action": "drop", "exercise": "ab_wheel"}],
    }) + "\n\u0060\u0060\u0060"
    proposal = proposal_mod.parse(text)
    assert proposal.changes[0].action == "drop"


@pytest.mark.parametrize("payload, message", [
    ({"summary": "x", "changes": [{"action": "set_sets", "exercise": "ab_wheel",
                                    "sets": 4, "load_kg": 100}]}, "computed numbers"),
    ({"changes": [{"action": "add_load", "exercise": "ab_wheel"}]},
     "action must be one of"),
    ({"changes": [{"action": "drop", "exercise": "ab_wheel",
                   "reason": "because"}]}, "unexpected keys"),
])
def test_invalid_proposals_are_rejected(payload, message):
    with pytest.raises(proposal_mod.ProposalError, match=message):
        proposal_mod.parse(payload)


# --- allowed substitutes ---------------------------------------------------


def test_allowed_substitutes_share_the_pattern_and_require_ratings_for_mains():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        context = context_for(conn)
        allowed = proposal_mod.allowed_substitutes(conn, context, prescription)

    # An essential lift may be swapped only for a rated primary compound; none are rated here.
    assert allowed["ssb_squat"] == []
    assert "back_extension" in allowed
    assert "hyperextension" in allowed["back_extension"]
    patterns = {context.entity(e).get("pattern") for e in allowed["back_extension"]}
    assert patterns == {"erector_extension"}


# --- assessment ------------------------------------------------------------


def assess(conn, prescription, payload):
    context = context_for(conn)
    return proposal_mod.assess(
        conn, prescription, proposal_mod.parse(payload) if isinstance(payload, dict) else payload,
        context=context, document=load_document(), thresholds=Thresholds.load(),
        decisions=decisions_for(conn, context),
    )


def test_a_legal_substitution_is_accepted_and_rebuilt():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        outcome = assess(conn, prescription, {
            "summary": "swap the back extension",
            "changes": [{"action": "substitute", "exercise": "back_extension",
                         "with": "hyperextension"}],
        })

    assert outcome.accepted, outcome.reasons
    ids = [item.exercise_id for item in outcome.prescription.items]
    assert "hyperextension" in ids and "back_extension" not in ids
    swapped = next(i for i in outcome.prescription.items
                   if i.exercise_id == "hyperextension")
    assert swapped.load_kg == 0.0


def test_a_pattern_change_is_rejected():
    with store_with(DAY_C) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        outcome = assess(conn, prescription, {
            "changes": [{"action": "substitute", "exercise": "dumbbell_row",
                         "with": "pull_up"}],
        })
    assert not outcome.accepted
    assert any("does not match" in reason for reason in outcome.reasons)


def test_an_essential_lift_cannot_be_substituted_or_dropped():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        swapped = assess(conn, prescription, {
            "changes": [{"action": "substitute", "exercise": "ssb_squat",
                         "with": "competition_squat"}],
        })
        dropped = assess(conn, prescription, {
            "changes": [{"action": "drop", "exercise": "bench_press"}],
        })
    assert not swapped.accepted
    assert not dropped.accepted


def test_set_changes_are_bounded():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        ok = assess(conn, prescription, {
            "changes": [{"action": "set_sets", "exercise": "ab_wheel", "sets": 5}],
        })
        too_many = assess(conn, prescription, {
            "changes": [{"action": "set_sets", "exercise": "ab_wheel", "sets": 7}],
        })
    assert ok.accepted, ok.reasons
    assert not too_many.accepted


def test_reorder_must_be_a_permutation():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        ids = [item.exercise_id for item in prescription.items]
        ok = assess(conn, prescription, {
            "changes": [{"action": "reorder", "order": list(reversed(ids))}],
        })
        bad = assess(conn, prescription, {
            "changes": [{"action": "reorder", "order": ids[:2]}],
        })
    assert ok.accepted, ok.reasons
    assert [i.exercise_id for i in ok.prescription.items] == list(reversed(ids))
    assert not bad.accepted


def test_a_downgraded_session_is_not_open_to_proposals():
    with store_with(DAY_A, readiness_rows=[{"Date": "2024-01-08", "Sleep": "2",
                                            "Energy": "4"}]) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        assert prescription.fallback_level == "fatigue_reduced"
        outcome = assess(conn, prescription, {
            "changes": [{"action": "drop", "exercise": "ab_wheel"}],
        })
    assert not outcome.accepted
    assert any("safety rule" in reason for reason in outcome.reasons)


# --- CLI -------------------------------------------------------------------


class FakeClient:
    model = "fake"

    def __init__(self, text):
        self.text = text
        self.available = True

    def complete(self, prompt, *, system=None):
        return LLMResponse(text=self.text, model=self.model, tokens=12)


def prepare(tmp_path, rows=DAY_A, readiness_rows=None):
    path = tmp_path / "coach.db"
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
    store = db.Store(path)
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
    finally:
        store.close()
    return path


def patch_client(monkeypatch, text):
    monkeypatch.setattr(cli, "load_settings", lambda: None)
    monkeypatch.setattr(cli, "build_client", lambda settings=None: FakeClient(text))


def test_cli_applies_an_accepted_proposal(tmp_path, monkeypatch, capsys):
    path = prepare(tmp_path)
    patch_client(monkeypatch, json.dumps({
        "summary": "swap the back extension",
        "changes": [{"action": "substitute", "exercise": "back_extension",
                     "with": "hyperextension"}],
    }))
    assert cli.main(["--db", str(path), "run", "--date", "2024-01-08", "--session-type", "squat",
                     "--llm", "on", "--propose", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "accepted" in out

    store = db.Store(path)
    try:
        row = store.connection.execute(
            "SELECT approved_by FROM prescription"
        ).fetchone()
        assert row["approved_by"] == "llm+policy"
        ids = [r["exercise_id"] for r in store.connection.execute(
            "SELECT exercise_id FROM prescription_item"
        )]
        assert "hyperextension" in ids
        kinds = [r["kind"] for r in store.connection.execute(
            "SELECT kind FROM run_event"
        )]
        assert "llm_output" in kinds and "policy_verdict" in kinds
    finally:
        store.close()


def test_cli_falls_back_when_the_proposal_carries_a_load(tmp_path, monkeypatch, capsys):
    path = prepare(tmp_path)
    patch_client(monkeypatch, json.dumps({
        "summary": "x",
        "changes": [{"action": "set_sets", "exercise": "ab_wheel", "sets": 4,
                     "load_kg": 100}],
    }))
    assert cli.main(["--db", str(path), "run", "--date", "2024-01-08", "--session-type", "squat",
                     "--llm", "on", "--propose", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "rejected" in out

    store = db.Store(path)
    try:
        assert store.connection.execute(
            "SELECT approved_by FROM prescription"
        ).fetchone()["approved_by"] == "deterministic"
        # The import itself opens a run, so read the newest one, not the first.
        assert store.connection.execute(
            "SELECT status FROM run ORDER BY rowid DESC LIMIT 1"
        ).fetchone()["status"] == "llm_downgraded"
    finally:
        store.close()


def test_cli_declining_keeps_the_deterministic_session(tmp_path, monkeypatch):
    path = prepare(tmp_path)
    patch_client(monkeypatch, json.dumps({
        "summary": "simplify",
        "changes": [{"action": "drop", "exercise": "ab_wheel"}],
    }))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["--db", str(path), "run", "--date", "2024-01-08", "--session-type", "squat",
                     "--llm", "on", "--propose"]) == 0

    store = db.Store(path)
    try:
        assert store.connection.execute(
            "SELECT approved_by FROM prescription"
        ).fetchone()["approved_by"] == "deterministic"
    finally:
        store.close()


# --- menu choices ----------------------------------------------------------


def test_menu_options_are_bounded_by_the_rir_rule():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        options = proposal_mod.menu(prescription, load_document())

    bench = options["bench_press"]
    assert "keep" in bench and "easier" in bench and "heavier" in bench
    # DEC-RIR-02: the allowed window is 1-4, so RIR 2 can go harder to RIR 1.
    assert "harder" in bench
    assert bench["harder"]["rir_target"] == 1
    assert bench["harder"]["load_kg"] > bench["keep"]["load_kg"]
    assert bench["easier"]["rir_target"] == 3
    assert bench["easier"]["load_kg"] < bench["keep"]["load_kg"]
    assert bench["heavier"]["load_kg"] > bench["keep"]["load_kg"]


def test_choosing_a_menu_option_applies_pythons_value():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        outcome = assess(conn, prescription, {
            "changes": [{"action": "choose", "exercise": "bench_press",
                         "option": "easier"}],
        })

    assert outcome.accepted, outcome.reasons
    bench = next(i for i in outcome.prescription.items if i.exercise_id == "bench_press")
    assert bench.rir_target == 3
    assert bench.load_kg < 84.5


def test_an_option_the_menu_does_not_offer_is_rejected():
    from dataclasses import replace as dataclass_replace

    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        # At RIR 1 a "harder" option would mean RIR 0, which the rule forbids.
        items = list(prescription.items)
        index = next(i for i, item in enumerate(items) if item.exercise_id == "bench_press")
        items[index] = dataclass_replace(items[index], rir_target=1)
        low = dataclass_replace(prescription, items=tuple(items))
        outcome = assess(conn, low, {
            "changes": [{"action": "choose", "exercise": "bench_press",
                         "option": "harder"}],
        })
    assert not outcome.accepted
    assert any("not offered" in reason for reason in outcome.reasons)


def test_unknown_option_name_is_rejected_by_the_parser():
    with pytest.raises(proposal_mod.ProposalError, match="option must be one of"):
        proposal_mod.parse({"changes": [{"action": "choose", "exercise": "bench_press",
                                         "option": "max_out"}]})


def test_an_rir_target_outside_the_rule_window_is_reported():
    from dataclasses import replace as dataclass_replace

    from strength_coach.prescribe.engine import validate_prescription

    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        context = context_for(conn)
        items = list(prescription.items)
        index = next(i for i, item in enumerate(items) if item.exercise_id == "bench_press")
        items[index] = dataclass_replace(items[index], rir_target=0)
        issues = validate_prescription(
            tuple(items), context, load_document(), "A", "2024-01-08"
        )

    assert any(issue.startswith("RIR_OUTSIDE_WINDOW:bench_press") for issue in issues)


def test_rir_1_is_accepted_by_the_validator():
    from dataclasses import replace as dataclass_replace

    from strength_coach.prescribe.engine import validate_prescription

    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        context = context_for(conn)
        items = list(prescription.items)
        index = next(i for i, item in enumerate(items) if item.exercise_id == "bench_press")
        items[index] = dataclass_replace(items[index], rir_target=1)
        issues = validate_prescription(
            tuple(items), context, load_document(), "A", "2024-01-08"
        )

    assert not any(issue.startswith("RIR_OUTSIDE_WINDOW") for issue in issues)


# --- rep schemes -----------------------------------------------------------

DAY_B = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30",
     "RIR": "3", "Reps_Done": "8"},
]


def test_maximal_scheme_is_the_lowest_and_excludes_hinges():
    from strength_coach.prescribe.schemes import Schemes

    schemes = Schemes.load()
    maximal = schemes.get("maximal")
    assert (maximal.reps_low, maximal.reps_high) == (1, 3)
    assert maximal.allows("ssb_squat")
    assert not maximal.allows("trap_bar_deadlift")
    assert schemes.applicable("maximal", exercise_id="bench_press", essential=True)
    assert not schemes.applicable("maximal", exercise_id="ab_wheel", essential=False)
    assert schemes.maximal_hinge_allowed is False
    assert not schemes.applicable("maximal", exercise_id="trap_bar_deadlift", essential=True)
    assert schemes.applicable(
        "maximal", exercise_id="trap_bar_deadlift", essential=True,
        maximal_hinge_allowed=True,
    )


def test_setting_the_maximal_scheme_rebuilds_reps_and_load():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        before = next(i for i in prescription.items if i.exercise_id == "bench_press")
        outcome = assess(conn, prescription, {
            "changes": [{"action": "set_scheme", "exercise": "bench_press",
                         "scheme": "maximal"}],
        })

    assert outcome.accepted, outcome.reasons
    after = next(i for i in outcome.prescription.items if i.exercise_id == "bench_press")
    assert (after.reps_low, after.reps_high) == (1, 3)
    assert after.load_kg > before.load_kg        # fewer reps at the same RIR means more load


def test_maximal_scheme_is_refused_on_the_hinge():
    with store_with(DAY_B) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="hinge")
        outcome = assess(conn, prescription, {
            "changes": [{"action": "set_scheme", "exercise": "trap_bar_deadlift",
                         "scheme": "maximal"}],
        })
    assert not outcome.accepted
    assert any("not allowed" in reason for reason in outcome.reasons)


def test_maximal_scheme_is_refused_on_an_accessory():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        outcome = assess(conn, prescription, {
            "changes": [{"action": "set_scheme", "exercise": "ab_wheel",
                         "scheme": "maximal"}],
        })
    assert not outcome.accepted


def test_volume_scheme_is_offered_to_accessories():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")
        outcome = assess(conn, prescription, {
            "changes": [{"action": "set_scheme", "exercise": "ab_wheel",
                         "scheme": "volume"}],
        })
    assert outcome.accepted, outcome.reasons
    item = next(i for i in outcome.prescription.items if i.exercise_id == "ab_wheel")
    assert (item.reps_low, item.reps_high) == (6, 8)
