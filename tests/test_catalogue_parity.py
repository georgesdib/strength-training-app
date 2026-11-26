"""Catalogue output must equal the online replacement resolver (WP1.4).

The earlier parity test compared the catalogue against build_item. The real contract is
resolve_replacement, because that is what an online substitution actually produces.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach.prescribe import build_prescription, catalogue, engine
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Back Extension", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "12"},
    {"Date": "2024-01-01", "Exercise": "Dumbbell Row", "Weight_Used": "30",
     "RIR": "2", "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Ab Wheel", "Weight_Used": "0",
     "RIR": "2", "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Box Jumps", "Weight_Used": "0",
     "RIR": "4", "Reps_Done": "4"},
]
TODAY = "2024-01-02"


@contextmanager
def store_with(rows=ROWS):
    training = make_training(rows)
    readiness = make_readiness([{"Date": TODAY}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store.connection
    finally:
        store.close()


def _plan_item(conn, session_type="squat"):
    prescription = build_prescription(conn, for_date=TODAY, session_type=session_type)
    return prescription, {item.exercise_id: item for item in prescription.items}


def _compare(conn, built, item) -> None:
    """The catalogue path and resolve_replacement must agree for this item's slot."""
    resolved, _, _ = engine.resolve_replacement(
        conn,
        for_date=TODAY,
        session_type="squat",
        exercise_id=item.exercise_id,
        sets=item.sets,
        reps_low=item.reps_low,
        reps_high=item.reps_high or item.reps_low,
        rir_target=item.rir_target,
        rest_s=item.rest_s,
        essential=item.essential,
        order_index=item.order_index,
    )
    expected = catalogue.prescription_from_catalogue(
        built,
        exercise_id=item.exercise_id,
        essential=item.essential,
        reps_low=item.reps_low,
        rir=item.rir_target,
        sets=item.sets,
    )
    assert expected["load_kg"] == resolved.load_kg, (
        item.exercise_id, expected["load_kg"], resolved.load_kg,
    )
    assert expected["sets"] == resolved.sets, (item.exercise_id, expected, resolved.sets)


def test_the_catalogue_matches_the_online_resolver_for_a_planned_lift():
    with store_with() as conn:
        built = catalogue.build_catalogue(conn, for_date=TODAY, session_type="squat")
        _, items = _plan_item(conn)
        _compare(conn, built, items["ssb_squat"])


def test_the_catalogue_matches_the_online_resolver_for_an_accessory():
    with store_with() as conn:
        built = catalogue.build_catalogue(conn, for_date=TODAY, session_type="squat")
        _, items = _plan_item(conn)
        if "dumbbell_row" not in items:
            pytest.skip("the template did not select a dumbbell row")
        _compare(conn, built, items["dumbbell_row"])


def test_the_catalogue_matches_the_online_resolver_for_bodyweight_and_power():
    with store_with() as conn:
        built = catalogue.build_catalogue(conn, for_date=TODAY, session_type="squat")
        _, items = _plan_item(conn)
        for exercise_id in ("ab_wheel", "box_jumps"):
            if exercise_id in items:
                _compare(conn, built, items[exercise_id])


def test_the_catalogue_matches_the_online_resolver_during_a_flare():
    with store_with() as conn:
        repositories.append_symptom(
            conn, logged_on=TODAY, timing="pre_session", region="low_back",
            level=2, settled_within_48h=None,
        )
        built = catalogue.build_catalogue(conn, for_date=TODAY, session_type="squat")
        _, items = _plan_item(conn)
        item = items["ssb_squat"]
        assert item.rir_target is not None and item.rir_target >= 3
        _compare(conn, built, item)


def test_the_catalogue_caps_the_direct_erector_dose_like_the_resolver():
    with store_with() as conn:
        repositories.append_symptom(
            conn, logged_on=TODAY, timing="pre_session", region="low_back",
            level=2, settled_within_48h=None,
        )
        built = catalogue.build_catalogue(conn, for_date=TODAY, session_type="squat")
        resolved, _, _ = engine.resolve_replacement(
            conn, for_date=TODAY, session_type="squat",
            exercise_id="back_extension", sets=5, reps_low=12, reps_high=12,
            rir_target=2, rest_s=120, essential=False, order_index=19,
        )
        expected = catalogue.prescription_from_catalogue(
            built, exercise_id="back_extension", essential=False,
            reps_low=12, rir=2, sets=5,
        )
        assert expected["load_kg"] == resolved.load_kg
        assert expected["sets"] == resolved.sets
        assert expected["prefill_source"] == "flare_dose"
