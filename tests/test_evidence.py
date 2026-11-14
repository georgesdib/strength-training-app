"""The shared evidence envelope is deterministic and never invents a metric."""

from __future__ import annotations

import pytest

from strength_coach.features import evidence


def _item(**overrides):
    base = dict(
        source="adherence",
        source_ids=(11, 12, 13),
        window_start="2024-01-01",
        window_end="2024-01-28",
        value={"set_completion": 0.8},
        source_fingerprint=evidence.make_source_fingerprint(
            [{"set_id": 11, "rir": 2}, {"set_id": 12, "rir": 3}]
        ),
        n=5,
        gate="signal",
        quality_flags=("sets_without_rir",),
    )
    base.update(overrides)
    return evidence.EvidenceItem(**base)


def test_evidence_id_is_deterministic_for_the_same_inputs():
    assert _item().evidence_id == _item().evidence_id
    assert _item().evidence_id.startswith("ev:")


def test_evidence_id_changes_with_the_window_the_rows_or_the_value():
    baseline = _item().evidence_id
    assert _item(window_end="2024-02-04").evidence_id != baseline
    assert _item(source_ids=(11, 12)).evidence_id != baseline
    assert _item(value={"set_completion": 0.9}).evidence_id != baseline
    assert _item(source="vbt").evidence_id != baseline


def test_source_row_order_does_not_change_the_id():
    assert _item(source_ids=(13, 11, 12)).evidence_id == _item().evidence_id


def test_source_fingerprint_changes_when_rows_change_but_the_claim_does_not():
    first = _item(
        source_fingerprint=evidence.make_source_fingerprint(
            [{"set_id": 11, "rir": 2}, {"set_id": 12, "rir": 0}]
        )
    )
    corrected = _item(
        source_fingerprint=evidence.make_source_fingerprint(
            [{"set_id": 11, "rir": 1}, {"set_id": 12, "rir": 1}]
        )
    )
    assert first.evidence_id == corrected.evidence_id
    assert first.source_fingerprint != corrected.source_fingerprint


def test_unknown_gate_and_comparability_are_rejected():
    with pytest.raises(ValueError):
        _item(gate="validated")
    with pytest.raises(ValueError):
        _item(comparability="close_enough")
    with pytest.raises(ValueError):
        _item(n=-1)


def test_payload_carries_provenance_and_limitations():
    payload = _item(
        unit="kg",
        method_versions={"vbt_analysis": "1"},
        calibration_ids=("calibration-1",),
        limitations=("descriptive only",),
        rule_ids=("DEC-AFC-01",),
    ).as_dict()
    assert payload["evidence_id"] == _item(
        unit="kg",
        method_versions={"vbt_analysis": "1"},
        calibration_ids=("calibration-1",),
        limitations=("descriptive only",),
        rule_ids=("DEC-AFC-01",),
    ).evidence_id
    assert payload["evidence_version"] == evidence.EVIDENCE_VERSION
    assert payload["source_fingerprint"].startswith("sf:")
    assert payload["source"] == "adherence"
    assert payload["source_ids"] == ["11", "12", "13"]
    assert payload["window"] == {"start": "2024-01-01", "end": "2024-01-28"}
    assert payload["gate"] == "signal"
    assert payload["comparability"] == "comparable"
    assert payload["method_versions"] == {"vbt_analysis": "1"}
    assert payload["limitations"] == ["descriptive only"]
    assert payload["rule_ids"] == ["DEC-AFC-01"]
