"""Loading the constitution.

Validation is the point: a rule whose `check.fn` is misspelled, or whose scope names a
missing collection, would otherwise become a rule that never fires -- and a report that
claims the constitution passed.
"""

from __future__ import annotations

import yaml

import pytest

from strength_coach.rules import loader


def make_rule(**overrides):
    rule = {
        "id": "PRG-RIR-001",
        "title": "Effort window",
        "severity": "veto",
        "scope": {"exercises": "$primary_compounds"},
        "statement": "no RIR 0-1",
        "params": {"default_rir": {"min": 2, "max": 3}},
        "inputs": ["set.rir"],
        "check": {"fn": "primary_compound_rir_window", "args": {}},
        "citations": ["constitution §2"],
        "depends_on_data_decisions": ["DQ-RIR-01"],
        "on_fail": {"action": "veto", "code": "RIR_FLOOR"},
        "notes": "why",
    }
    rule.update(overrides)
    return rule


def write_document(tmp_path, *, rules=None, collections=None, document=None, name="rules.yaml"):
    payload = {
        "document": {"id": "programme.constitution", "version": "1.0.0", **(document or {})},
        "collections": (
            collections if collections is not None else {"primary_compounds": ["ssb_squat"]}
        ),
        "rules": rules if rules is not None else [make_rule()],
    }
    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def test_loads_the_real_constitution():
    document = loader.load_document()
    assert document.document_id == "programme.constitution"
    assert document.version == "1.0.0"
    assert document.rule_ids == (
        "PRG-RIR-001",
        "PRG-DP-001",
        "PRG-SCHED-001",
        "PRG-EREC-001",
        "PRG-SPINE-001",
    )
    assert len(document.source_hash) == 64
    # Draft: the user has not approved it, so there is no effective date to invent.
    assert document.effective_from is None


def test_rule_fields_are_preserved():
    rule = loader.load_document().rule("PRG-RIR-001")
    assert rule.severity == "veto"
    assert rule.fail_action == "veto"
    assert rule.fail_code == "RIR_FLOOR"
    assert rule.check_fn == "primary_compound_rir_window"
    assert rule.citations
    assert "DQ-RIR-01" in rule.depends_on_data_decisions


def test_collection_scope_resolves_to_exercise_ids():
    document = loader.load_document()
    rule = document.rule("PRG-RIR-001")
    exercises = document.scope_exercises(rule.scope)
    assert "ssb_squat" in exercises and "trap_bar_deadlift" in exercises


def test_unscoped_rule_returns_none():
    document = loader.load_document()
    rule = document.rule("PRG-SPINE-001")
    assert document.scope_exercises(rule.scope) is None


def test_modifiers_are_parsed_separately_from_rules():
    document = loader.load_document()
    ids = [modifier["id"] for modifier in document.modifiers]
    assert ids == ["MOD-FAT-001", "MOD-BACK-001"]
    assert "MOD-FAT-001" not in document.rule_ids


def test_duplicate_rule_ids_are_rejected(tmp_path):
    path = write_document(tmp_path, rules=[make_rule(), make_rule()])
    with pytest.raises(loader.RuleDocumentError, match="duplicate rule ids"):
        loader.load_document(path)


def test_unknown_collection_is_rejected(tmp_path):
    path = write_document(
        tmp_path,
        rules=[make_rule(scope={"exercises": "$not_a_collection"})],
    )
    with pytest.raises(loader.RuleDocumentError, match="unknown collection"):
        loader.load_document(path)


def test_unregistered_predicate_is_rejected(tmp_path):
    path = write_document(tmp_path, rules=[make_rule(check={"fn": "not_implemented"})])
    with pytest.raises(loader.RuleDocumentError, match="unregistered check.fn"):
        loader.load_document(path)


def test_invalid_severity_is_rejected(tmp_path):
    path = write_document(tmp_path, rules=[make_rule(severity="blocker")])
    with pytest.raises(loader.RuleDocumentError, match="severity must be one of"):
        loader.load_document(path)


def test_missing_fail_code_is_rejected(tmp_path):
    path = write_document(tmp_path, rules=[make_rule(on_fail={"action": "veto"})])
    with pytest.raises(loader.RuleDocumentError, match="on_fail.code is required"):
        loader.load_document(path)


def test_invalid_rule_id_is_rejected(tmp_path):
    path = write_document(tmp_path, rules=[make_rule(id="rir-thing")])
    with pytest.raises(loader.RuleDocumentError, match="invalid id"):
        loader.load_document(path)


def test_content_hash_tracks_the_file_bytes(tmp_path):
    path = write_document(tmp_path)
    first = loader.load_document(path).source_hash
    path.write_text(path.read_text(encoding="utf-8") + "\n# a comment changes the bytes\n",
                    encoding="utf-8")
    second = loader.load_document(path).source_hash
    assert first != second
