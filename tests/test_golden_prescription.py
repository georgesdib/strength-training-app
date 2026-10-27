"""Golden prescriptions: exact numbers for all four canonical session types."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import make_readiness, make_training

from strength_coach.prescribe import build_prescription, validate_references
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer

pytestmark = pytest.mark.golden

FIXTURE = Path(__file__).parent / "fixtures" / "golden_session_types.yaml"
HISTORY_DAYS = ("2024-01-04", "2024-01-11", "2024-01-18", "2024-01-25")
SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")


def history_rows_all_days() -> list[dict]:
    rows: list[dict] = []
    for day in HISTORY_DAYS:
        rows += [
            {"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
             "RIR": "2", "Reps_Done": "5"},
            # DEC-PROGRAMME-08: the bench+squat support is the competition squat, so the
            # fixture must hold its history or the session is not executable.
            {"Date": day, "Exercise": "Competition Squat", "Weight_Used": "105",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Competition Bench Press", "Weight_Used": "80",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Box Jumps", "Weight_Used": "0",
             "RIR": "4", "Reps_Done": "4"},
            {"Date": day, "Exercise": "Back Extension", "Weight_Used": "0",
             "RIR": "2", "Reps_Done": "12"},
            {"Date": day, "Exercise": "Ab Wheel", "Weight_Used": "0",
             "RIR": "2", "Reps_Done": "8"},
            {"Date": day, "Exercise": "Hanging Leg Raise", "Weight_Used": "0",
             "RIR": "2", "Reps_Done": "10"},
            {"Date": day, "Exercise": "Split Squat", "Weight_Used": "30",
             "RIR": "3", "Reps_Done": "8"},
            {"Date": day, "Exercise": "Dumbbell Row", "Weight_Used": "30",
             "RIR": "2", "Reps_Done": "10"},
            {"Date": day, "Exercise": "Overhead Press (seated)", "Weight_Used": "40",
             "RIR": "2", "Reps_Done": "8"},
            {"Date": day, "Exercise": "Single Leg DB RDL", "Weight_Used": "20",
             "RIR": "2", "Reps_Done": "8"},
            {"Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Sumo Deadlift", "Weight_Used": "120",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
             "RIR": "2", "Reps_Done": "5"},
        ]
    return rows


def build_store(readiness_rows):
    training = make_training(history_rows_all_days())
    readiness = make_readiness(readiness_rows)
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


@pytest.mark.parametrize("session_type", SESSION_TYPES)
def test_golden_session_types(session_type):
    expected = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))[session_type]
    with build_store([{}]) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-02-01", session_type=session_type
        )
        context = RuleContext.from_store(store.connection, end="2024-02-01")
        assert validate_references(prescription, context, store.connection) == []

    assert prescription.session_type == session_type
    assert prescription.executable is expected["executable"]
    assert prescription.fallback_level == expected["fallback_level"]
    want = expected["items"]
    assert len(prescription.items) == len(want)
    for item, target in zip(prescription.items, want, strict=True):
        assert item.exercise_id == target["exercise_id"]
        assert item.sets == target["sets"]
        assert item.reps_low == target["reps_low"]
        assert item.reps_high == target["reps_high"]
        assert item.load_kg == pytest.approx(target["load_kg"], abs=1e-9)
        assert item.load_basis == target["load_basis"]
        assert item.rir_target == target["rir_target"]
        assert item.rest_s == target["rest_s"]
        assert item.essential is target["essential"]


def test_golden_fatigue_reduction():
    with build_store([{"Date": "2024-02-01", "Sleep": "2"}]) as store:
        prescription = build_prescription(
            store.connection, for_date="2024-02-01", session_type="hinge"
        )
    assert prescription.fallback_level == "fatigue_reduced"
    assert any(
        "MOD-FAT-001" in item.rationale_refs
        for item in prescription.items if item.load_kg is not None
    )
