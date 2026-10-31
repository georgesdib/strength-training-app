"""Read-only configuration inventory tests."""

from __future__ import annotations

import shutil

import yaml

from strength_coach.features import config_inventory, monitoring_analysis, relative_strength


def test_revision_is_deterministic_and_covers_code_defaults(monkeypatch):
    first = config_inventory.build_inventory(today="2026-10-30")
    second = config_inventory.build_inventory(today="2026-10-30")
    assert first["revision"] == second["revision"]

    monkeypatch.setattr(monitoring_analysis, "MIN_CORRELATION_PAIRS", 4)
    changed = config_inventory.build_inventory(today="2026-10-30")
    assert changed["revision"] != first["revision"]
    analysis = {
        row["key"]: row
        for group in changed["groups"]
        if group["key"] == "analysis"
        for row in group["parameters"]
    }
    assert analysis["analysis.correlation_min_pairs"]["value"] == 4


def test_python_fallback_is_not_labelled_as_yaml(monkeypatch):
    original = config_inventory._load

    def load(path):
        if path.name == "monitoring.v1.yaml":
            return {}
        return original(path)

    monkeypatch.setattr(config_inventory, "_load", load)
    payload = config_inventory.build_inventory(today="2026-10-30")
    monitoring = {
        row["key"]: row
        for group in payload["groups"]
        if group["key"] == "monitoring"
        for row in group["parameters"]
    }
    row = monitoring["monitoring.recent_reference.observations"]
    assert row["configured"] is False
    assert row["source_kind"] == "python_default"
    assert row["source"].startswith("python-default:")
    assert not row["source"].endswith(".yaml")


