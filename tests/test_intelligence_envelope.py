"""The envelope contract: shape, vocabularies, evidence references and determinism."""

from __future__ import annotations

import dataclasses as dc
import json

import pytest
from intelligence_support import ZERO_HASH, envelope, evidence_item

from strength_coach.intelligence.envelope import (
    SCHEMA_VERSION,
    FactBlock,
    Period,
    Provenance,
)
from strength_coach.intelligence.errors import EnvelopeError


def test_valid_envelope_passes_validation_and_matches_contract_shape():
    env = envelope()
    env.validate()
    payload = env.as_dict()
    assert set(payload) == {
        "intelligence_version",
        "schema_version",
        "capability",
        "capability_version",
        "status",
        "as_of",
        "period",
        "subject",
        "units",
        "facts",
        "evidence",
        "observations",
        "coverage",
        "missing",
        "limitations",
        "quality_flags",
        "privacy",
        "provenance",
        "generated_at",
    }
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["subject"] == {"athlete": "self"}
    # The contract calls the privacy field "class"; Python cannot.
    assert payload["privacy"]["class"] == "training"
    assert "classification" not in payload["privacy"]
    assert payload["facts"]["attendance"]["basis"] == "derived"


def test_evidence_is_passed_through_unchanged():
    item = evidence_item(value={"numerator": 1, "denominator": 1})
    fact = dc.replace(
        envelope().facts["attendance"], evidence_ids=(str(item["evidence_id"]),)
    )
    env = envelope(evidence=(item,), facts={"attendance": fact})
    env.validate()
    assert env.as_dict()["evidence"][0] == item


def test_canonical_json_is_stable_and_order_independent():
    first = envelope()
    second = envelope()
    assert first.canonical_json() == second.canonical_json()
    assert json.loads(first.canonical_json()) == first.as_dict()


def test_canonical_json_ignores_source_key_order():
    item = dict(evidence_item())
    reordered = dict(reversed(list(item.items())))
    env = envelope(evidence=(reordered,))
    env.validate()
    assert env.canonical_json() == envelope(evidence=(item,)).canonical_json()


def test_rejects_unregistered_method():
    fact = dc.replace(envelope().facts["attendance"], method="strength_coach.features.nope")
    with pytest.raises(EnvelopeError, match="unregistered method"):
        envelope(facts={"attendance": fact}).validate()


def test_observed_fact_also_requires_a_registered_method():
    fact = dc.replace(envelope().facts["attendance"], basis="observed", method="made.up")
    with pytest.raises(EnvelopeError, match="unregistered method"):
        envelope(facts={"attendance": fact}).validate()


def test_rejects_unknown_evidence_reference():
    fact = FactBlock(
        value=1,
        basis="derived",
        method="strength_coach.features.attendance.summary",
        evidence_ids=("ev:deadbeef",),
    )
    with pytest.raises(EnvelopeError, match="unknown evidence"):
        envelope(facts={"attendance": fact}).validate()


def test_rejects_duplicate_evidence_ids():
    item = evidence_item()
    with pytest.raises(EnvelopeError, match="duplicate evidence"):
        envelope(evidence=(item, dict(item))).validate()


def test_ok_requires_at_least_one_fact():
    with pytest.raises(EnvelopeError, match="requires at least one fact"):
        envelope(facts={}).validate()


def test_no_data_may_have_no_facts():
    env = envelope(status="no_data", facts={}, evidence=())
    env.validate()


def test_rejects_unknown_status():
    with pytest.raises(EnvelopeError, match="status"):
        envelope(status="error").validate()


def test_rejects_reversed_period():
    period = Period(start="2026-11-15", end="2026-11-14", days=1, weeks=1, timezone="UTC")
    with pytest.raises(EnvelopeError, match="period.start"):
        envelope(period=period).validate()


def test_rejects_period_days_below_one():
    period = Period(start="2026-11-14", end="2026-11-14", days=0, weeks=1, timezone="UTC")
    with pytest.raises(EnvelopeError, match="period.days"):
        envelope(period=period).validate()


def test_rejects_generated_at_without_utc_suffix():
    with pytest.raises(EnvelopeError, match="generated_at"):
        envelope(generated_at="2026-11-14T09:00:00+00:00").validate()


def test_rejects_foreign_subject():
    with pytest.raises(EnvelopeError, match="single athlete"):
        envelope(subject={"athlete": "other"}).validate()


def test_rejects_more_than_two_observations():
    item = evidence_item()
    observation = {
        "family": "rir",
        "text": "synthetic",
        "gate": "signal",
        "n": 1,
        "evidence_id": item["evidence_id"],
        "limitations": [],
    }
    with pytest.raises(EnvelopeError, match="two observations"):
        envelope(observations=(observation, dict(observation), dict(observation))).validate()


def test_rejects_observation_with_unknown_evidence():
    observation = {
        "family": "rir",
        "text": "synthetic",
        "gate": "signal",
        "n": 1,
        "evidence_id": "ev:deadbeef",
        "limitations": [],
    }
    with pytest.raises(EnvelopeError, match="observation references unknown evidence"):
        envelope(observations=(observation,)).validate()


def test_rejects_bad_evidence_gate_vocabulary():
    item = dict(evidence_item())
    item["gate"] = "excellent"
    with pytest.raises(EnvelopeError, match="evidence gate"):
        envelope(evidence=(item,)).validate()


def test_rejects_non_json_fact_value():
    fact = dc.replace(envelope().facts["attendance"], value=object())
    with pytest.raises(EnvelopeError, match="JSON serialisable"):
        envelope(facts={"attendance": fact}).validate()


def test_rejects_empty_units():
    with pytest.raises(EnvelopeError, match="units"):
        envelope(units={}).validate()


def test_rejects_bad_privacy_class():
    from strength_coach.intelligence.envelope import Privacy

    with pytest.raises(EnvelopeError, match="privacy class"):
        envelope(privacy=Privacy(classification="secret")).validate()


def test_rejects_provenance_without_services():
    provenance = Provenance(
        services=(),
        config_revision=ZERO_HASH,
        database_revision=1,
        builder_version="context.v1",
        context_hash=ZERO_HASH,
    )
    with pytest.raises(EnvelopeError, match="provenance.services"):
        envelope(provenance=provenance).validate()


def test_rejects_unknown_capability_identifier():
    with pytest.raises(EnvelopeError, match="capability"):
        envelope(capability="Training Overview").validate()


def test_envelope_is_frozen():
    env = envelope()
    with pytest.raises(dc.FrozenInstanceError):
        env.status = "no_data"  # type: ignore[misc]


def test_as_dict_is_a_fresh_structure():
    env = envelope()
    payload = env.as_dict()
    payload["facts"].clear()
    assert env.as_dict()["facts"], "as_dict must not expose internal state"
