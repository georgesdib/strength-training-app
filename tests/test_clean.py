"""Cleaning: sentinels, load basis, units and quarantine.

Each test pins one documented decision. If one of these changes, a data-quality decision has
changed, and the corresponding docs/DATA-QUALITY.md entry must change with it.
"""

import pandas as pd
import pytest

from conftest import make_readiness, make_training
from strength_coach.domain import load as load_mod
from strength_coach.ingest import clean


def clean_one(row: dict, readiness: dict | None = None):
    result = clean.build_clean_sets(
        make_training([row]), make_readiness([readiness or {}])
    )
    return result, result.sets.iloc[0]


# --- DEC-RIR-01: RIR 6 is a warm-up ---------------------------------------
def test_warmup_marker_makes_a_non_working_set():
    _, row = clean_one({"RIR": "6"})
    assert row["rir_class"] == "warmup"
    assert row["is_working_set"] == False  # noqa: E712 - numpy bool
    assert "WARMUP" in row["flags"]


def test_warmup_keeps_its_value():
    """Visible, not erased: the warm-up share is itself a coaching signal."""
    _, row = clean_one({"RIR": "6"})
    assert row["rir"] == 6


def test_effort_set_is_working():
    _, row = clean_one({"RIR": "2"})
    assert row["is_working_set"]
    assert "WARMUP" not in row["flags"]


# --- DQ-BW-01 + DEC-LOAD-02: bodyweight semantics -------------------------
def test_bodyweight_captured_total_has_zero_added_load():
    _, row = clean_one(
        {"Exercise": "Pull-ups (wide grip)", "Weight_Used": "79.8", "RIR": "2"},
        {"Weight": "80.0"},
    )
    assert row["load_basis"] == "bodyweight_total"
    assert row["external_load_kg"] == 0.0
    # DEC-LOAD-02: progression acts on ADDED load, so this is 0, not 79.8.
    assert row["progression_load_kg"] == 0.0
    assert row["total_load_kg"] == pytest.approx(79.8)


def test_added_plate_is_recognised():
    _, row = clean_one(
        {"Exercise": "Pull-ups (wide grip)", "Weight_Used": "5.0", "RIR": "2"},
        {"Weight": "80.0"},
    )
    assert row["load_basis"] == "added"
    assert row["progression_load_kg"] == 5.0
    assert row["total_load_kg"] == pytest.approx(85.0)


def test_unweighted_bodyweight_is_zero_added():
    _, row = clean_one(
        {"Exercise": "Ab Wheel", "Weight_Used": "0.0", "RIR": "2"},
        {"Weight": "80.0"},
    )
    assert row["load_basis"] == "bodyweight_total"
    assert row["external_load_kg"] == 0.0


def test_bodyweight_zero_is_a_sentinel_not_a_bodyweight():
    """A recorded 0 kg bodyweight would make every ratio infinite."""
    _, row = clean_one(
        {"Exercise": "Pull-ups (wide grip)", "Weight_Used": "79.8"},
        {"Weight": "0.0"},
    )
    assert row["load_basis"] == "unknown"


# --- DQ-REPS-01: seconds vs reps ------------------------------------------
def test_isometric_hold_logs_seconds_and_has_no_tonnage():
    _, row = clean_one(
        {"Exercise": "Chinese Plank", "Weight_Used": "5.0", "Reps_Done": "90", "RIR": "2"}
    )
    assert row["reps_unit"] == "seconds"
    assert "SECONDS_NOT_REPS" in row["flags"]
    assert pd.isna(row["tonnage_kg"])


def test_rep_typo_is_flagged_and_not_counted():
    _, row = clean_one(
        {"Exercise": "Pushups (chest emphasis)", "Weight_Used": "0", "Reps_Done": "1015"}
    )
    assert "REPS_TYPO" in row["flags"]
    assert pd.isna(row["tonnage_kg"])


def test_normal_set_has_tonnage():
    _, row = clean_one({"Weight_Used": "100", "Reps_Done": "5", "RIR": "2"})
    assert row["tonnage_kg"] == pytest.approx(500.0)


# --- quarantine ------------------------------------------------------------
def test_null_date_is_quarantined_not_dropped():
    result = clean.build_clean_sets(
        make_training([{"Date": "(null)"}, {"Date": "2024-01-02"}]), make_readiness([{}])
    )
    assert result.n_quarantined == 1
    assert result.quarantine.iloc[0]["quarantine_reason"] == "null_date"
    assert result.n_sets == 1
    assert result.issues["rows_quarantined"] == 1


def test_unknown_exercise_is_quarantined():
    result = clean.build_clean_sets(
        make_training([{"Exercise": "Zercher Thingamajig"}]), make_readiness([{}])
    )
    assert result.quarantine.iloc[0]["quarantine_reason"] == "unknown_exercise"


def test_source_row_is_preserved_for_traceability():
    result = clean.build_clean_sets(
        make_training([{"Date": "(null)"}, {"Date": "2024-01-02"}]), make_readiness([{}])
    )
    assert result.sets.iloc[0]["source_row"] == 2


# --- progression load ------------------------------------------------------
def test_progression_load_for_barbell_is_the_load():
    resolved = load_mod.resolve_load_basis(100.0, bodyweight_kg=80.0, is_bodyweight_type=False)
    assert load_mod.progression_load(resolved, is_bodyweight_type=False) == 100.0


def test_progression_load_refuses_unknown_basis():
    resolved = load_mod.resolve_load_basis(95.0, bodyweight_kg=None, is_bodyweight_type=True)
    assert load_mod.progression_load(resolved, is_bodyweight_type=True) is None
