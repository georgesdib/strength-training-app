"""Loading the constitution.

Validation is the point: a rule whose `check.fn` is misspelled, or whose scope names a
missing collection, would otherwise become a rule that never fires -- and a report that
claims the constitution passed.
"""

from __future__ import annotations

import pytest
import yaml

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
    assert document.version == "1.19.0"
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


def test_session_scopes_use_canonical_session_types():
    """DEC-SESSION-01: a rule scope must never reintroduce the retired A/B/C labels.

    scope.sessions is descriptive metadata — no predicate reads it — so a stale label is
    otherwise invisible: the report still cites the rule and nothing fails.
    """
    from strength_coach.prescribe.schedule import SESSION_TYPES

    document = loader.load_document()
    for rule in document.rules:
        sessions = rule.scope.get("sessions")
        if sessions is not None:
            assert set(sessions) <= set(SESSION_TYPES), (
                f"{rule.id} scopes sessions {list(sessions)}; "
                f"canonical types are {list(SESSION_TYPES)}"
            )


def test_modifiers_are_parsed_separately_from_rules():
    document = loader.load_document()
    ids = [modifier["id"] for modifier in document.modifiers]
    assert ids == ["MOD-DELOAD-001", "MOD-E1RM-001", "MOD-E1RM-DECAY-001", "MOD-GAP-001", "MOD-FAT-001", "MOD-VOL-001", "MOD-VOL-002", "MOD-VOL-003", "MOD-VOL-004", "MOD-VOL-005", "MOD-SELECT-001", "MOD-BACK-001", "MOD-SPINE-001", "MOD-TECH-001", "MOD-MIN-001"]
    assert "MOD-FAT-001" not in document.rule_ids


def test_every_modifier_names_the_code_that_implements_it():
    """A modifier without a code path is a promise the engine does not keep.

    The `when` blocks are documentation -- Python decides the trigger -- so `implemented_by`
    is the only link from the document to behaviour. This test follows the link: the module
    must import and the function must exist. It is what would have caught MOD-FAT-001's
    first-set RIR branch, which sat in the constitution with no implementation behind it
    (DEC-RIR-04).
    """
    import importlib

    document = loader.load_document()
    assert document.modifiers
    for modifier in document.modifiers:
        target = modifier.get("implemented_by")
        assert target, f"{modifier['id']} does not declare implemented_by"
        path, _, attribute = str(target).partition("::")
        assert attribute, (
            f"{modifier['id']}: implemented_by must be 'module/path.py::function'"
        )
        module = importlib.import_module(path.removesuffix(".py").replace("/", "."))
        assert callable(getattr(module, attribute, None)), (
            f"{modifier['id']}: {target} does not resolve to a callable"
        )


def test_the_spinal_trim_trigger_matches_the_rule_cap():
    """MOD-SPINE-001's `when` value duplicates PRG-SPINE-001's cap; they must not drift."""
    document = loader.load_document()
    cap = document.rule("PRG-SPINE-001").params["cap"]
    modifier = next(m for m in document.modifiers if m["id"] == "MOD-SPINE-001")
    trigger = modifier["when"]["any"][0]
    assert trigger["input"] == "spinal.week_cost"
    assert float(trigger["value"]) == float(cap)


@pytest.mark.parametrize("rules, message", [
    ([make_rule(), make_rule()], "duplicate rule ids"),
    ([make_rule(scope={"exercises": "$not_a_collection"})], "unknown collection"),
    ([make_rule(check={"fn": "not_implemented"})], "unregistered check.fn"),
    ([make_rule(severity="blocker")], "severity must be one of"),
    ([make_rule(on_fail={"action": "veto"})], "on_fail.code is required"),
    ([make_rule(id="rir-thing")], "invalid id"),
])
def test_invalid_documents_are_rejected(tmp_path, rules, message):
    path = write_document(tmp_path, rules=rules)
    with pytest.raises(loader.RuleDocumentError, match=message):
        loader.load_document(path)


def test_content_hash_tracks_the_file_bytes(tmp_path):
    path = write_document(tmp_path)
    first = loader.load_document(path).source_hash
    path.write_text(path.read_text(encoding="utf-8") + "\n# a comment changes the bytes\n",
                    encoding="utf-8")
    second = loader.load_document(path).source_hash
    assert first != second
