"""The critique rubric: what it scores, and what it refuses to score.

Two properties matter more than any individual number:

* a metric the data cannot support is stored as measurable = 0 with no score, never as 0.0;
* every measured item cites rows that exist, so a score can be audited.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import pytest

from conftest import make_readiness, make_training
from strength_coach.critique import UnknownSessionError, persist, score_session
from strength_coach.critique.facts import build_facts
from strength_coach.critique.rubric import Critique, RUBRIC_WEIGHTS
from strength_coach.rules import load_document
from strength_coach.rules import policy as policy_mod
from strength_coach.store import db, importer
from strength_coach.trace import RunTrace


@contextmanager
def store_with(rows):
    training = make_training(rows)
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


def session_rows(date: str, *, deadlift_rir: str = "2", with_erector: bool = False,
                 bench: bool = True, exercises=None) -> list[dict]:
    rows = [
        {"Date": date, "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": deadlift_rir, "Reps_Done": "3"},
        {"Date": date, "Exercise": "Dumbbell Row", "Weight_Used": "30", "RIR": "2",
         "Reps_Done": "12"},
        {"Date": date, "Exercise": "Split Squat", "Weight_Used": "30", "RIR": "3",
         "Reps_Done": "8"},
    ]
    if bench:
        rows.append({"Date": date, "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
                     "RIR": "2", "Reps_Done": "5"})
    if with_erector:
        rows.append({"Date": date, "Exercise": "Back Extension", "Weight_Used": "10",
                     "RIR": "2", "Reps_Done": "12"})
    return rows


# --- RIR adherence ---------------------------------------------------------


def test_grinding_sets_lower_the_rir_score():
    # Three rated sets: the deadlift at RIR 0 is a violation, the row and bench at RIR 2 are
    # compliant, so the item scores two-thirds.
    rows = session_rows("2024-01-01", deadlift_rir="0")
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
        facts = build_facts(store.connection, "2024-01-01")
    item = critique.item("RIR_ADHERENCE")
    assert item.measurable and item.score == pytest.approx(0.6667)
    assert "2/3" in item.detail
    assert item.evidence_refs
    assert all(policy_mod.resolve_reference(facts.context, ref) for ref in item.evidence_refs)


def test_rir_item_is_unmeasurable_with_only_warmups():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "6", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
    item = critique.item("RIR_ADHERENCE")
    assert not item.measurable and item.score is None


# --- progression -----------------------------------------------------------


def test_progression_missed_when_top_of_range_was_not_added_to():
    rows = session_rows("2024-01-01") + session_rows("2024-01-08")
    # Lateral raise sat at the top (12 reps, RIR 2) on 01-01, so 01-08 should have added a
    # step; keeping 12.5 kg is a progression failure.
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-08")
    item = critique.item("PROGRESSION_ADHERENCE")
    assert item.measurable
    assert item.score < 1.0
    assert "dumbbell_row" in item.detail


def test_progression_credit_when_the_step_was_taken():
    first = session_rows("2024-01-01")
    second = [
        {**row, "Date": "2024-01-08"}
        for row in session_rows("2024-01-01")
    ]
    for row in second:
        if row["Exercise"] == "Dumbbell Row":
            row["Weight_Used"] = "32.5"
    with store_with(first + second) as store:
        critique = score_session(store.connection, "2024-01-08")
    assert critique.item("PROGRESSION_ADHERENCE").score == 1.0


# --- spinal cost -----------------------------------------------------------


def test_weekly_spinal_cost_scores_below_one_when_over_the_cap():
    rows = session_rows("2024-01-01") + session_rows("2024-01-03")
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-03")
    item = critique.item("WEEKLY_SPINAL_COST")
    assert item.score < 1.0
    assert item.evidence_refs == ("week:2024-W01",)


# --- essential work --------------------------------------------------------


def test_missing_essential_lift_costs_half_the_item():
    rows = session_rows("2024-01-01", bench=False)
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
    item = critique.item("ESSENTIAL_WORK")
    assert item.measurable and item.score == 0.5
    assert "1/2" in item.detail


def test_essential_work_is_unmeasurable_when_the_day_is_unknown():
    # Every programme day now has a template, so essential work is unassessable only when
    # the day itself could not be inferred. A bench-only session is "unknown", not day A.
    rows = [
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
    item = critique.item("ESSENTIAL_WORK")
    assert item.measurable is False
    assert "no prescription template" in item.detail


# --- redundancy ------------------------------------------------------------


def test_hinge_plus_erector_is_redundant():
    rows = session_rows("2024-01-01", with_erector=True)
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
    item = critique.item("REDUNDANCY")
    assert item.measurable and item.score == 0.5


def test_a_clean_session_has_no_redundancy():
    rows = session_rows("2024-01-01")
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
    assert critique.item("REDUNDANCY").score == 1.0


# --- rotation --------------------------------------------------------------


def test_app_assigned_rotation_is_scored_neutral():
    rows = session_rows("2024-01-01") + session_rows("2024-01-08")
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-08")
    item = critique.item("ROTATION")
    assert item.measurable and item.score == 1.0
    assert "app-assigned" in item.detail


def test_self_directed_rotation_is_penalised():
    first = [
        {"Date": "2024-01-01", "Workout": "Freestyle", "Exercise": "Competition Squat",
         "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Workout": "Freestyle", "Exercise": "Competition Bench Press",
         "Weight_Used": "80", "RIR": "2", "Reps_Done": "5"},
    ]
    second = [
        {"Date": "2024-01-08", "Workout": "Freestyle", "Exercise": "Romanian Deadlift",
         "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-08", "Workout": "Freestyle", "Exercise": "Lateral Raise",
         "Weight_Used": "12.5", "RIR": "2", "Reps_Done": "10"},
    ]
    with store_with(first + second) as store:
        critique = score_session(store.connection, "2024-01-08")
    item = critique.item("ROTATION")
    assert item.measurable and item.score == 0.0   # no overlap at all


# --- the two unmeasurable items -------------------------------------------


def test_duration_and_velocity_loss_are_stored_unmeasured():
    rows = session_rows("2024-01-01")
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
    for key in ("SESSION_DURATION", "VELOCITY_LOSS"):
        item = critique.item(key)
        assert not item.measurable
        assert item.score is None


def test_composite_ignores_unmeasurable_items():
    rows = session_rows("2024-01-01")
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
    measured = [i for i in critique.items if i.measurable]
    assert 0 < sum(i.weight for i in measured) <= 1.0
    # The composite re-normalises over what was measurable, so an unmeasurable item never
    # drags the score toward zero.
    expected = sum(i.weight * i.score for i in measured) / sum(i.weight for i in measured)
    assert critique.composite == pytest.approx(expected)


# --- facts and persistence -------------------------------------------------


def test_unknown_session_raises():
    with store_with(session_rows("2024-01-01")) as store:
        with pytest.raises(UnknownSessionError):
            score_session(store.connection, "1999-01-01")


def test_facts_hash_is_stable_and_changes_with_content():
    with store_with(session_rows("2024-01-01")) as store:
        first = build_facts(store.connection, "2024-01-01").facts_hash()
        second = build_facts(store.connection, "2024-01-01").facts_hash()
    assert first == second

    with store_with(session_rows("2024-01-01", with_erector=True)) as store:
        changed = build_facts(store.connection, "2024-01-01").facts_hash()
    assert changed != first


def test_persist_writes_the_critique_and_its_scores():
    rows = session_rows("2024-01-01")
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
        with RunTrace.start(store.connection, input_hash="abc") as trace:
            critique_id = persist(store.connection, critique, run_id=trace.run_id)
            trace.event("artifact", {"critique": critique_id})

        row = store.connection.execute(
            "SELECT * FROM critique WHERE critique_id = ?", (critique_id,)
        ).fetchone()
        assert row["facts_hash"] == critique.facts_hash
        assert row["narrative"] == critique.narrative

        scores = {
            r["item"]: r
            for r in store.connection.execute(
                "SELECT * FROM rubric_score WHERE critique_id = ?", (critique_id,)
            )
        }
        assert len(scores) == len(critique.items)
        assert scores["RIR_ADHERENCE"]["measurable"] == 1
        assert scores["SESSION_DURATION"]["measurable"] == 0
        assert scores["SESSION_DURATION"]["score"] is None
        assert trace.status == "ok"


def test_measured_live_duration_is_scored_against_the_session_caps():
    rows = session_rows("2024-01-01")
    with store_with(rows) as store:
        conn = store.connection
        conn.execute(
            "UPDATE session SET duration_min = ?, duration_basis = 'measured' "
            "WHERE session_id = '2024-01-01'",
            (75.0,),
        )
        on_plan = score_session(conn, "2024-01-01")
        conn.execute(
            "UPDATE session SET duration_min = 85.0 WHERE session_id = '2024-01-01'"
        )
        partial = score_session(conn, "2024-01-01")
        conn.execute(
            "UPDATE session SET duration_min = 95.0 WHERE session_id = '2024-01-01'"
        )
        over = score_session(conn, "2024-01-01")
    assert on_plan.item("SESSION_DURATION").measurable
    assert on_plan.item("SESSION_DURATION").score == 1.0
    assert partial.item("SESSION_DURATION").score == pytest.approx(0.5)
    assert over.item("SESSION_DURATION").score == 0.0
    assert "80 planned" in on_plan.item("SESSION_DURATION").detail


def test_form_assessment_is_optional_and_scored_when_present():
    rows = session_rows("2024-01-01")
    with store_with(rows) as store:
        conn = store.connection
        conn.execute(
            "INSERT INTO session_form_rating (session_id, exercise_id, rating) "
            "VALUES ('2024-01-01', 'ssb_squat', 4), ('2024-01-01', 'bench_press', 5)"
        )
        critique = score_session(conn, "2024-01-01")
    item = critique.item("FORM_ASSESSMENT")
    assert item.measurable
    assert item.score == pytest.approx(0.9)
    assert "2 lift(s)" in item.detail


def test_rubric_has_eight_weighted_items_plus_one_zero_weight_diagnostic():
    assert len(RUBRIC_WEIGHTS) == 9
    assert sum(RUBRIC_WEIGHTS.values()) == pytest.approx(1.0)
    assert [key for key, weight in RUBRIC_WEIGHTS.items() if weight == 0] == ["VELOCITY_LOSS"]


def test_a_zero_weight_item_becoming_measurable_does_not_change_the_composite():
    rows = session_rows("2024-01-01")
    with store_with(rows) as store:
        critique = score_session(store.connection, "2024-01-01")
    velocity = replace(critique.item("VELOCITY_LOSS"), measurable=True, score=0.0)
    items = tuple(velocity if item.key == "VELOCITY_LOSS" else item for item in critique.items)
    augmented = Critique(critique.session_id, critique.facts_hash, items, critique.narrative)
    assert augmented.composite == pytest.approx(critique.composite)
