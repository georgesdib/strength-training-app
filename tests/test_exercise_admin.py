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
                "loadable": True,
            }
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
