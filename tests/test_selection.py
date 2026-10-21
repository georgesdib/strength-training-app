"""Shadow exercise selection: deterministic ranking, filters, LLM validation."""

from __future__ import annotations

from conftest import make_readiness, make_training
from strength_coach.prescribe import selection
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer, repositories


def store_with(rows=None):
    rows = rows or [
        {"Date": "2024-01-01", "Exercise": "Pull-ups (wide grip)", "Weight_Used": "0",
         "RIR": "2", "Reps_Done": "8"},
        {"Date": "2024-01-08", "Exercise": "Lat Pulldown", "Weight_Used": "60",
         "RIR": "2", "Reps_Done": "10"},
        {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
         "RIR": "2", "Reps_Done": "5"},
    ]
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def pull_slot(rows):
    return next(row for row in rows if row.slot_id == "accessory_pull_up")


def test_the_most_recent_variant_is_the_current_choice_and_suggestions_are_advisory():
    with store_with() as store:
        context = RuleContext.from_store(store.connection, end="2024-01-15")
        rows = selection.select(store.connection, context, "2024-01-15", "B")
    slot = pull_slot(rows)
    assert slot.current == "lat_pulldown"
    assert slot.suggested in {"pull_up", "lat_pulldown", "close_grip_pulldown"}
    assert slot.source == "python"
    assert len(slot.candidates) == 3
    assert "close_grip_pulldown" in {c.exercise_id for c in slot.candidates}


def test_can_do_false_excludes_a_candidate():
    with store_with() as store:
        repositories.append_exercise_suitability(
            store.connection, exercise_id="lat_pulldown", rated_on="2024-01-01",
            can_do=False, will_do=False, feels_bad=False,
        )
        context = RuleContext.from_store(store.connection, end="2024-01-15")
        rows = selection.select(store.connection, context, "2024-01-15", "B")
    slot = pull_slot(rows)
    assert "lat_pulldown" not in {c.exercise_id for c in slot.candidates}
    assert "pull_up" in {c.exercise_id for c in slot.candidates}


def test_an_llm_choice_must_come_from_the_candidate_list():
    with store_with() as store:
        context = RuleContext.from_store(store.connection, end="2024-01-15")
        rows = selection.select(
            store.connection, context, "2024-01-15", "B",
            chooser=lambda slot, candidates: ("pull_up", "model prefers the pull-up"),
        )
    slot = pull_slot(rows)
    assert slot.suggested == "pull_up"
    assert slot.source == "llm"

    with store_with() as store:
        context = RuleContext.from_store(store.connection, end="2024-01-15")
        rows = selection.select(
            store.connection, context, "2024-01-15", "B",
            chooser=lambda slot, candidates: ("invented_exercise", "bad answer"),
        )
    slot = pull_slot(rows)
    assert slot.suggested in {"pull_up", "lat_pulldown", "close_grip_pulldown"}
    assert slot.source == "python"


def test_day_a_has_catalogue_variants_even_though_the_template_has_one_exercise():
    with store_with() as store:
        context = RuleContext.from_store(store.connection, end="2024-01-15")
        rows = selection.select(store.connection, context, "2024-01-15", "A")
    squat = next(row for row in rows if row.slot_id == "squat_main")
    assert {"ssb_squat", "competition_squat"} <= {c.exercise_id for c in squat.candidates}
