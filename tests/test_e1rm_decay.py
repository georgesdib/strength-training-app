"""Old e1RM estimates and measured overrides decay after a grace period."""

from __future__ import annotations

import os

import pytest
import yaml
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
            store.connection, for_date="2024-03-01", session_type="squat"
        )
    squat = next(item for item in prescription.items if item.exercise_id == "ssb_squat")
    assert "MOD-E1RM-DECAY-001" in squat.rationale_refs
    assert any("e1RM is old" in warning for warning in prescription.warnings)

def test_decay_config_is_parsed_once_per_file_stamp(tmp_path, monkeypatch):
    """The decay factor is asked for every prescribed item; the file must be read once."""
    source = tmp_path / "decay.yaml"
    source.write_text("grace_days: 10\nweekly_decay: 0.02\n", encoding="utf-8")
    e1rm_decay._load_stamped.cache_clear()
    parses: list[str] = []
    real = yaml.safe_load

    def counting(text):
        parses.append(text)
        return real(text)

    monkeypatch.setattr(e1rm_decay.yaml, "safe_load", counting)
    first = e1rm_decay.DecayConfig.load(source)
    second = e1rm_decay.DecayConfig.load(source)

    assert parses == [source.read_text(encoding="utf-8")]
    assert first is second
    assert first.grace_days == 10
    assert first.weekly_decay == pytest.approx(0.02)
    assert first.source_path == source


def test_decay_config_edit_invalidates_the_cache(tmp_path):
    """A stamp change must never serve the previous values."""
    source = tmp_path / "decay.yaml"
    source.write_text("grace_days: 10\n", encoding="utf-8")
    e1rm_decay._load_stamped.cache_clear()
    assert e1rm_decay.DecayConfig.load(source).grace_days == 10

    source.write_text("grace_days: 30\n", encoding="utf-8")
    before = source.stat()
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))

    edited = e1rm_decay.DecayConfig.load(source)
    assert edited.grace_days == 30
    assert edited is e1rm_decay.DecayConfig.load(source)
