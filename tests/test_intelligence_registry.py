"""Capability registration and request-validation helpers."""

from __future__ import annotations

import datetime as dt

import pytest

from strength_coach.intelligence import CAPABILITIES
from strength_coach.intelligence.errors import IntelligenceError
from strength_coach.intelligence.registry import (
    CapabilityRegistry,
    CapabilityRequest,
    CapabilitySpec,
    payload_mapping,
    reject_unknown,
    require_date,
    require_int,
)


class _Request(CapabilityRequest):
    @classmethod
    def parse(cls, payload, *, config, today):  # pragma: no cover - registration only
        return cls()

    def to_mapping(self):
        return {}


def _spec(**overrides):
    values = {
        "name": "get_example",
        "version": "1.0.0",
        "summary": "Example capability.",
        "request_type": _Request,
        "handler": lambda conn, request, execution: None,
    }
    values.update(overrides)
    return CapabilitySpec(**values)


def test_shipped_registry_lists_the_overview_capability():
    assert CAPABILITIES.names() == ("get_training_overview",)


def test_describe_reports_version_summary_and_read_only():
    described = CAPABILITIES.describe()
    assert len(described) == 1
    entry = described[0]
    assert entry["name"] == "get_training_overview"
    assert entry["version"] == "1.0.0"
    assert entry["read_only"] is True
    assert "1-52 weeks" in str(entry["summary"])


def test_names_are_sorted_and_stable():
    registry = CapabilityRegistry()
    registry.register(_spec(name="get_zeta"))
    registry.register(_spec(name="compare_alpha"))
    registry.register(_spec(name="get_alpha"))
    assert registry.names() == ("compare_alpha", "get_alpha", "get_zeta")


def test_unknown_capability_is_not_found():
    with pytest.raises(IntelligenceError) as error:
        CapabilityRegistry().get("get_missing")
    assert error.value.code == "not_found"


def test_duplicate_name_is_rejected():
    registry = CapabilityRegistry()
    registry.register(_spec())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_spec())


@pytest.mark.parametrize(
    "name",
    ["create_workout", "update_plan", "delete_session", "get_Bad", "set_state", "overview"],
)
def test_mutating_or_malformed_names_are_rejected(name):
    with pytest.raises(ValueError, match="capability name"):
        CapabilityRegistry().register(_spec(name=name))


@pytest.mark.parametrize("version", ["1", "1.0", "v1.0.0", "1.0.0-beta"])
def test_versions_must_be_major_minor_patch(version):
    with pytest.raises(ValueError, match="capability version"):
        CapabilityRegistry().register(_spec(version=version))


def test_read_only_is_required():
    with pytest.raises(ValueError, match="read-only"):
        CapabilityRegistry().register(_spec(read_only=False))


def test_request_type_must_be_a_capability_request():
    with pytest.raises(ValueError, match="request_type"):
        CapabilityRegistry().register(_spec(request_type=dict))


def test_summary_is_required():
    with pytest.raises(ValueError, match="summary"):
        CapabilityRegistry().register(_spec(summary=""))


def test_payload_mapping_rejects_non_objects():
    for payload in ([], "x", 3, None):
        with pytest.raises(IntelligenceError) as error:
            payload_mapping(payload)
        assert error.value.code == "invalid_argument"


def test_payload_mapping_rejects_non_string_keys():
    with pytest.raises(IntelligenceError):
        payload_mapping({1: "x"})


def test_reject_unknown_names_the_first_field():
    with pytest.raises(IntelligenceError) as error:
        reject_unknown({"as_of": "2026-11-14", "bogus": 1}, ("as_of",))
    assert error.value.code == "invalid_argument"
    assert error.value.field == "bogus"


@pytest.mark.parametrize("value", [True, False, 0, 53, "4", 4.0, None])
def test_require_int_rejects_out_of_range_and_non_integers(value):
    with pytest.raises(IntelligenceError) as error:
        require_int(value, "window_weeks", minimum=1, maximum=52)
    assert error.value.code == "invalid_argument"
    assert error.value.field == "window_weeks"


def test_require_int_accepts_the_boundaries():
    assert require_int(1, "window_weeks", minimum=1, maximum=52) == 1
    assert require_int(52, "window_weeks", minimum=1, maximum=52) == 52


def test_require_date_parses_and_rejects():
    assert require_date("2026-11-14", "as_of") == dt.date(2026, 11, 14)
    for value in ("14/11/2026", "2026-13-01", 20261114, None):
        with pytest.raises(IntelligenceError) as error:
            require_date(value, "as_of")
        assert error.value.field == "as_of"
