"""Phase 0 tool: read-only, deterministic, and it must not invent a verdict."""

from __future__ import annotations

import pandas as pd
import pytest

from strength_coach.store import db
from tools.performance_carryover import (
    _modified,
    _weighted_risk_difference,
    add_expected_velocity,
    analyse,
    analyse_h3,
    decide,
    fingerprint,
    main,
    make_pairs,
    mark_constant_load,
    prepare,
    render_markdown,
)


def _rows(*records: dict) -> pd.DataFrame:
    return pd.DataFrame(list(records))


def test_modified_treats_sql_null_and_nan_as_unknown():
    assert _modified(None, None) is None
    assert _modified(float("nan"), float("nan")) is None
    assert _modified('{"fallback_level": "full"}', None) is False
    assert _modified('{"fallback_level": "fatigue_reduced"}', None) is True
    assert _modified('{"fallback_level": "full"}', '{"items": []}') is True


# --- expected velocity -------------------------------------------------------


def test_expected_velocity_holds_out_the_set_session():
    records = []
    for _ in range(30):
        records.append({"session_id": "a", "exercise_id": "bench_press", "reps": 3,
                        "velocity": 0.10, "in_window": True})
    for session in ("b", "c", "d"):
        for _ in range(4):
            records.append({"session_id": session, "exercise_id": "bench_press", "reps": 3,
                            "velocity": 0.50, "in_window": True})
    frame = add_expected_velocity(_rows(*records))

    session_a = frame[frame["session_id"] == "a"]
    session_b = frame[frame["session_id"] == "b"]

    # A session never contributes to its own expectation.
    assert session_a["centre"].iloc[0] == pytest.approx(0.50)
    # The held-out session does drag the other sessions, which is the point of the design.
    assert session_b["centre"].iloc[0] == pytest.approx(0.10)
    assert session_a["u"].iloc[0] < -2.0


def test_expected_velocity_is_absent_below_the_ladder():
    records = [
        {"session_id": session, "exercise_id": "bench_press", "reps": 3,
         "velocity": 0.30, "in_window": True}
        for session in ("a", "b") for _ in range(20)
    ]
    frame = add_expected_velocity(_rows(*records))
    assert frame["u"].isna().all()


# --- eligibility and groups --------------------------------------------------


def test_prepare_applies_the_eligibility_rules():
    good = {"session_id": "s", "exercise_id": "bench_press", "occurred_on": "2026-01-05",
            "set_id": 1, "raw_id": 1, "velocity": 0.5, "is_working_set": 1, "rir": 2,
            "reps": 3, "load_kg": 100.0, "load_basis": "external", "flags": "[]"}
    records = [
        good,
        {**good, "set_id": 2, "raw_id": 2, "is_working_set": 0},
        {**good, "set_id": 3, "raw_id": 3, "rir": 6},
        {**good, "set_id": 4, "raw_id": 4, "reps": 12},
        {**good, "set_id": 5, "raw_id": 5, "load_basis": "unknown"},
        {**good, "set_id": 6, "raw_id": 6, "flags": "[\"REPS_TYPO\"]"},
        {**good, "set_id": 7, "raw_id": 7, "load_kg": 20.0},
    ]
    prepared, excluded = prepare(_rows(*records))

    assert len(prepared) == 1
    assert prepared.iloc[0]["set_id"] == 1
    for reason in ("not_working_set", "no_effort_rating", "reps_out_of_range",
                   "load_basis_unknown", "reps_typo", "load_too_light"):
        assert excluded[reason] == 1, reason


def test_constant_load_groups_ignore_back_offs():
    frame = _rows(
        {"session_id": "s1", "exercise_id": "x", "load_kg": 100.0},
        {"session_id": "s1", "exercise_id": "x", "load_kg": 100.5},
        {"session_id": "s2", "exercise_id": "x", "load_kg": 120.0},
        {"session_id": "s2", "exercise_id": "x", "load_kg": 100.0},
    )
    out = mark_constant_load(frame)
    assert out[out["session_id"] == "s1"]["constant_load"].all()
    assert not out[out["session_id"] == "s2"]["constant_load"].any()


# --- H1 primitives -----------------------------------------------------------


def test_pairs_use_consecutive_eligible_verdicts():
    frame = _rows(
        {"session_id": "s", "exercise_id": "x", "position": 1, "u": -3.0,
         "in_window": True, "constant_load": True},
        {"session_id": "s", "exercise_id": "x", "position": 2, "u": -2.5,
         "in_window": True, "constant_load": True},
        {"session_id": "s", "exercise_id": "x", "position": 3, "u": 0.0,
         "in_window": True, "constant_load": True},
    )
    pairs = make_pairs(frame)

    assert len(pairs) == 2
    assert pairs[0]["trigger"] is True
    assert pairs[0]["next_below"] is True
    assert pairs[1]["position_next"] == 3


