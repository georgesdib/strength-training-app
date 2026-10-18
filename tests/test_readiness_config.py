"""Readiness derivation is configurable where it is a preference, fixed where it is a rule.

The mechanical pipeline (sentinels, coercion, the duplicate merge) is documented and tested in
test_readiness.py; this file covers the parts a user may change: which fields drive the fatigue
modifier, the threshold, and which merge strategy is accepted.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
import yaml

from conftest import make_readiness, make_training
from strength_coach.features.readiness import ReadinessConfig, ReadinessConfigError
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer

HISTORY = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
]


@contextmanager
def store_with(readiness_rows):
    training = make_training(HISTORY)
    readiness = make_readiness(readiness_rows)
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


# --- configuration ---------------------------------------------------------


def test_defaults_match_the_documented_behaviour(tmp_path):
    config = ReadinessConfig.load(tmp_path / "missing.yaml")
    assert config.modifier_fields == ("sleep", "energy")
    assert config.at_or_below == 2.0
    assert config.merge_strategy == "most_complete"


def test_a_file_can_widen_the_modifier_fields(tmp_path):
    path = tmp_path / "readiness.yaml"
    path.write_text(yaml.safe_dump({
        "merge": {"strategy": "most_complete", "tie_break": "latest"},
        "modifier": {"fields": ["sleep", "soreness"], "at_or_below": 3},
    }), encoding="utf-8")

    config = ReadinessConfig.load(path)
    assert config.modifier_fields == ("sleep", "soreness")
    assert config.at_or_below == 3.0


def test_unknown_field_is_rejected(tmp_path):
    path = tmp_path / "readiness.yaml"
    path.write_text(yaml.safe_dump({"modifier": {"fields": ["sleep", "vibes"]}}),
                    encoding="utf-8")
    with pytest.raises(ReadinessConfigError, match="unknown readiness fields"):
        ReadinessConfig.load(path)


def test_unimplemented_merge_strategy_is_rejected(tmp_path):
    path = tmp_path / "readiness.yaml"
    path.write_text(yaml.safe_dump({"merge": {"strategy": "average"}}), encoding="utf-8")
    with pytest.raises(ReadinessConfigError, match="not implemented"):
        ReadinessConfig.load(path)


def test_unimplemented_tie_break_is_rejected(tmp_path):
    path = tmp_path / "readiness.yaml"
    path.write_text(yaml.safe_dump({"merge": {"tie_break": "first"}}), encoding="utf-8")
    with pytest.raises(ReadinessConfigError, match="not implemented"):
        ReadinessConfig.load(path)


# --- the trigger -----------------------------------------------------------


def test_trigger_reads_only_configured_fields():
    default = ReadinessConfig()
    row = {"sleep": 4, "energy": 4, "soreness": 1}
    assert default.trigger(row) is None

    widened = ReadinessConfig(modifier_fields=("sleep", "soreness"))
    assert widened.trigger(row) == "soreness=1"


def test_a_missing_value_never_triggers():
    config = ReadinessConfig()
    assert config.trigger({"sleep": None, "energy": None}) is None
    assert config.trigger(None) is None


def test_the_threshold_is_inclusive():
    assert ReadinessConfig().trigger({"sleep": 2, "energy": 5}) == "sleep=2"
    assert ReadinessConfig().trigger({"sleep": 3, "energy": 5}) is None


# --- the engine ------------------------------------------------------------


def test_engine_uses_the_configured_fields():
    readiness = [{"Date": "2024-02-01", "Sleep": "4", "Energy": "4", "Soreness": "2"}]

    with store_with(readiness) as store:
        default = build_prescription(store.connection, for_date="2024-02-01", session_day="A")
        widened = build_prescription(
            store.connection,
            for_date="2024-02-01",
            session_day="A",
            readiness_config=ReadinessConfig(modifier_fields=("sleep", "soreness")),
        )

    assert default.fallback_level == "full"          # soreness is not a configured field
    assert widened.fallback_level == "fatigue_reduced"
    assert any("soreness=2" in warning for warning in widened.warnings)
    assert widened.notes["readiness_fields"] == ["sleep", "soreness"]
