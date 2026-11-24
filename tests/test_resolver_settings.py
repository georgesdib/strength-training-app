"""Resolver settings: Step 1 storage, defaults and prescription snapshot."""

from __future__ import annotations

import json

import pytest

from strength_coach import settings_profile, settings_registry
from strength_coach.store import db, repositories


def test_resolver_defaults_are_registered_and_neutral() -> None:
    snapshot = settings_registry.snapshot()
    assert snapshot.get("resolver.enabled") is False
    assert snapshot.get("resolver.dwell.target") == 7
    assert snapshot.get("resolver.dwell.tau") == pytest.approx(0.5)
    assert snapshot.get("resolver.dwell.probability") == pytest.approx(0.1)
    assert snapshot.get("resolver.eligibility.auto_requires_can_do") is False
    assert snapshot.get("resolver.top_set.mode") == "off"
    assert snapshot.get("resolver.top_set.fallback_above_rir") == 2
    assert snapshot.get("resolver.competition.peak_weeks") == 4
    weights = [
        snapshot.get("resolver.weights.readiness"),
        snapshot.get("resolver.weights.fatigue"),
        snapshot.get("resolver.weights.spinal"),
        snapshot.get("resolver.weights.injury"),
        snapshot.get("resolver.weights.dwell"),
    ]
    assert abs(sum(weights) - 0.80) < 1e-9
    assert "resolver.weights.rotation" not in snapshot.values
    assert "resolver.weights.preference" not in snapshot.values


def test_resolver_enable_requires_shared_confirmation() -> None:
    store = db.Store(path=":memory:")
    try:
        with pytest.raises(ValueError, match="resolver.enabled requires explicit confirmation"):
            settings_profile.save(
                store.connection,
                set_values={"resolver.enabled": True},
                effective_from="2024-01-01",
            )
        state = settings_profile.save(
            store.connection,
            set_values={"resolver.enabled": True},
            effective_from="2024-01-01",
            resolver_enable_confirmed=True,
        )
        assert state["resolved"]["resolver.enabled"] is True
        state = settings_profile.save(
            store.connection,
            set_values={"resolver.dwell.target": 5},
            effective_from="2024-01-02",
        )
        assert state["resolved"]["resolver.enabled"] is True
    finally:
        store.close()


def test_resolver_settings_are_profile_backed() -> None:
    store = db.Store(path=":memory:")
    try:
        state = settings_profile.save(
            store.connection,
            set_values={
                "resolver.dwell.tau": 0.8,
                "resolver.top_set.mode": "preferred",
            },
            effective_from="2026-11-01",
        )
        assert state["resolved"]["resolver.dwell.tau"] == 0.8
        assert state["resolved"]["resolver.top_set.mode"] == "preferred"
        assert state["overrides"]["resolver.dwell.tau"] == 0.8
    finally:
        store.close()


def test_resolver_guarded_keys_need_confirmation() -> None:
    store = db.Store(path=":memory:")
    try:
        with pytest.raises(ValueError, match="guarded settings require confirmation"):
            settings_profile.save(
                store.connection,
                set_values={"resolver.weights.spinal": 0.2},
                effective_from="2026-11-01",
            )
        state = settings_profile.save(
            store.connection,
            set_values={"resolver.weights.spinal": 0.2},
            effective_from="2026-11-01",
            guard_confirmed=True,
            reason="resolver step 1 test",
        )
        assert state["resolved"]["resolver.weights.spinal"] == 0.2
    finally:
        store.close()


def test_prescription_snapshot_includes_resolver_keys() -> None:
    store = db.Store(path=":memory:")
    try:
        conn = store.connection
        run = repositories.start_run(conn, input_hash="resolver", code_version="test")
        repositories.append_prescription(
            conn,
            prescription_id="p-resolver",
            run_id=run.run_id,
            for_date="2026-11-01",
            session_type="squat",
            fallback_level="full",
            rule_document_version="test",
            calibration_ids=(),
            approved_by="deterministic",
            items=[],
        )
        settings_profile.snapshot_prescription(conn, "p-resolver", "2026-11-01")
        snapshot = repositories.prescription_profile(conn, "p-resolver")
        assert snapshot is not None
        decoded = json.loads(snapshot["settings_json"])
        assert decoded["registry"]["resolver.enabled"] is False
        assert decoded["registry"]["resolver.top_set.mode"] == "off"
    finally:
        store.close()
