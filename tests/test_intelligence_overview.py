"""Capability execution: composition, validation, determinism, read-only and failure mapping."""

from __future__ import annotations

import dataclasses as dc
import json
import logging

import pytest
from intelligence_support import (
    enabled_config,
    seed_store,
    service,
)
from intelligence_support import (
    envelope as valid_envelope,
)

from strength_coach.features import progress
from strength_coach.intelligence import INTERNAL_PRINCIPAL, IntelligenceConfig
from strength_coach.intelligence.errors import IntelligenceError
from strength_coach.intelligence.registry import (
    CapabilityRegistry,
    CapabilityRequest,
    CapabilitySpec,
)

TABLES = ("session", "clean_set", "workout_session", "workout_set", "prescription", "readiness_day")


def _counts(conn) -> dict[str, int]:
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def _overview(conn, **arguments):
    args: dict[str, object] = {"as_of": "2026-11-14", "window_weeks": 4}
    args.update(arguments)
    return service(conn).execute(INTERNAL_PRINCIPAL, "get_training_overview", args)


def test_overview_matches_the_owning_services():
    store = seed_store()
    try:
        conn = store.connection
        result = _overview(conn)
        assert result.ok, result.error
        env = result.envelope
        direct = progress.dashboard(conn, "2026-11-14", weeks=4)

        assert env.status == "ok"
        assert env.facts["attendance"].value["completed"] == direct["attendance"]["completed"] == 3
        assert env.facts["feedback_coverage"].value["sessions"] == direct["coverage"]["sessions"]
        assert env.facts["volume"].value == direct["volume"]
        assert env.coverage["completed_sessions"] == 3
        assert env.facts["deload"].value["active"] is False
        assert env.facts["readiness_coverage"].value["observed_days"] == 1
        assert env.period.start == "2026-10-18"
        assert env.period.end == "2026-11-14"
        assert env.period.days == 28
    finally:
        store.close()


def test_overview_never_returns_health_or_note_fields():
    store = seed_store()
    try:
        env = _overview(store.connection).envelope
        values = {name: fact.value for name, fact in env.facts.items()}
        text = json.dumps(values)
        for forbidden in ("injury_free", "symptom", '"level"', "notes"):
            assert forbidden not in text, forbidden
        assert set(env.facts["attendance"].value) == {
            "completed",
            "target",
            "pct",
            "target_shortfall",
            "families",
            "session_types",
            "duration",
        }
        assert env.privacy.as_dict()["class"] == "training"
        assert "readiness values" in env.privacy.excluded_fields
    finally:
        store.close()


def test_every_fact_names_a_registered_owner():
    store = seed_store()
    try:
        env = _overview(store.connection).envelope
        from strength_coach.intelligence.methods import METHODS

        for name, fact in env.facts.items():
            assert fact.method in METHODS, name
            assert fact.basis == "derived", name
    finally:
        store.close()


def test_missing_target_is_reported_not_invented():
    store = seed_store()
    try:
        env = _overview(store.connection).envelope
        assert env.facts["attendance"].value["target"] is None
        assert env.facts["attendance"].value["pct"] is None
        assert "no sessions-per-week target in the athlete profile" in env.missing
    finally:
        store.close()


def test_empty_window_is_no_data_not_zero_progress():
    store = seed_store()
    try:
        result = _overview(store.connection, as_of="2025-01-01", window_weeks=4)
        assert result.ok
        env = result.envelope
        assert env.status == "no_data"
        assert "no completed sessions in the window" in env.missing
        assert "no comparable e1RM observations in the window" in env.missing
        assert env.facts["attendance"].value["completed"] == 0
        assert env.facts["strength_trend"].gate == "insufficient"
    finally:
        store.close()


@pytest.mark.parametrize(
    "arguments, field",
    [
        ({"as_of": "2026-11-15"}, "as_of"),
        ({"as_of": "14/11/2026"}, "as_of"),
        ({"as_of": 20261114}, "as_of"),
        ({"as_of": "1999-12-31"}, "as_of"),
        ({"window_weeks": 0}, "window_weeks"),
        ({"window_weeks": 53}, "window_weeks"),
        ({"window_weeks": "4"}, "window_weeks"),
        ({"window_weeks": True}, "window_weeks"),
        ({"window_weeks": 4.0}, "window_weeks"),
        ({"window_weeks": None}, "window_weeks"),
        ({"bogus": 1}, "bogus"),
    ],
)
def test_invalid_arguments_are_rejected_with_a_field(arguments, field):
    store = seed_store()
    try:
        result = _overview(store.connection, **arguments)
        assert not result.ok
        assert result.error.code == "invalid_argument"
        assert result.error.field == field
    finally:
        store.close()


def test_non_object_payload_is_rejected():
    store = seed_store()
    try:
        result = service(store.connection).execute(
            INTERNAL_PRINCIPAL, "get_training_overview", ["not", "an", "object"]
        )
        assert result.error.code == "invalid_argument"
    finally:
        store.close()


def test_window_limit_comes_from_configuration():
    store = seed_store()
    try:
        tight = service(store.connection, config=enabled_config(max_window_days=28))
        rejected = tight.execute(
            INTERNAL_PRINCIPAL,
            "get_training_overview",
            {"as_of": "2026-11-14", "window_weeks": 5},
        )
        assert rejected.error.field == "window_weeks"
        accepted = tight.execute(
            INTERNAL_PRINCIPAL,
            "get_training_overview",
            {"as_of": "2026-11-14", "window_weeks": 4},
        )
        assert accepted.ok
    finally:
        store.close()


