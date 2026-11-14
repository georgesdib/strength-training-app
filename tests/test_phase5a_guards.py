"""Phase 5A guards: AFC work must not move the validation instrument.

These are the mechanical checks `DEC-AFC-02` requires before AFC code merges. They are
deliberately cheap: a golden hash of the prospective report, a hash of the locked configuration
inventory, and a source check that prospective does not start consuming `workout.summary()`.

A failure here means the Phase 5A input moved. Fix the change, not the constant, unless the
2027-01-22 gate has been recorded and the commit says why the instrument changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import config_inventory, prospective
from strength_coach.store import db, importer, repositories

ROOT = Path(__file__).resolve().parents[1]

# Captured from the last commit before AFC implementation (d599706, 2026-11-13).
PROSPECTIVE_REPORT_SHA256 = (
    "46280bd94cabdf3f342e3f067f6973ff37e4a0b76841e3d9897dfcee5f7a872f"
)
LOCKED_CONFIG_REVISION = (
    "5c6b5885c980ef00df1273a4ebb8ed697900dfd002c3080116e5befc2e805923"
)
LOCAL_OVERRIDES = sorted((ROOT / "config").glob("*.local.yaml"))


def _store():
    dates = [
        "2023-12-11", "2023-12-18", "2023-12-25", "2024-01-01",
        "2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29",
    ]
    loads = ["100", "102", "104", "106", "108", "110", "112", "114"]
    rows = [
        {"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": load,
         "RIR": "2", "Reps_Done": "5"}
        for day, load in zip(dates, loads, strict=True)
    ]
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_athlete_profile(
        store.connection, effective_from="2023-12-01",
        sessions_per_week_target=3,
    )
    return store


def test_prospective_report_is_unchanged_since_the_afc_baseline():
    store = _store()
    try:
        report = prospective.report(store.connection, weeks=8, on_date="2024-03-01")
    finally:
        store.close()
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == PROSPECTIVE_REPORT_SHA256


@pytest.mark.skipif(
    bool(LOCAL_OVERRIDES),
    reason="local config overlay present; the Phase 5A baseline is not comparable",
)
def test_locked_configuration_revision_is_unchanged():
    payload = config_inventory.build_inventory(today="2026-11-13")
    assert payload["phase"]["locked"] is True
    assert payload["revision"] == LOCKED_CONFIG_REVISION


def test_prospective_does_not_consume_the_workout_summary():
    text = (ROOT / "strength_coach" / "features" / "prospective.py").read_text(
        encoding="utf-8"
    )
    assert "workout.summary" not in text
    assert "workout.summary(" not in text
