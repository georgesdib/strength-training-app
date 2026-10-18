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
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
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


def context_for(conn, date="2024-02-01"):
    return RuleContext.from_store(conn, end=date)


def decisions_for(conn, context):
    return evaluate(load_document(), context).verdict("PRG-DP-001").details.get(
        "decisions", {}
    )


# --- parsing ---------------------------------------------------------------


def test_parse_accepts_a_fenced_json_block():
    text = "\u0060\u0060\u0060json\n" + json.dumps({
        "summary": "simplify",
        "changes": [{"action": "drop", "exercise": "lateral_raise"}],
    }) + "\n\u0060\u0060\u0060"
    proposal = proposal_mod.parse(text)
    assert proposal.changes[0].action == "drop"


def test_a_load_in_a_proposal_is_rejected():
    with pytest.raises(proposal_mod.ProposalError, match="computed numbers"):
        proposal_mod.parse({
            "summary": "x",
            "changes": [{"action": "set_sets", "exercise": "lateral_raise",
                         "sets": 4, "load_kg": 100}],
        })


def test_unknown_action_is_rejected():
    with pytest.raises(proposal_mod.ProposalError, match="action must be one of"):
        proposal_mod.parse({"changes": [{"action": "add_load",
                                         "exercise": "lateral_raise"}]})


def test_extra_keys_are_rejected():
    with pytest.raises(proposal_mod.ProposalError, match="unexpected keys"):
        proposal_mod.parse({"changes": [{"action": "drop",
                                         "exercise": "lateral_raise",
                                         "reason": "because"}]})


# --- allowed substitutes ---------------------------------------------------


def test_allowed_substitutes_share_the_pattern_and_skip_essentials():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")
        context = context_for(conn)
        allowed = proposal_mod.allowed_substitutes(conn, context, prescription)

    assert "ssb_squat" not in allowed          # essential
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
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")
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
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="C")
        outcome = assess(conn, prescription, {
            "changes": [{"action": "substitute", "exercise": "split_squat",
                         "with": "lateral_raise"}],
        })
    assert not outcome.accepted
    assert any("does not match" in reason for reason in outcome.reasons)


def test_an_essential_lift_cannot_be_substituted_or_dropped():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")
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
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")
        ok = assess(conn, prescription, {
            "changes": [{"action": "set_sets", "exercise": "lateral_raise", "sets": 5}],
        })
        too_many = assess(conn, prescription, {
            "changes": [{"action": "set_sets", "exercise": "lateral_raise", "sets": 7}],
        })
    assert ok.accepted, ok.reasons
    assert not too_many.accepted


def test_reorder_must_be_a_permutation():
    with store_with(DAY_A) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")
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
    with store_with(DAY_A, readiness_rows=[{"Date": "2024-02-01", "Sleep": "2",
                                            "Energy": "4"}]) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")
        assert prescription.fallback_level == "fatigue_reduced"
        outcome = assess(conn, prescription, {
            "changes": [{"action": "drop", "exercise": "lateral_raise"}],
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
    assert cli.main(["--db", str(path), "run", "--date", "2024-02-01", "--day", "A",
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
        "changes": [{"action": "set_sets", "exercise": "lateral_raise", "sets": 4,
                     "load_kg": 100}],
    }))
    assert cli.main(["--db", str(path), "run", "--date", "2024-02-01", "--day", "A",
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
        "changes": [{"action": "drop", "exercise": "lateral_raise"}],
    }))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["--db", str(path), "run", "--date", "2024-02-01", "--day", "A",
                     "--llm", "on", "--propose"]) == 0

    store = db.Store(path)
    try:
        assert store.connection.execute(
            "SELECT approved_by FROM prescription"
        ).fetchone()["approved_by"] == "deterministic"
    finally:
        store.close()