def test_execution_is_deterministic():
    store = seed_store()
    try:
        first = _overview(store.connection).envelope.as_dict()
        second = _overview(store.connection).envelope.as_dict()
        assert first == second
        assert first["provenance"]["context_hash"] == second["provenance"]["context_hash"]
    finally:
        store.close()


def test_context_hash_changes_with_arguments():
    store = seed_store()
    try:
        wide = _overview(store.connection, window_weeks=4).envelope.provenance.context_hash
        narrow = _overview(store.connection, window_weeks=5).envelope.provenance.context_hash
        assert wide != narrow
    finally:
        store.close()


def test_execution_is_read_only():
    store = seed_store()
    try:
        conn = store.connection
        before = _counts(conn)
        changes = conn.total_changes
        assert _overview(conn).ok
        assert _counts(conn) == before
        assert conn.total_changes == changes
        assert conn.in_transaction is False
    finally:
        store.close()


def test_disabled_configuration_returns_unavailable():
    store = seed_store()
    try:
        disabled = service(store.connection, config=IntelligenceConfig(enabled=False))
        result = disabled.execute(INTERNAL_PRINCIPAL, "get_training_overview", {})
        assert result.error.code == "unavailable"
    finally:
        store.close()


def test_unknown_capability_is_not_found():
    store = seed_store()
    try:
        result = service(store.connection).execute(INTERNAL_PRINCIPAL, "get_nope", {})
        assert result.error.code == "not_found"
    finally:
        store.close()


def test_execution_requires_a_principal():
    store = seed_store()
    try:
        for principal in (None, {"identity": "x", "kind": "phone"}):
            with pytest.raises(TypeError):
                service(store.connection).execute(principal, "get_training_overview", {})
    finally:
        store.close()


def test_describe_lists_read_only_capabilities():
    store = seed_store()
    try:
        described = service(store.connection).describe()
        assert len(described) == 10
        assert all(entry["read_only"] is True for entry in described)
    finally:
        store.close()


def test_service_debug_line_has_metadata_not_argument_values(caplog):
    store = seed_store()
    try:
        with caplog.at_level(logging.DEBUG):
            _overview(store.connection)
        assert "capability=get_training_overview outcome=ok" in caplog.text
        assert "args=" in caplog.text
        assert "window_weeks" not in caplog.text
    finally:
        store.close()


# --- failure mapping through a private registry ---------------------------------


class _Request(CapabilityRequest):
    @classmethod
    def parse(cls, payload, *, config, today):
        return cls()

    def to_mapping(self):
        return {}


def _registry_with(handler) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        CapabilitySpec(
            name="get_probe",
            version="1.0.0",
            summary="Probe.",
            request_type=_Request,
            handler=handler,
        )
    )
    return registry


def test_unexpected_exception_becomes_internal_without_leaking(caplog):
    store = seed_store()
    try:
        def boom(conn, request, execution):
            raise RuntimeError("secret internals")

        probe = service(store.connection, registry=_registry_with(boom))
        with caplog.at_level(logging.INFO):
            result = probe.execute(INTERNAL_PRINCIPAL, "get_probe", {})
        assert result.error.code == "internal"
        assert "secret internals" not in result.error.message
        assert "intelligence capability get_probe raised" in caplog.text
    finally:
        store.close()


def test_invalid_envelope_becomes_internal(caplog):
    store = seed_store()
    try:
        def bad(conn, request, execution):
            base = valid_envelope()
            fact = dc.replace(base.facts["attendance"], method="made.up")
            return valid_envelope(facts={"attendance": fact})

        probe = service(store.connection, registry=_registry_with(bad))
        with caplog.at_level(logging.INFO):
            result = probe.execute(INTERNAL_PRINCIPAL, "get_probe", {})
        assert result.error.code == "internal"
        assert "invalid envelope" in caplog.text
    finally:
        store.close()


def test_unexpected_parser_failure_becomes_internal(caplog):
    store = seed_store()
    try:
        class BrokenRequest(CapabilityRequest):
            @classmethod
            def parse(cls, payload, *, config, today):
                raise RuntimeError("parser internals")

            def to_mapping(self):
                return {}

        registry = CapabilityRegistry()
        registry.register(
            CapabilitySpec(
                name="get_broken",
                version="1.0.0",
                summary="Broken.",
                request_type=BrokenRequest,
                handler=lambda conn, request, execution: None,
            )
        )
        probe = service(store.connection, registry=registry)
        with caplog.at_level(logging.INFO):
            result = probe.execute(INTERNAL_PRINCIPAL, "get_broken", {})
        assert result.error.code == "internal"
        assert "parser internals" not in result.error.message
        assert "failed to prepare" in caplog.text
    finally:
        store.close()


def test_expected_capability_failure_is_preserved():
    store = seed_store()
    try:
        def missing(conn, request, execution):
            raise IntelligenceError("not_found", "no such workout")

        probe = service(store.connection, registry=_registry_with(missing))
        result = probe.execute(INTERNAL_PRINCIPAL, "get_probe", {})
        assert result.error.code == "not_found"
        assert result.error.message == "no such workout"
    finally:
        store.close()


def test_result_is_either_success_or_failure():
    from strength_coach.intelligence.service import CapabilityResult

    with pytest.raises(ValueError):
        CapabilityResult()
    with pytest.raises(ValueError):
        CapabilityResult(envelope=valid_envelope(), error=IntelligenceError("internal", "x"))
    success = CapabilityResult.success(valid_envelope())
    assert success.ok and success.as_public()["ok"] is True
    failure = CapabilityResult.failure(IntelligenceError("not_found", "x"))
    assert not failure.ok and failure.as_public()["error"]["code"] == "not_found"
