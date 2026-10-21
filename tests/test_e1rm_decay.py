"""Old e1RM estimates and measured overrides decay after a grace period."""

from __future__ import annotations

import pytest

from conftest import make_readiness, make_training
from strength_coach.features import e1rm_decay
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    # A recent session of another lift keeps the continuity gap small, isolating the
    # e1RM-age decay from MOD-GAP-001's load reduction.
    {"Date": "2024-02-28", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


def test_grace_and_bounded_linear_decay():
    cfg = e1rm_decay.DecayConfig.load()
    assert e1rm_decay.factor(0, cfg) == 1.0
    assert e1rm_decay.factor(cfg.grace_days, cfg) == 1.0
    assert e1rm_decay.factor(cfg.grace_days + 7, cfg) == pytest.approx(0.99)
    assert e1rm_decay.factor(400, cfg) == pytest.approx(0.90)


def test_an_old_set_is_decayed_in_the_prescription():
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    with db.Store(":memory:") as store:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        prescription = build_prescription(
            store.connection, for_date="2024-03-01", session_day="A"
        )
    squat = next(item for item in prescription.items if item.exercise_id == "ssb_squat")
    assert "MOD-E1RM-DECAY-001" in squat.rationale_refs
    assert any("e1RM is old" in warning for warning in prescription.warnings)
