"""Resolver policy: structural validation for the Step 1 skeleton."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from strength_coach.prescribe.resolver_policy import (
    ResolverPolicy,
    ResolverPolicyError,
    _load_yaml,
    _validate_candidate_catalogue,
    load_candidate_catalogue,
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
    assert policy.allowed_patterns["accessory_row"] == (
        "horizontal_pull", "vertical_pull", "rear_delt_pull"
    )
    assert policy.allowed_patterns["core_anti_extension"] == (
        "core_anti_extension", "core_stability"
    )
    assert policy.slot_pools["hinge"]["hinge_main"] == (
        "trap_bar_deadlift", "sumo_deadlift"
    )
    assert policy.redundancy.max_per_pattern == 2
    assert "ssb_squat" in policy.top_set.eligible_lifts
    assert "conventional_deadlift" not in policy.top_set.eligible_lifts


def test_digest_changes_with_content() -> None:
    first = ResolverPolicy.from_text(_base_text())
    second = ResolverPolicy.from_text(_base_text() + "\n# changed\n")
    assert first.digest != second.digest


def test_validate_text_uses_the_same_parser() -> None:
    policy = validate_text(_base_text())
    assert policy.required_patterns["squat"]
    assert len(policy.digest) == 64


def test_duplicate_yaml_key_is_rejected_at_top_level() -> None:
    with pytest.raises(ResolverPolicyError, match="duplicate key 'redundancy'"):
        ResolverPolicy.from_text(
            _base_text() + "\nredundancy:\n  max_per_pattern: 3\n"
        )


def test_duplicate_yaml_key_is_rejected_nested() -> None:
    body = _base_text().replace(
        "  max_per_pattern: 2\n  max_per_primary_muscle: 2",
        "  max_per_pattern: 2\n  max_per_pattern: 3\n  max_per_primary_muscle: 2",
    )
    with pytest.raises(ResolverPolicyError, match="duplicate key 'redundancy.max_per_pattern'"):
        ResolverPolicy.from_text(body)


def test_malformed_yaml_has_a_useful_error() -> None:
    with pytest.raises(ResolverPolicyError, match="invalid YAML"):
        ResolverPolicy.from_text("schema_version: [unclosed")


def test_yaml_merge_keys_are_rejected() -> None:
    with pytest.raises(ResolverPolicyError, match="merge key"):
        _load_yaml("a: {<<: {b: 1}}", "test")


def test_yaml_merge_keys_are_rejected_in_candidate_catalogue(tmp_path) -> None:
    path = tmp_path / "catalogue.yaml"
    path.write_text("<<: {slots: {}}\n", encoding="utf-8")
    with pytest.raises(ResolverPolicyError, match="merge key"):
        _validate_candidate_catalogue(path, "test")


def test_shared_yaml_aliases_are_allowed() -> None:
    raw = _load_yaml("a: &a [1]\nb: *a\n", "test")
    assert raw["a"] == [1]
    assert raw["b"] == [1]


def test_recursive_mapping_alias_is_rejected() -> None:
    with pytest.raises(ResolverPolicyError, match="recursive YAML alias"):
        _load_yaml("a: &a {b: *a}", "test")


def test_recursive_sequence_alias_is_rejected() -> None:
    with pytest.raises(ResolverPolicyError, match="recursive YAML alias"):
        _load_yaml("a: &a [*a]", "test")


def test_non_string_mapping_keys_are_rejected() -> None:
    with pytest.raises(ResolverPolicyError, match="must be a string"):
        _load_yaml("1: one", "test")
    with pytest.raises(ResolverPolicyError, match="must be a string"):
        _load_yaml("true: yes", "test")
    with pytest.raises(ResolverPolicyError, match="scalar string"):
        _load_yaml("[a]: one", "test")


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


def test_slot_pool_candidate_must_match_the_slot_pattern() -> None:
    raw = yaml.safe_load(_base_text())
    raw["slot_pools"] = {"squat": {"squat_main": ["bench_press"]}}
    with pytest.raises(ResolverPolicyError, match="permitted"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))


def test_explicit_allowed_patterns_permit_flexibility() -> None:
    raw = yaml.safe_load(_base_text())
    raw["allowed_patterns"] = {"squat_main": ["squat", "horizontal_push"]}
    raw["slot_pools"] = {"squat": {"squat_main": ["bench_press"]}}
    policy = ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))
    assert policy.slot_pools["squat"]["squat_main"] == ("bench_press",)


def test_slot_pool_must_not_be_empty() -> None:
    raw = yaml.safe_load(_base_text())
    raw["slot_pools"] = {"squat": {"squat_main": []}}
    with pytest.raises(ResolverPolicyError, match="must not be empty"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))


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


def test_top_set_eligible_lifts_must_be_main_lifts() -> None:
    raw = yaml.safe_load(_base_text())
    raw["top_set"]["eligible_lifts"].append("ab_wheel")
    with pytest.raises(ResolverPolicyError, match="not a main lift"):
        ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))


def test_top_set_accepts_a_classified_primary_compound() -> None:
    # DEC-RESOLVER-13: conventional_deadlift is a primary compound, so it passes the
    # classification gate even though the shipped policy list does not opt it in.
    raw = yaml.safe_load(_base_text())
    raw["top_set"]["eligible_lifts"].append("conventional_deadlift")
    policy = ResolverPolicy.from_text(yaml.safe_dump(raw, sort_keys=False))
    assert "conventional_deadlift" in policy.top_set.eligible_lifts
    assert "conventional_deadlift" not in ResolverPolicy.from_text(_base_text()).top_set.eligible_lifts


def test_candidate_catalogue_must_have_the_expected_structure(tmp_path) -> None:
    path = tmp_path / "catalogue.yaml"
    path.write_text("slots: []\n", encoding="utf-8")
    with pytest.raises(ResolverPolicyError, match="slots"):
        _validate_candidate_catalogue(path, "test")


def test_candidate_catalogue_rejects_unknown_exercises(tmp_path) -> None:
    path = tmp_path / "catalogue.yaml"
    path.write_text(
        "slots:\n"
        "  squat: {squat_main: [not_an_exercise]}\n"
        "  hinge: {}\n"
        "  bench_squat: {}\n"
        "  bench_hinge: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ResolverPolicyError, match="unknown exercise"):
        _validate_candidate_catalogue(path, "test")


def test_candidate_catalogue_candidate_must_match_the_slot_pattern(tmp_path) -> None:
    path = tmp_path / "catalogue.yaml"
    path.write_text(
        "slots:\n"
        "  squat: {squat_main: [bench_press]}\n"
        "  hinge: {}\n"
        "  bench_squat: {}\n"
        "  bench_hinge: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ResolverPolicyError, match="permitted"):
        _validate_candidate_catalogue(path, "test")


def test_candidate_catalogue_explicit_flexibility_allows_a_pattern(tmp_path) -> None:
    path = tmp_path / "catalogue.yaml"
    path.write_text(
        "slots:\n"
        "  squat: {squat_main: [bench_press]}\n"
        "  hinge: {}\n"
        "  bench_squat: {}\n"
        "  bench_hinge: {}\n",
        encoding="utf-8",
    )
    _validate_candidate_catalogue(
        path, "test", {"squat_main": ("squat", "horizontal_push")}
    )


def test_candidate_catalogue_rejects_duplicate_keys(tmp_path) -> None:
    path = tmp_path / "catalogue.yaml"
    path.write_text(
        "slots:\n"
        "  squat:\n"
        "    squat_main: [ssb_squat]\n"
        "    squat_main: [competition_squat]\n"
        "  hinge: {}\n"
        "  bench_squat: {}\n"
        "  bench_hinge: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ResolverPolicyError, match="duplicate key"):
        _validate_candidate_catalogue(path, "test")


def test_candidate_path_must_stay_inside_the_repository() -> None:
    with pytest.raises(ResolverPolicyError, match="relative path"):
        ResolverPolicy.from_text(
            _body(candidate_catalogue={"mode": "reference", "path": "/tmp/variants.yaml"})
        )


def test_candidate_path_must_exist() -> None:
    with pytest.raises(ResolverPolicyError, match="cannot read") as info:
        ResolverPolicy.from_text(
            _body(candidate_catalogue={"mode": "reference", "path": "config/missing.yaml"})
        )
    assert isinstance(info.value.__cause__, FileNotFoundError)


def test_policy_load_missing_file_is_a_configuration_error(tmp_path) -> None:
    with pytest.raises(ResolverPolicyError, match="cannot read") as info:
        ResolverPolicy.load(tmp_path / "missing.yaml")
    assert isinstance(info.value.__cause__, FileNotFoundError)


def test_policy_load_invalid_utf8_is_a_configuration_error(tmp_path) -> None:
    path = tmp_path / "policy.yaml"
    path.write_bytes(b"\xff")
    with pytest.raises(ResolverPolicyError, match="cannot read") as info:
        ResolverPolicy.load(path)
    assert isinstance(info.value.__cause__, UnicodeDecodeError)


def test_policy_load_permission_error_is_a_configuration_error(tmp_path, monkeypatch) -> None:
    def denied(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(ResolverPolicyError, match="cannot read") as info:
        ResolverPolicy.load(tmp_path / "policy.yaml")
    assert isinstance(info.value.__cause__, PermissionError)


def test_candidate_catalogue_invalid_utf8_is_a_configuration_error(tmp_path) -> None:
    path = tmp_path / "catalogue.yaml"
    path.write_bytes(b"\xff")
    with pytest.raises(ResolverPolicyError, match="cannot read") as info:
        _validate_candidate_catalogue(path, "test")
    assert isinstance(info.value.__cause__, UnicodeDecodeError)


def test_candidate_catalogue_is_read_once(monkeypatch) -> None:
    policy = ResolverPolicy.load()
    target = paths.repo_root() / policy.candidate_catalogue.path
    calls: list[Path] = []
    original = Path.read_text

    def counting_read(self, *args, **kwargs):
        if self == target:
            calls.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read)
    catalogue = load_candidate_catalogue(policy)
    assert len(calls) == 1
    assert catalogue["squat"]["squat_main"]


def test_redundancy_must_be_positive() -> None:
    with pytest.raises(ResolverPolicyError, match="positive integer"):
        ResolverPolicy.from_text(_body(redundancy={"max_per_pattern": 0,
                                                   "max_per_primary_muscle": 2}))
