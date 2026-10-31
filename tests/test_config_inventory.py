"""Read-only configuration inventory tests."""

from __future__ import annotations

from strength_coach.features import config_inventory, monitoring_analysis


def test_revision_is_deterministic_and_covers_code_defaults(monkeypatch):
    first = config_inventory.build_inventory(today="2026-10-30")
    second = config_inventory.build_inventory(today="2026-10-30")
    assert first["revision"] == second["revision"]

    monkeypatch.setattr(monitoring_analysis, "MIN_CORRELATION_PAIRS", 4)
    changed = config_inventory.build_inventory(today="2026-10-30")
    assert changed["revision"] != first["revision"]
    analysis = {
        row["key"]: row
        for group in changed["groups"] if group["key"] == "analysis"
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
        for group in payload["groups"] if group["key"] == "monitoring"
        for row in group["parameters"]
    }
    row = monitoring["monitoring.recent_reference.observations"]
    assert row["configured"] is False
    assert row["source_kind"] == "python_default"
    assert row["source"].startswith("python-default:")
    assert not row["source"].endswith(".yaml")


def test_relationship_provenance_marks_local_override():
    class Item:
        id = "pair"

    source, kind = config_inventory._relationship_provenance(Item(), {"pair"})
    assert kind == "local_override"
    assert "local" in source
    source, kind = config_inventory._relationship_provenance(Item(), set())
    assert kind == "canonical_config"


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
        "monitoring", "exposure", "calibration", "relationships",
        "readiness", "prescription", "analysis",
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

    relationships = {row["key"]: row for row in groups["relationships"]["parameters"]}
    count = relationships["relationships.count"]["value"]
    assert count >= 2
    assert len([key for key in relationships if key.startswith("relationships.") and key.endswith(".max_gap_days")]) == count

    analysis = {row["key"]: row for row in groups["analysis"]["parameters"]}
    assert analysis["analysis.correlation_min_pairs"]["value"] == 3
    assert analysis["analysis.version"]["editability"] == "fixed"


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
