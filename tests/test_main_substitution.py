"""Main-lift substitution: allowed, but only with a rated replacement and rarely."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.agents import proposal as proposal_mod
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe.config import Thresholds
from strength_coach.rules import RuleContext, evaluate, load_document
from strength_coach.store import db, importer, queries, repositories

ROWS = [
    {"Date": "2026-09-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2026-09-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2026-09-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2026-09-01", "Exercise": "Split Squat", "Weight_Used": "30",
     "RIR": "3", "Reps_Done": "8"},
]
ROWS += [
    {"Date": day, "Exercise": "Competition Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"}
    for day in ("2024-01-01", "2024-01-08", "2024-01-15")
    for _ in range(4)
]


@contextmanager
def store_with():
    training = make_training(ROWS)
    readiness = make_readiness([{}])
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


def rate(conn, exercise_id, can_do=True, will_do=True, feels_bad=False):
    repositories.append_exercise_suitability(
        conn, exercise_id=exercise_id, rated_on="2026-10-01",
        can_do=can_do, will_do=will_do, feels_bad=feels_bad,
    )


def assess(conn, prescription, payload):
    context = RuleContext.from_store(conn, end=prescription.for_date)
    decisions = evaluate(load_document(), context).verdict("PRG-DP-001").details.get(
        "decisions", {}
    )
    return proposal_mod.assess(
        conn, prescription, proposal_mod.parse(payload),
        context=context, document=load_document(), thresholds=Thresholds.load(),
        decisions=decisions,
    )


def test_a_rated_primary_compound_can_replace_an_essential_lift():
    with store_with() as store:
        conn = store.connection
        rate(conn, "sumo_deadlift")
        prescription = build_prescription(conn, for_date="2026-10-20", session_day="B")
        outcome = assess(conn, prescription, {
            "summary": "switch the hinge to sumo",
            "changes": [{"action": "substitute", "exercise": "trap_bar_deadlift",
                         "with": "sumo_deadlift"}],
        })

    assert outcome.accepted, outcome.reasons
    item = next(i for i in outcome.prescription.items
                if i.exercise_id == "sumo_deadlift")
    assert item.essential is True
    assert item.load_kg is not None


def test_an_unrated_replacement_is_refused():
    with store_with() as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2026-10-20", session_day="B")
        outcome = assess(conn, prescription, {
            "changes": [{"action": "substitute", "exercise": "trap_bar_deadlift",
                         "with": "sumo_deadlift"}],
        })

    assert not outcome.accepted
    assert any("can-do / will-do rating" in reason for reason in outcome.reasons)


def test_at_most_one_main_lift_substitution_per_proposal():
    with store_with() as store:
        conn = store.connection
        rate(conn, "sumo_deadlift")
        rate(conn, "bench_press")
        prescription = build_prescription(conn, for_date="2026-10-20", session_day="B")
        outcome = assess(conn, prescription, {
            "changes": [
                {"action": "substitute", "exercise": "trap_bar_deadlift",
                 "with": "sumo_deadlift"},
                {"action": "substitute", "exercise": "bench_press_narrow",
                 "with": "bench_press"},
            ],
        })

    assert not outcome.accepted
    assert any("at most one main-lift substitution" in reason
               for reason in outcome.reasons)


def test_the_interval_limits_how_often_a_main_lift_changes():
    with store_with() as store:
        conn = store.connection
        rate(conn, "sumo_deadlift")
        prescription = build_prescription(conn, for_date="2026-10-20", session_day="B")
        run = repositories.start_run(conn, input_hash="x", code_version="test")
        conn.execute(
            "INSERT INTO run_event (run_id, seq, kind, payload, created_at) "
            "VALUES (?, 1, 'policy_verdict', ?, '2026-10-01T00:00:00.000Z')",
            (run.run_id, json.dumps({"main_substitution": True})),
        )
        outcome = assess(conn, prescription, {
            "changes": [{"action": "substitute", "exercise": "trap_bar_deadlift",
                         "with": "sumo_deadlift"}],
        })

    assert not outcome.accepted
    assert any("minimum interval" in reason for reason in outcome.reasons)


def test_state_rate_records_suitability(tmp_path):
    path = tmp_path / "coach.db"
    assert cli.main(["--db", str(path), "state", "--rate", "sumo_deadlift",
                     "--can-do", "yes", "--will-do", "yes"]) == 0
    store = db.Store(path)
    try:
        ratings = queries.exercise_suitability(store.connection)
        assert ratings["sumo_deadlift"]["can_do"] == 1
        assert ratings["sumo_deadlift"]["will_do"] == 1
        assert ratings["sumo_deadlift"]["feels_bad"] == 0
    finally:
        store.close()
