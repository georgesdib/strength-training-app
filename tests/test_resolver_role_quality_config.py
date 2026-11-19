"""WP0 checks for the role-quality configuration and synthetic fixtures.

These tests do not exercise the evaluator: the configuration is unwired until WP6.
They keep the approved class values and the fixture shapes from drifting before the
implementation that consumes them exists.
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


def test_legacy_fixture_keeps_roles_and_group_sum() -> None:
    data = _load_json("legacy_two_group_plan.json")
    groups = data["item"]["set_groups"]
    assert [group["role"] for group in groups] == ["top_set", "back_off"]
    assert sum(group["sets"] for group in groups) == data["item"]["sets"] == 4


def test_ordered_fixture_has_no_role_and_contiguous_indexes() -> None:
    data = _load_json("ordered_three_group_plan.json")
    groups = data["item"]["set_groups"]
    assert [group["group_index"] for group in groups] == [0, 1, 2]
    assert all("role" not in group for group in groups)
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
