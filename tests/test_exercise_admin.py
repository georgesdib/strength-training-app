"""Exercise-catalogue edits: overrides merge, validation, no taxonomy rewrite."""

from __future__ import annotations

import pytest
import yaml

from strength_coach.store import exercise_admin
from strength_coach.utils import exercises, paths


def _root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "repo_root", lambda: tmp_path)
    cfg = tmp_path / "config" / "exercises"
    cfg.mkdir(parents=True)
    (cfg / "taxonomy.v1.yaml").write_text(yaml.safe_dump({
        "schema_version": "1.0.0",
        "entities": {
            "base_lift": {
                "display": "Base Lift",
                "log_names": ["Base Lift"],
                "pattern": "squat",
                "primary_muscles": ["quadriceps"],
                "loadable": True,
            },
            "hinge_lift": {
                "display": "Hinge Lift",
                "log_names": ["Hinge Lift"],
                "pattern": "hinge",
                "primary_muscles": ["hamstrings"],
                "loadable": True,
            },
        },
    }))
    (cfg / "overrides.v1.yaml").write_text("schema_version: '1.0.0'\nentities: {}\n")
    exercises.taxonomy.cache_clear()
    return tmp_path


def test_edit_base_entity_is_written_as_an_override(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    result = exercise_admin.save("base_lift", {"pattern": "hinge"})
    row = next(r for r in result["entities"] if r["id"] == "base_lift")
    assert row["source"] == "override"
    assert row["pattern"] == "hinge"
    assert row["props"]["display"] == "Base Lift"  # untouched fields are preserved
    base = yaml.safe_load((tmp_path / "config/exercises/taxonomy.v1.yaml").read_text())
    assert base["entities"]["base_lift"]["pattern"] == "squat"


def test_add_a_new_exercise_and_resolve_it(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    exercise_admin.save("new_lift", {
        "display": "New Lift",
        "log_names": ["New Lift"],
        "pattern": "squat",
        "primary_muscles": ["quadriceps"],
        "loadable": True,
    })
    tax = exercises.Taxonomy.load(
        tmp_path / "config/exercises/taxonomy.v1.yaml",
        overrides_path=tmp_path / "config/exercises/overrides.v1.yaml",
    )
    resolved = tax.resolve("New Lift")
    assert resolved.id == "new_lift"
    assert resolved.pattern == "squat"
    assert tax.resolve("Base Lift").id == "base_lift"


def test_an_unknown_pattern_is_refused(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="canonical taxonomy pattern"):
        exercise_admin.save("new_lift", {
            "display": "New Lift",
            "log_names": ["New Lift"],
            "pattern": "squattt",
        })


def test_an_unknown_muscle_is_refused(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="primary_muscles"):
        exercise_admin.save("new_lift", {
            "display": "New Lift",
            "log_names": ["New Lift"],
            "pattern": "squat",
            "primary_muscles": ["quadricep"],
        })


def test_a_new_vbt_family_is_allowed_but_must_be_a_slug(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    exercise_admin.save("new_lift", {
        "display": "New Lift",
        "log_names": ["New Lift"],
        "pattern": "squat",
        "vbt_family": "squat_variant_two",
    })
    with pytest.raises(ValueError, match="vbt_family"):
        exercise_admin.save("new_lift", {"vbt_family": "Squat Variant"})


def test_vbt_and_spinal_cost_can_be_cleared_and_spinal_cost_is_bounded(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    result = exercise_admin.save("new_lift", {
        "display": "New Lift", "log_names": ["New Lift"], "pattern": "squat",
        "vbt_family": "squat_variant_two", "spinal_cost": 2.5,
    })
    row = next(r for r in result["entities"] if r["id"] == "new_lift")
    assert row["props"]["vbt_family"] == "squat_variant_two"
    assert row["props"]["spinal_cost"] == 2.5

    cleared = exercise_admin.save("new_lift", {"vbt_family": None, "spinal_cost": None})
    row = next(r for r in cleared["entities"] if r["id"] == "new_lift")
    assert "vbt_family" not in row["props"]
    assert "spinal_cost" not in row["props"]

    with pytest.raises(ValueError, match="between 0 and 5"):
        exercise_admin.save("new_lift", {"spinal_cost": 5.5})
    with pytest.raises(ValueError, match="0.5 steps"):
        exercise_admin.save("new_lift", {"spinal_cost": 0.1})


def test_a_legacy_pattern_can_be_preserved_but_not_extended(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    # Simulate a record whose pattern predates the current taxonomy. Keeping it is allowed;
    # changing to another unknown value is not.
    base = yaml.safe_load((tmp_path / "config/exercises/taxonomy.v1.yaml").read_text())
    base["entities"]["legacy_lift"] = {
        "display": "Legacy Lift", "log_names": ["Legacy Lift"], "pattern": "old_pattern",
    }
    (tmp_path / "config/exercises/taxonomy.v1.yaml").write_text(yaml.safe_dump(base))
    exercises.taxonomy.cache_clear()
    exercise_admin.save("legacy_lift", {"display": "Legacy Lift"})
    with pytest.raises(ValueError, match="canonical taxonomy pattern"):
        exercise_admin.save("legacy_lift", {"pattern": "another_unknown"})


def test_log_name_collisions_are_refused(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="already belongs"):
        exercise_admin.save("other", {
            "display": "Other",
            "log_names": ["Base Lift"],
            "pattern": "squat",
        })


def test_an_id_cannot_be_changed_or_invalid(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="id must"):
        exercise_admin.save("Bad Id", {
            "display": "Bad",
            "log_names": ["Bad"],
            "pattern": "squat",
        })


def test_catalogue_day_roles_are_derived_from_templates():
    rows = {row["id"]: row["props"].get("day_roles") for row in exercise_admin.catalog()["entities"]}
    assert rows["bench_press_narrow"] == ["hinge"]
    assert rows["bench_press_pause"] == ["hinge"]
    assert rows["1_arm_row"] == []
