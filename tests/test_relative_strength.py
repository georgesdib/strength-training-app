"""Configured relative-strength ratio tests."""

from __future__ import annotations

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import relative_strength
from strength_coach.store import db, importer
from strength_coach.utils import exercises


def _store(front=("100", "105", "110"), back=("140", "145", "150")):
    rows = []
    dates = ("2024-01-01", "2024-01-08", "2024-01-15")
    for day, f_load, b_load in zip(dates, front, back, strict=False):
        rows.append({"Date": day, "Exercise": "Front Squat", "Weight_Used": f_load,
                     "RIR": "2", "Reps_Done": "5"})
        rows.append({"Date": day, "Exercise": "Competition Squat", "Weight_Used": b_load,
                     "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{"Date": day} for day in dates])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_ratio_uses_latest_raw_observations_and_reports_dates():
    relationship = relative_strength.Relationship(
        id="test", label="Front / competition", numerator="front_squat",
        denominator="competition_squat", relationship_type="variant_to_main",
        max_gap_days=14, max_age_days=42, min_observations=2, notes="test",
    )
    with _store() as store:
        ratio = relative_strength.current_ratio(
            store.connection, relationship, "2024-01-20"
        )

    assert isinstance(ratio, relative_strength.Ratio)
    assert ratio.status == "available"
    assert ratio.numerator_date == "2024-01-15"
    assert ratio.denominator_date == "2024-01-15"
    assert ratio.gap_days == 0
    assert ratio.numerator_observations == 3
    assert ratio.denominator_observations == 3
    assert ratio.ratio_pct == pytest.approx(100 * (110 * (1 + 7 / 30)) / (150 * (1 + 7 / 30)))


def test_ratio_with_one_side_sparse_is_insufficient_history():
    relationship = relative_strength.Relationship(
        id="test", label="Front / competition", numerator="front_squat",
        denominator="competition_squat", relationship_type="variant_to_main",
        max_gap_days=14, max_age_days=42, min_observations=2, notes="test",
    )
    with _store(front=("100",), back=("140", "145", "150")) as store:
        ratio = relative_strength.current_ratio(
            store.connection, relationship, "2024-01-20"
        )
    assert isinstance(ratio, dict)
    assert ratio["status"] == "insufficient_history"


def test_ratio_trend_uses_history_before_the_range_and_keeps_invalid_statuses():
    relationship = relative_strength.Relationship(
        id="test", label="Front / competition", numerator="front_squat",
        denominator="competition_squat", relationship_type="variant_to_main",
        max_gap_days=14, max_age_days=42, min_observations=2, notes="test",
    )
    with _store() as store:
        trend = relative_strength.ratio_trend(
            store.connection, relationship, "2024-01-15", "2024-01-20"
        )
        sparse = relative_strength.ratio_trend(
            store.connection, relationship, "2024-01-01", "2024-01-20"
        )

    assert trend[0]["status"] == "available"
    assert trend[0]["denominator_date"] == "2024-01-15"
    assert trend[0]["denominator_observations"] == 3
    assert sparse[0]["status"] == "insufficient_history"
    assert sparse[0]["ratio_pct"] is None


def test_ratio_trend_counts_only_recent_observations_for_the_minimum():
    stale_relationship = relative_strength.Relationship(
        id="test", label="Front / competition", numerator="front_squat",
        denominator="competition_squat", relationship_type="variant_to_main",
        max_gap_days=10, max_age_days=5, min_observations=2, notes="test",
    )
    recent_relationship = relative_strength.Relationship(
        id="test", label="Front / competition", numerator="front_squat",
        denominator="competition_squat", relationship_type="variant_to_main",
        max_gap_days=10, max_age_days=10, min_observations=2, notes="test",
    )
    with _store() as store:
        stale = relative_strength.ratio_trend(
            store.connection, stale_relationship, "2024-01-15", "2024-01-15"
        )
        recent = relative_strength.ratio_trend(
            store.connection, recent_relationship, "2024-01-15", "2024-01-15"
        )

    assert stale[0]["status"] == "insufficient_history"
    assert stale[0]["ratio_pct"] is None
    assert stale[0]["numerator_observations"] == 1
    assert stale[0]["denominator_observations"] == 1
    assert recent[0]["status"] == "available"
    assert recent[0]["ratio_pct"] is not None
    assert recent[0]["numerator_observations"] == 2
    assert recent[0]["denominator_observations"] == 2


def test_config_relationships_validate_against_taxonomy():
    relationships = relative_strength.load_relationships()
    issues = relative_strength.validate_relationships(
        exercises.taxonomy(), relationships
    )
    assert issues == []
