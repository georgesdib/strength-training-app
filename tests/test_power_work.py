"""Power work is quality-limited, not RIR-limited (DEC-POWER-02).

The template, the item, the API payload and the analytics must all agree that a box jump has
no RIR target. The stop rule is the operative instruction and is stored with the item.
"""

from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import pytest

from conftest import make_readiness, make_training
from strength_coach.agents import proposal
from strength_coach.features import derived
from strength_coach.features.deload import DeloadDecision
from strength_coach.prescribe import build_prescription, templates
from strength_coach.prescribe.persistence import _rows
from strength_coach.rules import load_document
from strength_coach.store import db, importer
from strength_coach.web import server

SQUAT_ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "5",
     "RIR": "2", "Reps_Done": "12"},
    {"Date": "2024-01-01", "Exercise": "Dumbbell Row", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Ab Wheel", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Box Jumps", "Weight_Used": "0",
     "RIR": "4", "Reps_Done": "4"},
]


@contextmanager
def store_with(rows, *, readiness_rows=None):
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


def item(prescription, exercise_id):
    return next(i for i in prescription.items if i.exercise_id == exercise_id)


def test_a_power_item_has_no_rir_and_stores_the_stop_rule():
    with store_with(SQUAT_ROWS) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="squat",
        )

    box = item(prescription, "box_jump")
    assert box.effort_model == "quality"
    assert box.rir_target is None
    assert box.load_kg == 0.0
    assert box.quality_stop and "quality" in box.quality_stop.lower()
    assert any("power work" in warning for warning in prescription.warnings)

    squat = item(prescription, "ssb_squat")
    assert squat.effort_model == "rir"
    assert squat.rir_target == 2
    assert squat.quality_stop is None


def test_the_api_payload_carries_the_quality_fields_and_a_null_rir():
    with store_with(SQUAT_ROWS) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="squat",
        )
    payload = server._item_dict(item(prescription, "box_jump"))
    assert payload["effort_model"] == "quality"
    assert payload["rir_target"] is None
    assert payload["quality_stop"]
    row = _rows({"items": [payload]})[0]
    assert row["effort_model"] == "quality"
    assert row["quality_stop"] == payload["quality_stop"]


def test_the_template_rejects_a_power_rir_or_a_missing_stop_rule():
    base = {
        "id": "power", "exercise": "box_jump", "sets": 3,
        "reps": {"low": 3, "high": 5}, "rest_s": 120, "power": True,
        "load_source": "bodyweight",
    }
    with pytest.raises(templates.TemplateError, match="must not carry an RIR"):
        templates._parse_slot({**base, "rir": {"low": 4, "high": 5}}, "squat")
    with pytest.raises(templates.TemplateError, match="quality_stop"):
        templates._parse_slot(base, "squat")
    with pytest.raises(templates.TemplateError, match="only for power work"):
        templates._parse_slot(
            {**base, "power": False, "rir": {"low": 2, "high": 3},
             "quality_stop": "stop"},
            "squat",
        )


def test_the_power_rir_is_excluded_from_the_effort_window():
    frame = pd.DataFrame([
        {"exercise_id": "box_jump", "rir": 4},
        {"exercise_id": "ssb_squat", "rir": 2},
    ])
    out = derived.add_effort_fields(frame)
    assert pd.isna(out.loc[0, "in_rir_window"])
    assert pd.isna(out.loc[0, "rir_target_low"])
    assert bool(out.loc[1, "in_rir_window"])


def test_readiness_and_a_deload_do_not_try_to_change_a_quality_rir():
    poor = [{"Date": "2024-01-20", "Sleep": "1", "Energy": "1", "Mood": "1",
             "Soreness": "1", "Stress": "1"}]
    with store_with(SQUAT_ROWS, readiness_rows=poor) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-20", session_type="squat",
            deload_decision=DeloadDecision(reason="test deload", trigger="test"),
        )
    box = item(prescription, "box_jump")
    assert box.rir_target is None
    assert box.effort_model == "quality"
    assert prescription.executable is True


def test_the_proposal_offers_only_keep_for_quality_work():
    with store_with(SQUAT_ROWS) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-01-08", session_type="squat",
        )
    document = load_document()
    menus = proposal.menu(prescription, document)
    assert list(menus["box_jump"]) == ["keep"]
    from strength_coach.prescribe import schemes
    assert proposal.scheme_options(prescription, schemes.Schemes.load())["box_jump"] == []
    prompt = proposal.prompt_for(prescription, allowed={}, options=menus)
    assert "quality stop" in prompt
    assert "RIR None" not in prompt
