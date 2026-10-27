"""5b modality registry: metadata, toggles and the existing-setting delegation."""

from __future__ import annotations

import pytest

from strength_coach import cli, modalities
from strength_coach.store import db, repositories


def test_modalities_have_classes_and_delegate_to_existing_flags():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        rows = modalities.state(conn, "2026-10-26")["modules"]
        by_id = {row["id"]: row for row in rows}
        assert by_id["mrv_cap"]["class"] == "guarded_safety"
        assert by_id["hard_constraints"]["class"] == "hard_safety"
        assert by_id["spinal"]["toggleable"] is False
        result = modalities.update(conn, "deload", enabled=False, effective_from="2026-10-26")
        again = modalities.show(conn, "deload", "2026-10-26")
    finally:
        store.close()
    assert result["enabled"] is False
    assert again["enabled"] is False
    assert again["enabled_source"] == "config" or again["enabled_source"] == "profile"


def test_modalities_cli_list_and_set(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main(["--db", str(path), "settings", "modalities", "list"]) == 0
    assert "mrv_cap" in capsys.readouterr().out
    assert cli.main([
        "--db", str(path), "settings", "modalities", "set", "deload", "enabled=off",
    ]) == 0
    assert "deload: off" in capsys.readouterr().out


def test_selection_and_high_intensity_are_not_plain_toggles():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        by_id = {row["id"]: row for row in modalities.state(conn, "2026-10-26")["modules"]}
        assert by_id["selection"]["enabled_source"] == "per_request"
        assert by_id["selection"]["toggleable"] is False
        assert by_id["high_intensity_exposure"]["class"] == "guarded_safety"
        assert by_id["high_intensity_exposure"]["toggleable"] is False
        with pytest.raises(ValueError, match="guarded"):
            modalities.update(
                conn, "high_intensity_exposure",
                factors={"high_intensity.override": {"lookback_days": 3}},
                effective_from="2026-10-26",
            )
    finally:
        store.close()


def test_volume_budget_toggle_uses_the_athlete_profile():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        repositories.append_athlete_profile(
            conn, effective_from="2026-10-26", primary_goal="strength",
            goal_rank=["strength"], focus_lifts=["squat"],
        )
        assert modalities.show(conn, "volume_budget", "2026-10-26")["enabled"] is False
        modalities.update(conn, "volume_budget", enabled=True)
        state = modalities.show(conn, "volume_budget", "2026-10-26")
    finally:
        store.close()
    assert state["enabled"] is True
    assert state["enabled_source"] == "athlete_profile"


def test_guarded_and_hard_modules_are_not_plain_toggles():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        with pytest.raises(ValueError, match="guarded"):
            modalities.update(conn, "mrv_cap", enabled=False)
        with pytest.raises(ValueError, match="not toggleable"):
            modalities.update(conn, "hard_constraints", enabled=False)
        result = modalities.update(
            conn, "mrv_cap", enabled=False, guard_confirmed=True,
            reason="reviewed cap", effective_from="2026-10-26",
        )
    finally:
        store.close()
    assert result["enabled"] is False