"""Step 4 settings profile precedence, append-only versions and snapshots."""

from __future__ import annotations

import json

import pytest

from strength_coach import cli, settings_profile
from strength_coach.prescribe import volume_budget
from strength_coach.store import db, repositories


def _store():
    return db.Store(":memory:")


def test_profile_precedence_and_effective_date():
    store = _store()
    try:
        conn = store.connection
        settings_profile.save(
            conn, set_values={"undulation.cycle_weeks": 3},
            effective_from="2026-10-26",
        )
        before = settings_profile.state(conn, "2026-10-25")
        after = settings_profile.state(conn, "2026-10-26")
        latest = settings_profile.latest(conn, "2026-10-26")
    finally:
        store.close()
    assert before["profile_id"] is None
    assert after["resolved"]["undulation.cycle_weeks"] == 3
    assert latest["overrides"] == {"undulation.cycle_weeks": 3}


def test_profile_budget_override_reaches_budget_config():
    store = _store()
    try:
        conn = store.connection
        settings_profile.save(
            conn, set_values={"budget": {"tolerance": 0.15}},
            effective_from="2026-10-26",
        )
        config = volume_budget.BudgetConfig.load(conn=conn, on_date="2026-10-26")
        settings = settings_profile.state(conn, "2026-10-26")
    finally:
        store.close()
    assert config.tolerance == 0.15
    assert settings["budget"]["tolerance"] == 0.15


def test_profile_rejects_guarded_and_unknown_keys():
    store = _store()
    try:
        conn = store.connection
        with pytest.raises(ValueError, match="guarded"):
            settings_profile.save(
                conn, set_values={"volume.apply_mrv_cap": False},
                effective_from="2026-10-26",
            )
        with pytest.raises(ValueError, match="unknown settings key"):
            settings_profile.save(
                conn, set_values={"not.a.key": 1}, effective_from="2026-10-26",
            )
    finally:
        store.close()


def test_profile_versions_are_append_only_and_keep_the_last_map():
    store = _store()
    try:
        conn = store.connection
        settings_profile.save(
            conn, set_values={"undulation.cycle_weeks": 3},
            effective_from="2026-10-26",
        )
        settings_profile.save(
            conn, set_values={"e1rm.window_days": 56},
            effective_from="2026-10-27",
        )
        settings_profile.save(
            conn, set_values=None, unset=["undulation.cycle_weeks"],
            effective_from="2026-10-28",
        )
        latest = settings_profile.latest(conn, "2026-10-28")
        history = settings_profile.history(conn)
        with pytest.raises(Exception):
            conn.execute("UPDATE settings_profile SET effective_from='x'")
    finally:
        store.close()
    assert latest["overrides"] == {"e1rm.window_days": 56}
    assert len(history) == 3


def test_cli_settings_profile_set_and_show(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main([
        "--db", str(path), "settings", "profile", "set",
        "undulation.cycle_weeks=3", "budget={\"tolerance\":0.15}",
    ]) == 0
    assert cli.main(["--db", str(path), "settings", "profile", "show"]) == 0
    out = capsys.readouterr().out
    assert "overrides" in out and "undulation.cycle_weeks" in out
    assert "0.15" in out


def test_feature_settings_apply_profile_values_including_the_dup_table():
    store = _store()
    try:
        conn = store.connection
        settings_profile.save(
            conn,
            set_values={
                "undulation.weeks": {"1": {"squat": "strength"}},
                "undulation.cycle_weeks": 1,
                "undulation.maximal_hinge_allowed": True,
                "deload.prescription.rir_add": 2,
                "e1rm.window_days": 63,
            },
            effective_from="2026-10-26",
        )
        resolved = settings_profile.feature_settings(conn, "2026-10-26")
    finally:
        store.close()
    assert resolved.undulation.cycle_weeks == 1
    assert resolved.maximal_hinge_allowed is True
    assert resolved.undulation.weeks[1]["squat"] == "strength"
    assert resolved.deload.rir_add == 2
    assert resolved.thresholds.e1rm_window_days == 63


def test_guarded_settings_require_confirmation_and_reason():
    store = _store()
    try:
        conn = store.connection
        settings_profile.save(
            conn,
            set_values={"volume.apply_mrv_cap": False},
            effective_from="2026-10-26",
        )
    except ValueError as exc:
        assert "guarded" in str(exc)
    else:
        raise AssertionError("guarded write should fail")
    try:
        settings_profile.save(
            conn,
            set_values={"volume.apply_mrv_cap": False},
            effective_from="2026-10-26",
            guard_confirmed=True,
        )
    except ValueError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("guarded write needs a reason")
    result = settings_profile.save(
        conn,
        set_values={
            "volume.apply_mrv_cap": False,
            "spinal.override": {"cap": 5, "costs": {"rdl": 1}},
        },
        effective_from="2026-10-26",
        guard_confirmed=True,
        reason="back history changed",
    )
    try:
        resolved = settings_profile.feature_settings(conn, "2026-10-26")
    finally:
        store.close()
    assert result["reason"] == "back history changed"
    assert result["overrides"]["volume.apply_mrv_cap"] is False
    assert resolved.spinal_cap == 5
    assert resolved.spinal_costs["rdl"] == 1


def test_5c_feature_settings_and_guarded_exposure_override():
    store = _store()
    try:
        conn = store.connection
        settings_profile.save(
            conn,
            set_values={
                "continuity.apply": False,
                "warmup.percents": [0.5, 0.8],
                "test_cadence.schemes": ["3RM"],
                "high_intensity.override": {
                    "lookback_days": 3,
                    "windows_hours": {"upper": 12},
                },
            },
            effective_from="2026-10-26",
            guard_confirmed=True,
            reason="exposure review",
        )
        resolved = settings_profile.feature_settings(conn, "2026-10-26")
    finally:
        store.close()
    assert resolved.continuity.apply is False
    assert resolved.warmup.percents == (0.5, 0.8)
    assert resolved.test_cadence.schemes == ("3RM",)
    assert resolved.exposure.lookback_days == 3
    assert resolved.exposure.windows["upper"] == 12


def test_prescription_snapshot_is_written():
    store = _store()
    try:
        conn = store.connection
        settings_profile.save(
            conn, set_values={"budget": {"tolerance": 0.15}},
            effective_from="2026-10-26",
        )
        run = repositories.start_run(conn, input_hash="settings", code_version="test")
        repositories.append_prescription(
            conn, prescription_id="p-settings", run_id=run.run_id,
            for_date="2026-10-26", session_type="squat", fallback_level="full",
            rule_document_version="test", calibration_ids=(),
            approved_by="deterministic", items=[],
        )
        settings_profile.snapshot_prescription(conn, "p-settings", "2026-10-26")
        snapshot = repositories.prescription_profile(conn, "p-settings")
    finally:
        store.close()
    assert snapshot is not None
    decoded = json.loads(snapshot["settings_json"])
    assert decoded["budget"]["tolerance"] == 0.15
    assert decoded["registry"]["undulation.cycle_weeks"] == 4
    assert snapshot["config_hash"]