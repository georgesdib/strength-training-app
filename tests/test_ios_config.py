"""iOS facade config: validation, atomic edit and effective/source reporting."""

from __future__ import annotations

import pytest

from strength_coach import ios_config

BASE = """# iOS facade header
mutations_enabled: true
issued_plan_ttl_seconds: 3600
plan_request_ttl_seconds: 900
receipt_retention_days: 30
"""


def _write(tmp_path, text: str = BASE):
    path = tmp_path / "ios.v1.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_describe_reports_effective_values_source_and_reload(tmp_path):
    path = _write(tmp_path)

    data = ios_config.describe_config(path)

    assert data["effective"] == {
        "mutations_enabled": True,
        "watch_enabled": False,
        "issued_plan_ttl_seconds": 3600,
        "plan_request_ttl_seconds": 900,
        "receipt_retention_days": 30,
        "idle_warn_seconds": 10800,
        "idle_abandon_seconds": 86400,
    }
    assert data["source"] == str(path)
    assert data["reload"] == "per request"
    assert data["restart_required"] is False
    assert data["ranges"]["issued_plan_ttl_seconds"] == {"kind": "int", "min": 60, "max": 86400}


def test_save_updates_only_known_keys_and_keeps_comments(tmp_path):
    path = _write(tmp_path)

    data = ios_config.save_config(
        {
            "mutations_enabled": False,
            "issued_plan_ttl_seconds": 7200,
            "plan_request_ttl_seconds": 1200,
            "receipt_retention_days": 14,
        },
        path,
    )

    text = path.read_text(encoding="utf-8")
    assert "# iOS facade header" in text
    assert "mutations_enabled: false" in text
    assert "issued_plan_ttl_seconds: 7200" in text
    assert "plan_request_ttl_seconds: 1200" in text
    assert "receipt_retention_days: 14" in text
    assert data["effective"]["mutations_enabled"] is False
    assert ios_config.load_config(path).issued_plan_ttl_seconds == 7200


def test_save_appends_a_missing_optional_key(tmp_path):
    path = _write(
        tmp_path,
        "mutations_enabled: true\nissued_plan_ttl_seconds: 3600\nreceipt_retention_days: 30\n",
    )

    ios_config.save_config({"plan_request_ttl_seconds": 900}, path)

    text = path.read_text(encoding="utf-8")
    assert "plan_request_ttl_seconds: 900" in text


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"issued_plan_ttl_seconds": 59}, "issued_plan_ttl_seconds"),
        ({"issued_plan_ttl_seconds": 86401}, "issued_plan_ttl_seconds"),
        ({"plan_request_ttl_seconds": 3601}, "plan_request_ttl_seconds"),
        ({"receipt_retention_days": 0}, "receipt_retention_days"),
        ({"mutations_enabled": "true"}, "mutations_enabled"),
        ({"issued_plan_ttl_seconds": True}, "issued_plan_ttl_seconds"),
        ({"unknown": 1}, "unknown"),
    ],
)
def test_save_rejects_invalid_values_and_leaves_the_file_unchanged(tmp_path, values, message):
    path = _write(tmp_path)
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ios_config.IOSConfigError, match=message):
        ios_config.save_config(values, path)

    assert path.read_text(encoding="utf-8") == before


def test_save_rejects_duplicate_keys(tmp_path):
    path = _write(
        tmp_path,
        "mutations_enabled: true\nmutations_enabled: false\n"
        "issued_plan_ttl_seconds: 3600\nreceipt_retention_days: 30\n",
    )

    with pytest.raises(ios_config.IOSConfigError, match="duplicate mutations_enabled"):
        ios_config.save_config({"issued_plan_ttl_seconds": 7200}, path)
