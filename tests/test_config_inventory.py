"""Read-only configuration inventory tests."""

from __future__ import annotations

from strength_coach.features import config_inventory


def test_inventory_groups_values_and_phase_lock():
    payload = config_inventory.build_inventory(today="2026-10-30")
    groups = {group["key"]: group for group in payload["groups"]}

    assert payload["read_only"] is True
    assert payload["application_version"]
    assert len(payload["revision"]) == 64
    assert payload["phase"]["locked"] is True
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
    assert "review is due" in payload["phase"]["note"]
