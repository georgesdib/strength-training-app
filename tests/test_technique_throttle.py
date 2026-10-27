"""MOD-TECH-001: a user-declared technique throttle, one session, no stored state."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import prescription_provenance
from strength_coach.prescribe import build_prescription
from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.prescribe.technique_throttle import (
    TechniqueThrottleConfig,
    apply,
)
from strength_coach.store import db, importer

TODAY = dt.date.today().isoformat()
ROWS = [
    {"Date": TODAY, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": TODAY, "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


@contextmanager
def store_with(rows=ROWS):
    training = make_training(rows)
    readiness = make_readiness([{"Date": rows[0]["Date"]}])
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


def item(index, exercise, *, essential=True, load=100.0, rir=2,
         increment=2.5, load_basis="external", load_factor=1.0):
    return PrescriptionItem(
        order_index=index, exercise_id=exercise, sets=5, reps_low=5, reps_high=5,
        load_kg=load, load_basis=load_basis, rounding_increment_kg=increment,
        rir_target=rir, rest_s=180, essential=essential, load_factor=load_factor,
    )


PATTERNS = {
    "ssb_squat": "squat",
    "competition_bench_press": "horizontal_push",
    "leg_press": "squat",
}


def by_id(result, exercise_id):
    return next(i for i in result["items"] if i.exercise_id == exercise_id)


def test_load_is_capped_and_rir_floored():
    before = (item(0, "ssb_squat"),)
    result = apply(before, PATTERNS)
    after = by_id(result, "ssb_squat")
    assert result["applied"] is True
    assert result["status"] == "applied"
    assert after.load_kg == 90.0
    assert after.rir_target == 3
    assert after.load_factor == pytest.approx(0.90)
    assert "MOD-TECH-001" in after.rationale_refs


def test_rir_floor_never_lowers_a_target_already_above_it():
    result = apply((item(0, "ssb_squat", rir=4),), PATTERNS)
    after = by_id(result, "ssb_squat")
    assert after.rir_target == 4
    assert after.load_kg == 90.0


def test_an_existing_reduction_is_not_multiplied_on():
    # Readiness already took this item to 0.85; the throttle compares, never multiplies, so
    # the load is unchanged and only the RIR floor can still apply.
    before = (item(0, "ssb_squat", load=85.0, load_factor=0.85),)
    result = apply(before, PATTERNS)
    after = by_id(result, "ssb_squat")
    assert after.load_kg == 85.0
    assert after.load_factor == pytest.approx(0.85)
    assert after.rir_target == 3
    assert "load capped" not in result["reason"]


def test_naming_a_pattern_leaves_other_patterns_alone():
    before = (item(0, "ssb_squat"), item(1, "competition_bench_press", load=80.0))
    result = apply(before, PATTERNS, pattern="squat")
    assert by_id(result, "ssb_squat").load_kg == 90.0
    bench = by_id(result, "competition_bench_press")
    assert bench.load_kg == 80.0
    assert bench.rir_target == 2
    assert "MOD-TECH-001" not in bench.rationale_refs


def test_default_scope_is_main_lifts_only():
    before = (item(0, "ssb_squat"), item(1, "leg_press", essential=False, load=200.0))
    result = apply(before, PATTERNS)
    assert by_id(result, "ssb_squat").load_kg == 90.0
    accessory = by_id(result, "leg_press")
    assert accessory.load_kg == 200.0
    assert accessory.rir_target == 2


def test_bodyweight_work_keeps_its_load_and_takes_the_rir_floor():
    before = (item(0, "ssb_squat", load=80.0, load_basis="bodyweight_total"),)
    result = apply(before, PATTERNS)
    after = by_id(result, "ssb_squat")
    assert after.load_kg == 80.0
    assert after.rir_target == 3
    assert result["load_not_reducible"] == ["ssb_squat"]


def test_unmatched_pattern_is_reported_not_applied():
    before = (item(0, "ssb_squat"),)
    result = apply(before, PATTERNS, pattern="vertical_pull")
    assert result["applied"] is False
    assert result["status"] == "no_match"
    assert by_id(result, "ssb_squat").load_kg == 100.0


def test_config_rejects_an_impossible_rir_floor(tmp_path):
    source = tmp_path / "throttle.yaml"
    source.write_text("load_multiplier: 0.9\nrir_floor: 5\nrir_cap: 3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        TechniqueThrottleConfig.load(source)


def test_engine_applies_the_throttle_and_records_provenance():
    with store_with() as store:
        plain = build_prescription(
            store.connection, for_date=TODAY, session_type="squat"
        )
        throttled = build_prescription(
            store.connection, for_date=TODAY, session_type="squat",
            technique_throttle=True,
        )

    # The fixture has one lift with no working history, so the plan is not executable; the
    # throttle must neither add nor remove an issue.
    assert throttled.issues == plain.issues
    changed = [i.exercise_id for i in throttled.items
               if "MOD-TECH-001" in i.rationale_refs]
    assert "ssb_squat" in changed
    assert throttled.notes["technique_throttle"]["applied"] is True
    for before, after in zip(plain.items, throttled.items, strict=False):
        if after.exercise_id in changed:
            assert after.rir_target >= 3
            assert after.load_kg <= before.load_kg * 0.90 + 1e-9
            assert after.rest_s == before.rest_s
        else:
            assert after.load_kg == before.load_kg
            assert after.rir_target == before.rir_target
    keys = [key for key, _ in prescription_provenance.extract(throttled)]
    assert "MOD-TECH-001" in keys


def test_engine_without_the_flag_is_unchanged():
    with store_with() as store:
        prescription = build_prescription(
            store.connection, for_date=TODAY, session_type="squat"
        )
    assert prescription.notes["technique_throttle"] is None
    assert all("MOD-TECH-001" not in i.rationale_refs for i in prescription.items)


def test_throttle_does_not_carry_into_the_next_session():
    # Nothing is stored, so the next build without the flag is a normal prescription.
    with store_with() as store:
        first = build_prescription(
            store.connection, for_date=TODAY, session_type="squat",
            technique_throttle=True,
        )
        second = build_prescription(
            store.connection, for_date=TODAY, session_type="squat"
        )
    assert first.notes["technique_throttle"]["applied"] is True
    assert second.notes["technique_throttle"] is None
    assert all("MOD-TECH-001" not in i.rationale_refs for i in second.items)