def test_weighted_risk_difference_is_stratum_weighted():
    rows = [
        {"stratum": "2-3", "trigger": True, "next_below": True},
        {"stratum": "2-3", "trigger": True, "next_below": False},
        {"stratum": "2-3", "trigger": False, "next_below": False},
        {"stratum": "2-3", "trigger": False, "next_below": False},
    ]
    assert _weighted_risk_difference(rows) == pytest.approx(0.5)


# --- H3 ----------------------------------------------------------------------


def test_dual_channel_agreement_and_kappa_can_be_perfect():
    frame = _rows(
        *[
            {"u": 0.0, "rir_value": 2, "rir_low": 2, "rir_high": 3},
            {"u": -3.0, "rir_value": 1, "rir_low": 2, "rir_high": 3},
            {"u": 3.0, "rir_value": 4, "rir_low": 2, "rir_high": 3},
        ]
    )
    result = analyse_h3(frame)
    assert result["sets"] == 3
    assert result["agreement"] == pytest.approx(1.0)
    assert result["kappa"] == pytest.approx(1.0)


def test_dual_channel_kappa_is_undefined_with_one_category():
    frame = _rows({"u": 0.0, "rir_value": 2, "rir_low": 2, "rir_high": 3})
    result = analyse_h3(frame)
    assert result["agreement"] == pytest.approx(1.0)
    assert result["kappa"] is None


# --- verdict -----------------------------------------------------------------


def _report(*, session_lifts=30, trigger_sets=20, rate=0.2, rd=0.2, rd_low=0.05,
            odds=2.0, odds_low=1.2, h2_pairs=12, h2_difference=-0.8, h2_low=-1.4,
            agreement=0.6, kappa=0.2) -> dict:
    return {
        "coverage": {"session_lifts": session_lifts, "trigger_sets": trigger_sets,
                     "trigger_rate": rate},
        "h1": {
            "risk_difference": {"estimate": rd, "ci": {"low": rd_low, "high": 0.4}},
            "odds_ratio": {"estimate": odds, "low": odds_low, "high": 3.0,
                           "continuity_corrected": False},
        },
        "h2": {"pairs": h2_pairs, "difference_mad": h2_difference,
               "ci": {"low": h2_low, "high": -0.2}},
        "h3": {"agreement": agreement, "kappa": kappa},
    }


def test_decide_pass_requires_every_criterion():
    assert decide(_report())["code"] == "pass"


def test_decide_narrow_when_persistence_fails():
    assert decide(_report(h2_pairs=3))["code"] == "narrow"


def test_decide_persistence_requires_the_worse_direction():
    # A trigger session followed by a BETTER session is not persistence.
    assert decide(_report(h2_difference=0.8, h2_low=-0.2))["code"] == "narrow"


def test_decide_stop_when_carry_over_fails():
    assert decide(_report(rd=0.0, rd_low=-0.1, odds=1.0, odds_low=0.7))["code"] == "stop"


def test_decide_stop_when_channels_disagree():
    assert decide(_report(agreement=0.2, kappa=0.0))["code"] == "stop"


def test_decide_inconclusive_on_thin_yield():
    assert decide(_report(session_lifts=5, trigger_sets=2))["code"] == "inconclusive"


# --- database smoke ----------------------------------------------------------


def _empty_database(tmp_path) -> str:
    path = tmp_path / "coach.db"
    db.Store(str(path)).close()
    return str(path)


def test_empty_database_is_readable_and_inconclusive(tmp_path):
    path = _empty_database(tmp_path)
    report = analyse(path)

    assert report["coverage"]["sets_read"] == 0
    assert report["verdict"]["code"] == "inconclusive"
    assert "inconclusive" in render_markdown(report)


def test_analysis_leaves_the_database_untouched(tmp_path):
    path = _empty_database(tmp_path)
    before = fingerprint(path)
    analyse(path)
    assert fingerprint(path) == before


def test_tool_refuses_to_write_outside_private(tmp_path, capsys):
    path = _empty_database(tmp_path)
    with pytest.raises(SystemExit, match="private"):
        main(["--db", path, "--out", str(tmp_path / "out.md"),
              "--json", str(tmp_path / "out.json")])
    capsys.readouterr()
    assert not (tmp_path / "out.md").exists()
