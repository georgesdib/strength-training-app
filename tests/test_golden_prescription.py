"""Golden prescription: the exact numbers, locked.

Phase 5's acceptance asked for a golden test alongside the executability criteria. This is it:
a fixed synthetic history produces the exact prescription in `fixtures/golden_day_b.yaml`,
including the fatigue-reduced variant. Any unintended change to e1RM inversion, rounding,
rep targets or the modifier fails here, loudly, with a diff.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import make_readiness, make_training
from strength_coach.prescribe import build_prescription, validate_references
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer

pytestmark = pytest.mark.golden

FIXTURE = Path(__file__).parent / "fixtures" / "golden_day_b.yaml"
DAY_FIXTURES = {
    "A": Path(__file__).parent / "fixtures" / "golden_day_a.yaml",
    "C": Path(__file__).parent / "fixtures" / "golden_day_c.yaml",
}
HISTORY_DAYS = ("2024-01-04", "2024-01-11", "2024-01-18", "2024-01-25")


def history_rows() -> list[dict]:
    rows: list[dict] = []
    for day in HISTORY_DAYS:
        rows += [
            {"Date": day, "Exercise": "Competition Deadlift", "Weight_Used": "150",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Lateral Raise", "Weight_Used": "12.5",
             "RIR": "2", "Reps_Done": "10"},
            {"Date": day, "Exercise": "Split Squat", "Weight_Used": "30",
             "RIR": "3", "Reps_Done": "8"},
        ]
    return rows


def history_rows_all_days() -> list[dict]:
    """A history that supports A, B and C: every lift the templates reference."""
    rows: list[dict] = []
    for day in HISTORY_DAYS:
        rows += [
            {"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Competition Bench Press", "Weight_Used": "80",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Back Extension", "Weight_Used": "0",
             "RIR": "2", "Reps_Done": "12"},
            {"Date": day, "Exercise": "Lateral Raise", "Weight_Used": "12.5",
             "RIR": "2", "Reps_Done": "10"},
            {"Date": day, "Exercise": "Split Squat", "Weight_Used": "30",
             "RIR": "3", "Reps_Done": "8"},
        ]
    return rows


@pytest.mark.parametrize("day", ["A", "C"])
def test_golden_day_a_and_c(day):
    expected = yaml.safe_load(DAY_FIXTURES[day].read_text(encoding="utf-8"))

    training = make_training(history_rows_all_days())
    readiness = make_readiness([{}])
    with db.Store(":memory:") as store:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        prescription = build_prescription(
            store.connection, for_date=expected["for_date"], session_day=day
        )
        context = RuleContext.from_store(store.connection, end=expected["for_date"])
        assert validate_references(prescription, context, store.connection) == []

    assert prescription.session_day == day
    assert prescription.executable, prescription.issues
    assert prescription.fallback_level == expected["expected"]["fallback_level"]

    want = expected["expected"]["items"]
    assert len(prescription.items) == len(want)
    for item, target in zip(prescription.items, want, strict=True):
        assert item.exercise_id == target["exercise_id"]
        assert item.sets == target["sets"]
        assert item.load_kg == pytest.approx(target["load_kg"], abs=1e-9)
        assert item.load_basis == target["load_basis"]
        assert item.rir_target == target["rir_target"]
        assert item.rest_s == target["rest_s"]
        assert item.essential is target["essential"]
        assert item.rationale_refs[0] == target["rule"]

    # The A/C templates provide the rep range the double-progression rule was missing.
    assert not any("rep_range.back_extension" in w for w in prescription.warnings)
    # Bodyweight erector work must not be "progressed" into a 0.5 kg prescription.
    erector = next(i for i in prescription.items if i.exercise_id == "back_extension")
    assert erector.load_kg == 0.0
    assert any("bodyweight" in w for w in prescription.warnings)


def build_store(readiness_rows):
    training = make_training(history_rows())
    readiness = make_readiness(readiness_rows)
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_golden_day_b_prescription():
    expected = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    with build_store([{}]) as store:
        prescription = build_prescription(store.connection, for_date=expected["for_date"])
        context = RuleContext.from_store(store.connection, end=expected["for_date"])
        assert validate_references(prescription, context, store.connection) == []

        assert prescription.executable is expected["expected"]["executable"]
        assert prescription.fallback_level == expected["expected"]["fallback_level"]
        assert prescription.session_day == expected["session_day"]

        want = expected["expected"]["items"]
        assert len(prescription.items) == len(want)
        for item, target in zip(prescription.items, want, strict=True):
            assert item.exercise_id == target["exercise_id"]
            assert item.sets == target["sets"]
            assert item.reps_low == target["reps_low"]
            assert item.reps_high == target["reps_high"]
            assert item.load_kg == pytest.approx(target["load_kg"], abs=1e-9)
            assert item.rir_target == target["rir_target"]
            assert item.rest_s == target["rest_s"]
            assert item.essential is target["essential"]
            assert item.rationale_refs[0] == target["rule"]


def test_golden_fatigue_reduction():
    expected = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))["fatigue"]
    with build_store([{"Date": "2024-02-01", "Sleep": "2"}]) as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01")

    assert prescription.fallback_level == expected["fallback_level"]
    loads = {item.exercise_id: item.load_kg for item in prescription.items}
    for exercise_id, load in expected["loads"].items():
        assert loads[exercise_id] == pytest.approx(load, abs=1e-9)
    # The modifier must leave a citation trail on every item it touched.
    for item in prescription.items:
        assert "MOD-FAT-001" in item.rationale_refs
