"""Configured relative-strength ratio tests."""

from __future__ import annotations

import shutil

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


def test_append_relationship_validates_and_reloads(tmp_path):
    source = relative_strength.paths.config_dir("strength-relationships.v1.yaml")
    target = tmp_path / "strength-relationships.v1.yaml"
    shutil.copyfile(source, target)
    relationship = relative_strength.Relationship(
        id="front_squat_to_bench_press",
        label="Front squat / bench press",
        numerator="front_squat",
        denominator="bench_press",
        relationship_type="variant_to_main",
        max_gap_days=14,
        max_age_days=42,
        min_observations=2,
        notes="Descriptive only.",
    )
    result = relative_strength.append_relationship(relationship, path=target)
    assert len(result) == len(relative_strength.load_relationships(target))
    assert relative_strength.validate_relationships(exercises.taxonomy(), result) == []
    with pytest.raises(ValueError, match="duplicate"):
        relative_strength.append_relationship(relationship, path=target)


def test_append_relationship_rejects_non_e1rm_exercise(tmp_path):
    target = tmp_path / "strength-relationships.v1.yaml"
    shutil.copyfile(relative_strength.paths.config_dir("strength-relationships.v1.yaml"), target)
    relationship = relative_strength.Relationship(
        id="plank_to_squat", label="Plank / squat", numerator="plank",
        denominator="competition_squat", relationship_type="accessory_to_main",
        max_gap_days=14, max_age_days=42, min_observations=2, notes="test",
    )
    with pytest.raises(ValueError, match="does not support an e1RM"):
        relative_strength.append_relationship(relationship, path=target)


def test_relationship_overlay_edit_add_delete_reset(tmp_path):
    source = relative_strength.paths.config_dir("strength-relationships.v1.yaml")
    target = tmp_path / "strength-relationships.v1.yaml"
    shutil.copyfile(source, target)
    canonical_before = target.read_bytes()
    original = relative_strength.load_relationships(target)
    first, second = original[0], original[1]
    revision = relative_strength.relationship_config_revision(target)

    added = relative_strength.Relationship(
        id="front_squat_to_bench_press",
        label="Front squat / bench press",
        numerator="front_squat",
        denominator="bench_press",
        relationship_type="variant_to_main",
        max_gap_days=10,
        max_age_days=30,
        min_observations=2,
        notes="Local addition.",
    )
    relative_strength.append_relationship(added, path=target)
    updated = relative_strength.Relationship(
        **{**first.__dict__, "label": "Edited front squat ratio", "max_gap_days": 9}
    )
    relative_strength.update_relationship(updated, path=target)
    relative_strength.delete_relationship(second.id, path=target)

    effective = {
        item.id: (item, kind)
        for item, _source, kind in relative_strength.load_relationships_with_sources(target)
    }
    assert target.read_bytes() == canonical_before
    assert effective[first.id][0].label == "Edited front squat ratio"
    assert effective[first.id][0].max_gap_days == 9
    assert effective[first.id][1] == "local_override"
    assert second.id not in effective
    assert added.id in effective
    assert effective[added.id][1] == "local_override"
    assert relative_strength.relationship_config_revision(target) != revision

    relative_strength.reset_relationship(first.id, path=target)
    relative_strength.reset_relationship(second.id, path=target)
    relative_strength.reset_relationship(added.id, path=target)
    restored = {item.id: item for item in relative_strength.load_relationships(target)}
    assert restored[first.id].label == first.label
    assert second.id in restored
    assert added.id not in restored


def test_relationship_update_rejects_membership_change(tmp_path):
    source = relative_strength.paths.config_dir("strength-relationships.v1.yaml")
    target = tmp_path / "strength-relationships.v1.yaml"
    shutil.copyfile(source, target)
    original = relative_strength.load_relationships(target)[0]
    changed = relative_strength.Relationship(
        **{**original.__dict__, "numerator": "bench_press_narrow"}
    )
    with pytest.raises(ValueError, match="membership cannot be changed"):
        relative_strength.update_relationship(changed, path=target)
