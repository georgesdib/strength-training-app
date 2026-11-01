"""Resolver policy: structural validation for the Step 1 skeleton."""

from __future__ import annotations

import hashlib

import pytest
import yaml

from strength_coach.prescribe.resolver_policy import (
    ResolverPolicy,
    ResolverPolicyError,
    validate_text,
)
from strength_coach.utils import paths


def _base_text() -> str:
    return paths.template_resolver_yaml().read_text(encoding="utf-8")


def _body(**changes) -> str:
    raw = yaml.safe_load(_base_text())
    raw.update(changes)
    return yaml.safe_dump(raw, sort_keys=False)


def test_default_policy_loads_and_hashes() -> None:
    policy = ResolverPolicy.load()
    assert policy.schema_version == "1.0.0"
    assert policy.digest == hashlib.sha256(
        paths.template_resolver_yaml().read_bytes()
    ).hexdigest()
    assert policy.candidate_catalogue.mode == "reference"
    assert policy.candidate_catalogue.path == "config/variants.v1.yaml"
    assert set(policy.required_patterns) == {"squat", "hinge", "bench_squat", "bench_hinge"}
    assert policy.allowed_patterns == {}
    assert policy.slot_pools == {}
    assert policy.redundancy.max_per_pattern == 2
    assert "ssb_squat" in policy.top_set.eligible_lifts


def test_digest_changes_with_content() -> None:
    first = ResolverPolicy.from_text(_base_text())
    second = ResolverPolicy.from_text(_base_text() + "\n# changed\n")
    assert first.digest != second.digest


def test_validate_text_uses_the_same_parser() -> None:
    policy = validate_text(_base_text())
    assert policy.required_patterns["squat"]
    assert len(policy.digest) == 64


def test_unsupported_schema_is_rejected() -> None:
    body = _base_text().replace('schema_version: "1.0.0"', 'schema_version: "9.0.0"')
    with pytest.raises(ResolverPolicyError, match="unsupported schema"):
        ResolverPolicy.from_text(body)


def test_unknown_top_level_key_is_rejected() -> None:
    with pytest.raises(ResolverPolicyError, match="unknown keys"):
        ResolverPolicy.from_text(_body(unexpected=True))


def test_required_patterns_must_cover_the_four_sessions() -> None:
    raw = yaml.safe_load(_base_text())
    raw["required_patterns"].pop("hinge")
    with pytest.raises(ResolverPolicyError, match="exactly"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))


def test_unknown_pattern_is_rejected() -> None:
    raw = yaml.safe_load(_base_text())
    raw["required_patterns"]["squat"].append("not_a_pattern")
    with pytest.raises(ResolverPolicyError, match="unknown taxonomy pattern"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))


def test_duplicate_pattern_is_rejected() -> None:
    raw = yaml.safe_load(_base_text())
    raw["required_patterns"]["squat"].append("squat")
    with pytest.raises(ResolverPolicyError, match="duplicate pattern"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))


def test_allowed_patterns_need_a_known_slot() -> None:
    with pytest.raises(ResolverPolicyError, match="unknown slot"):
        ResolverPolicy.from_text(_body(allowed_patterns={"not_a_slot": ["squat"]}))


def test_allowed_patterns_and_slot_pools_accept_valid_values() -> None:
    raw = yaml.safe_load(_base_text())
    raw["allowed_patterns"] = {"accessory_row": ["horizontal_pull", "vertical_pull"]}
    raw["slot_pools"] = {"squat": {"squat_main": ["ssb_squat", "competition_squat"]}}
    policy = ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))
    assert policy.allowed_patterns["accessory_row"] == ("horizontal_pull", "vertical_pull")
    assert policy.slot_pools["squat"]["squat_main"] == ("ssb_squat", "competition_squat")


def test_slot_pools_validate_session_slot_and_exercise() -> None:
    raw = yaml.safe_load(_base_text())
    raw["slot_pools"] = {"squat": {"not_a_slot": ["ssb_squat"]}}
    with pytest.raises(ResolverPolicyError, match="unknown slot"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))

    raw["slot_pools"] = {"squat": {"squat_main": ["not_an_exercise"]}}
    with pytest.raises(ResolverPolicyError, match="unknown exercise"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))


def test_top_set_eligible_lifts_must_exist() -> None:
    raw = yaml.safe_load(_base_text())
    raw["top_set"]["eligible_lifts"].append("not_an_exercise")
    with pytest.raises(ResolverPolicyError, match="unknown exercise"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))


def test_candidate_path_must_stay_inside_the_repository() -> None:
    with pytest.raises(ResolverPolicyError, match="relative path"):
        ResolverPolicy.from_text(
            _body(candidate_catalogue={"mode": "reference", "path": "/tmp/variants.yaml"})
        )


def test_candidate_path_must_exist() -> None:
    with pytest.raises(ResolverPolicyError, match="does not exist"):
        ResolverPolicy.from_text(
            _body(candidate_catalogue={"mode": "reference", "path": "config/missing.yaml"})
        )


def test_redundancy_must_be_positive() -> None:
    with pytest.raises(ResolverPolicyError, match="positive integer"):
        ResolverPolicy.from_text(_body(redundancy={"max_per_pattern": 0,
                                                   "max_per_primary_muscle": 2}))
