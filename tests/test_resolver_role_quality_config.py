"""WP0/WP6 checks for the role-quality configuration and synthetic fixtures.

These tests keep the approved class values, the wired WP6 criteria and the fixture shapes
from drifting.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "config" / "resolver-role-quality.v1.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "resolver_structure"


def _load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_role_quality_config_records_the_wp0_decisions() -> None:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "1.0.0"
    assert raw["role_priority"] == ["main", "secondary", "accessory"]
    assert raw["criteria"]["main"] == [
        "specificity", "exposure", "suitability",
    ]
    assert raw["criteria"]["secondary"] == [
        "complementarity", "volume_usefulness", "redundancy",
    ]
    assert raw["criteria"]["accessory"] == [
        "coverage", "productive_volume", "stimulus_to_fatigue",
    ]
    assert "continuity" not in raw
    assert raw["specificity"]["classes"] == {
        "same_lift": 3,
        "same_lift_group": 2,
        "same_pattern": 1,
        "other_permitted_pattern": 0,
    }
    assert raw["exposure"]["heavy_band"] == 0.80
    assert raw["exposure"]["e1rm_age_days"] == {"full": 14, "partial": 45}
    assert raw["suitability"]["unrated"] == 2
    assert raw["tax"]["mandatory_axes"]["accessory"] == ["axial", "skill"]
    assert raw["programme_header"]["method"] == "strength_coach.features.programme.header"


def test_role_quality_config_documents_the_wired_criteria() -> None:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    text = CONFIG.read_text(encoding="utf-8")
    assert "unwired" not in text
    assert "WP6 wires it" not in text

    assert raw["complementarity"]["classes"] == {
        "same_pattern": 1,
        "same_family": 1,
        "complementary": 3,
    }
    assert raw["complementarity"]["missing"] == 2
    assert raw["complementarity"]["key_source"] == (
        "strength_coach.features.volume.volume_target_key"
    )

    for name in ("volume_usefulness", "productive_volume"):
        assert raw[name]["tolerance"] == 0.15
        assert raw[name]["classes"] == {
            "fills_deficit": 3,
            "within_target": 2,
            "redundant": 1,
        }
        assert raw[name]["missing"] == 2

    assert raw["redundancy"]["classes"] == {
        "duplicate": 1,
        "partial_overlap": 2,
        "complementary": 3,
    }
    assert raw["redundancy"]["missing"] == 2
    assert raw["coverage"]["classes"] == {"uncovered": 3, "covered": 1}
    assert raw["coverage"]["missing"] == 2
    assert raw["tax"]["classes"] == {"low": 3, "moderate": 2, "high": 1}
    assert raw["tax"]["missing"] == 2
    assert raw["tax"]["stimulus"] == "slot_dose"


def test_legacy_fixture_keeps_roles_and_group_sum() -> None:
    data = _load_json("legacy_two_group_plan.json")
    groups = data["item"]["set_groups"]
    assert [group["role"] for group in groups] == ["top_set", "back_off"]
    assert sum(group["sets"] for group in groups) == data["item"]["sets"] == 4


def test_straight_set_plan_performed_as_top_set_and_back_offs() -> None:
    data = _load_json("straight_set_plan_top_backoff_performance.json")
    performed = data["performed"]
    assert data["plan"]["set_groups"] == []
    assert len(performed) == 4
    assert performed[0]["rir"] == 1
    assert all(row["rir"] == 3 for row in performed[1:])
    assert performed[0]["load_kg"] > performed[1]["load_kg"]


def test_rir6_import_fixture_documents_the_boundary() -> None:
    text = (FIXTURES / "rir6_import_row.csv").read_text(encoding="utf-8")
    header, row = text.strip().splitlines()
    assert header == "Exercise,Set,RPE,Value,Weight,Reps"
    columns = row.split(",")
    # RPE 4 currently maps to RIR 6, which is a warm-up by definition.
    assert columns[2] == "4"


def test_deload_taper_fixture_distinguishes_design_from_failure() -> None:
    data = _load_json("deload_taper_cases.json")
    by_name = {case["name"]: case["expected"] for case in data["cases"]}
    assert by_name["deload"] == {
        "structure_status": "not_applicable",
        "reason_class": "blocked_by_design",
    }
    assert by_name["taper"] == {
        "structure_status": "not_applicable",
        "reason_class": "blocked_by_design",
    }
    assert by_name["unexpected"] == {
        "structure_status": "unsatisfied",
        "reason_class": "unexpected",
    }