def test_local_relationship_overlay_is_not_claimed_without_effective_loader(tmp_path, monkeypatch):
    canonical = tmp_path / "strength-relationships.v1.yaml"
    shutil.copyfile(
        relative_strength.paths.config_dir("strength-relationships.v1.yaml"),
        canonical,
    )
    first = relative_strength.load_relationships(canonical)[0]
    (tmp_path / "strength-relationships.local.yaml").write_text(
        "relationships:\n"
        f"  - id: {first.id}\n"
        "    label: Local label\n"
        f"    numerator: {first.numerator}\n"
        f"    denominator: {first.denominator}\n"
        "    relationship_type: variant_to_main\n"
        "    max_gap_days: 99\n"
        "    max_age_days: 99\n"
        "    min_observations: 2\n"
        "    notes: local test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(relative_strength.paths, "config_dir", lambda name: tmp_path / name)
    group = config_inventory._relationship_group()
    rows = {row["key"]: row for row in group["parameters"]}
    assert rows[f"relationships.{first.id}.max_gap_days"]["value"] == first.max_gap_days
    assert rows[f"relationships.{first.id}.max_gap_days"]["source_kind"] == "canonical_config"
    assert all(row["source_kind"] == "canonical_config" for row in group["parameters"])


def test_prescription_defaults_match_thresholds_loader(tmp_path, monkeypatch):
    from strength_coach.prescribe.config import Thresholds

    path = tmp_path / "thresholds.yaml"
    path.write_text("load: {}\n", encoding="utf-8")
    monkeypatch.setattr(config_inventory.paths, "thresholds_yaml", lambda: path)
    expected = Thresholds.load()
    payload = config_inventory.build_inventory(today="2026-10-30")
    rows = {
        row["key"]: row
        for group in payload["groups"]
        if group["key"] == "prescription"
        for row in group["parameters"]
    }
    assert rows["prescription.load.increment_kg"]["value"] == expected.increment_kg == 2.5
    assert rows["prescription.load.e1rm_source"]["value"] == expected.e1rm_source == "best_usable"
    for key in ("prescription.load.increment_kg", "prescription.load.e1rm_source"):
        assert rows[key]["configured"] is False
        assert rows[key]["source_kind"] == "python_default"


def test_readiness_defaults_match_loader(tmp_path, monkeypatch):
    from strength_coach.features.readiness import ReadinessConfig

    path = tmp_path / "readiness.yaml"
    path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(config_inventory.paths, "readiness_yaml", lambda: path)
    expected = ReadinessConfig.load()
    payload = config_inventory.build_inventory(today="2026-10-30")
    rows = {
        row["key"]: row
        for group in payload["groups"]
        if group["key"] == "readiness"
        for row in group["parameters"]
    }
    assert rows["readiness.merge.strategy"]["value"] == expected.merge_strategy
    assert rows["readiness.score.baseline_days"]["value"] == expected.baseline_days
    assert rows["readiness.score.baseline_days"]["configured"] is False
    assert rows["readiness.score.baseline_days"]["source_kind"] == "python_default"


def test_phase_boundaries_distinguish_before_active_and_post_review():
    before = config_inventory.build_inventory(today="2026-10-29")
    start = config_inventory.build_inventory(today="2026-10-30")
    review = config_inventory.build_inventory(today="2027-01-22")
    after = config_inventory.build_inventory(today="2027-01-23")

    assert before["phase"]["period"] == "before"
    assert start["phase"]["period"] == "active"
    assert review["phase"]["period"] == "active"
    assert after["phase"]["period"] == "post_review"
    assert all(item["phase"]["locked"] is True for item in (before, start, review, after))


def test_inventory_groups_values_and_phase_lock():
    payload = config_inventory.build_inventory(today="2026-10-30")
    groups = {group["key"]: group for group in payload["groups"]}

    assert payload["read_only"] is True
    assert payload["application_version"]
    assert len(payload["revision"]) == 64
    assert payload["phase"]["locked"] is True
    assert payload["phase"]["period"] == "active"
    assert payload["phase"]["review_due"] == "2027-01-22"
    assert set(groups) == {
        "monitoring",
        "exposure",
        "calibration",
        "relationships",
        "readiness",
        "prescription",
        "analysis",
    }

    monitoring = {row["key"]: row for row in groups["monitoring"]["parameters"]}
    assert monitoring["monitoring.hard_sets.near_failure_max_rir"]["value"] == 2
    assert monitoring["monitoring.recent_reference.max_age_days"]["source"] == "config/monitoring.v1.yaml"

    exposure = {row["key"]: row for row in groups["exposure"]["parameters"]}
    assert exposure["exposure.acute_days"]["value"] == 7
    assert exposure["exposure.chronic_days"]["value"] == 28

    calibration = {row["key"]: row for row in groups["calibration"]["parameters"]}
    assert calibration["calibration.min_tests"]["value"] == 3
    assert calibration["e1rm.method_version"]["editability"] == "fixed"
    assert calibration["e1rm.method_version"]["configured"] is False

    relationships = {row["key"]: row for row in groups["relationships"]["parameters"]}
    count = relationships["relationships.count"]["value"]
    assert count >= 2
    assert (
        len(
            [
                key
                for key in relationships
                if key.startswith("relationships.") and key.endswith(".max_gap_days")
            ]
        )
        == count
    )

    analysis = {row["key"]: row for row in groups["analysis"]["parameters"]}
    assert analysis["analysis.correlation_min_pairs"]["value"] == 3
    assert analysis["analysis.version"]["editability"] == "fixed"
    assert analysis["analysis.version"]["configured"] is False


def test_inventory_has_no_absolute_paths_or_athlete_data():
    payload = config_inventory.build_inventory(today="2026-10-30")
    text = repr(payload)
    assert "/home/" not in text
    assert "data/coach.db" not in text
    for group in payload["groups"]:
        for row in group["parameters"]:
            assert row["editable"] is False
            assert not row["source"].startswith("/")
            assert row["doc"].endswith(".md")


def test_after_review_date_inventory_remains_locked():
    payload = config_inventory.build_inventory(today="2027-01-23")
    assert payload["phase"]["locked"] is True
    assert payload["phase"]["period"] == "post_review"
    assert "review date has passed" in payload["phase"]["note"]


def _budget_rows(tmp_path, monkeypatch, mutate=None, local=None):
    source = config_inventory.paths.config_dir("volume.v1.yaml")
    shutil.copyfile(config_inventory.paths.thresholds_yaml(), tmp_path / "thresholds.v1.yaml")
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if mutate is not None:
        mutate(data)
    (tmp_path / "volume.v1.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    if local is not None:
        (tmp_path / "volume.local.yaml").write_text(yaml.safe_dump(local, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        config_inventory.paths,
        "config_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    group = config_inventory._prescription_group()
    return {row["key"]: row for row in group["parameters"]}


def _assert_budget(row, value, source, kind, configured):
    assert row["value"] == value
    assert row["source"] == source
    assert row["source_kind"] == kind
    assert row["configured"] is configured


def test_budget_total_derived_from_canonical_targets(tmp_path, monkeypatch):
    def mutate(data):
        del data["budget"]["weekly_total"]

    rows = _budget_rows(tmp_path, monkeypatch, mutate)
    _assert_budget(
        rows["volume.budget.weekly_total"],
        63.0,
        "config/volume.v1.yaml",
        "canonical_config",
        True,
    )


def test_budget_total_derived_from_merged_local_targets(tmp_path, monkeypatch):
    def mutate(data):
        del data["budget"]["weekly_total"]

    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        mutate,
        local={"budget": {"weekly_target": {"squat": 11}}},
    )
    _assert_budget(
        rows["volume.budget.weekly_total"],
        64.0,
        "merged config: config/volume.v1.yaml + config/volume.local.yaml",
        "local_override",
        True,
    )


def test_explicit_local_budget_total_takes_precedence(tmp_path, monkeypatch):
    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        local={"budget": {"weekly_total": 63}},
    )
    _assert_budget(
        rows["volume.budget.weekly_total"],
        63.0,
        "local override: config/volume.local.yaml",
        "local_override",
        True,
    )


def test_explicit_canonical_total_keeps_provenance_with_local_targets(tmp_path, monkeypatch):
    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        local={"budget": {"weekly_target": {"squat": 11, "horizontal_push": 11}}},
    )
    _assert_budget(
        rows["volume.budget.weekly_total"],
        63.0,
        "config/volume.v1.yaml",
        "canonical_config",
        True,
    )


def test_effective_total_derived_from_canonical_effective_targets(tmp_path, monkeypatch):
    def mutate(data):
        del data["budget"]["weekly_total_effective"]

    rows = _budget_rows(tmp_path, monkeypatch, mutate)
    _assert_budget(
        rows["volume.budget.weekly_total_effective"],
        74.25,
        "config/volume.v1.yaml",
        "canonical_config",
        True,
    )


def test_effective_total_derived_from_merged_effective_targets(tmp_path, monkeypatch):
    def mutate(data):
        del data["budget"]["weekly_total_effective"]

    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        mutate,
        local={"budget": {"weekly_target_effective": {"squat": 11}}},
    )
    _assert_budget(
        rows["volume.budget.weekly_total_effective"],
        75.25,
        "merged config: config/volume.v1.yaml + config/volume.local.yaml",
        "local_override",
        True,
    )


