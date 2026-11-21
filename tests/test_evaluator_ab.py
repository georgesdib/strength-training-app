"""Fixed-history A/B for the WP6 hierarchy: same finalists, different key."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from conftest import make_readiness, make_training

from strength_coach import settings_profile
from strength_coach.prescribe import resolver, resolver_policy, templates
from strength_coach.prescribe.evaluator import EvaluationInputs
from strength_coach.store import db, importer
from tests.test_resolver_wiring import _pools


def test_fixed_history_ab_changes_only_the_selection_key(monkeypatch) -> None:
    rows = [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-02", "Exercise": "Competition Squat", "Weight_Used": "120",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-09", "Exercise": "Competition Squat", "Weight_Used": "120",
         "RIR": "2", "Reps_Done": "5"},
    ]
    training = make_training(rows)
    readiness = make_readiness([{}])
    with db.Store(":memory:") as store:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        policy = resolver_policy.ResolverPolicy.load()
        empty = replace(
            policy,
            required_patterns=MappingProxyType(
                {session: () for session in templates.SESSION_TYPES}
            ),
        )
        monkeypatch.setattr(
            resolver_policy.ResolverPolicy, "load",
            classmethod(lambda cls, path=None: empty),
        )
        base = _pools()
        rich = replace(
            base,
            pools={**base.pools, "squat_main": ("ssb_squat", "competition_squat")},
        )
        monkeypatch.setattr(
            resolver.generator, "candidate_pools", lambda *args, **kwargs: rich
        )
        settings_profile.save(
            store.connection,
            set_values={"resolver.enabled": True},
            resolver_enable_confirmed=True,
            effective_from="2024-01-01",
        )
        resolved = resolver.build_resolved(
            store.connection,
            for_date="2024-01-15",
            session_type="squat",
            inputs=EvaluationInputs(top_set_intent="off"),
        )

    feasible = [item for item in resolved.beam.evaluated if item.feasible]
    assert len(feasible) == 2
    classic = min(feasible, key=lambda item: item.classic_score_key)
    quality = resolved.beam.best
    assert classic.assignment != quality.assignment
    assert dict(classic.assignment)["squat_main"] == "competition_squat"
    assert dict(quality.assignment)["squat_main"] == "ssb_squat"
    assert quality.quality is not None
    # The A/B only changes the key: both finalists pass the same band, time and warning gate.
    assert {item.components.volume_error for item in feasible} == {0.0}
    assert {item.components.time_over_minutes for item in feasible} == {0.0}
    assert quality.components.warnings <= classic.components.warnings