def test_effective_total_falls_back_to_merged_weekly_targets(tmp_path, monkeypatch):
    def mutate(data):
        del data["budget"]["weekly_target_effective"]
        del data["budget"]["weekly_total_effective"]
        del data["budget"]["weekly_total"]

    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        mutate,
        local={"budget": {"weekly_target": {"squat": 11}}},
    )
    _assert_budget(
        rows["volume.budget.weekly_total_effective"],
        64.0,
        "merged config: config/volume.v1.yaml + config/volume.local.yaml",
        "local_override",
        True,
    )


def test_budget_totals_use_python_defaults_when_targets_absent(tmp_path, monkeypatch):
    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        mutate=lambda data: data.update({"budget": {}}),
    )
    _assert_budget(
        rows["volume.budget.weekly_total"],
        63.0,
        "python-default: strength_coach/prescribe/volume_budget.py",
        "python_default",
        False,
    )
    _assert_budget(
        rows["volume.budget.weekly_total_effective"],
        63.0,
        "python-default: strength_coach/prescribe/volume_budget.py",
        "python_default",
        False,
    )


def test_local_null_suppresses_canonical_weekly_total(tmp_path, monkeypatch):
    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        local={"budget": {"weekly_total": None}},
    )
    _assert_budget(
        rows["volume.budget.weekly_total"],
        63.0,
        "config/volume.v1.yaml",
        "canonical_config",
        True,
    )


def test_local_null_suppresses_canonical_effective_total(tmp_path, monkeypatch):
    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        local={"budget": {"weekly_total_effective": None}},
    )
    _assert_budget(
        rows["volume.budget.weekly_total_effective"],
        74.25,
        "config/volume.v1.yaml",
        "canonical_config",
        True,
    )


def test_local_null_effective_total_falls_back_to_weekly_targets(tmp_path, monkeypatch):
    def mutate(data):
        del data["budget"]["weekly_target_effective"]

    rows = _budget_rows(
        tmp_path,
        monkeypatch,
        mutate,
        local={"budget": {"weekly_total_effective": None}},
    )
    _assert_budget(
        rows["volume.budget.weekly_total_effective"],
        63.0,
        "config/volume.v1.yaml",
        "canonical_config",
        True,
    )
