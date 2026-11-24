"""Persistence follow-up: one look, one label, and it must not invent carry-over."""

from __future__ import annotations

import pandas as pd
import pytest

from strength_coach.store import db
from tools.performance_persistence import (
    _gate,
    _model,
    _time_span_years,
    analyse,
    assign_lift_levels,
    build_pairs,
    build_session_lifts,
    build_triplets,
    fingerprint,
    main,
    render_markdown,
)


def _lifts(*records: dict) -> list[dict]:
    return [
        {"session_id": record["session_id"], "exercise_id": record.get("exercise_id", "bench_press"),
         "date": record["date"], "mean_u": record["mean_u"], "n_sets": record.get("n_sets", 3),
         "modified": record.get("modified", False)}
        for record in records
    ]


def test_time_span_is_years_and_handles_missing_dates():
    import datetime as dt

    origin = dt.date(2024, 1, 1)
    assert _time_span_years(origin, ["2024-01-01", "2025-01-01"]) == pytest.approx(1.0, abs=0.01)
    assert _time_span_years(origin, []) is None
    assert _time_span_years(None, ["2025-01-01"]) is None


# --- units -------------------------------------------------------------------


def test_session_lifts_average_eligible_sets():
    frame = pd.DataFrame([
        {"session_id": "s1", "exercise_id": "bench_press", "occurred_on": "2026-01-01",
         "u": -1.0, "modified": False},
        {"session_id": "s1", "exercise_id": "bench_press", "occurred_on": "2026-01-01",
         "u": 1.0, "modified": False},
        {"session_id": "s2", "exercise_id": "bench_press", "occurred_on": "2026-01-03",
         "u": 0.0, "modified": True},
    ])
    lifts = build_session_lifts(frame)
    assert len(lifts) == 2
    assert lifts[0]["mean_u"] == pytest.approx(0.0)
    assert lifts[0]["n_sets"] == 2
    assert lifts[1]["modified"] is True


def test_pairs_take_the_earliest_next_within_the_window():
    lifts = _lifts(
        {"session_id": "a", "date": "2026-01-01", "mean_u": -1.0},
        {"session_id": "b", "date": "2026-01-08", "mean_u": 0.0},
        {"session_id": "c", "date": "2026-01-15", "mean_u": 1.0},
        {"session_id": "d", "date": "2026-03-01", "mean_u": -2.0},
    )
    pairs = build_pairs(lifts)

    assert [pair["session_id"] for pair in pairs] == ["a", "b"]
    assert pairs[0]["u_next"] == pytest.approx(0.0)
    assert pairs[0]["days"] == 7
    # c's only later exposure is far outside 14 days, so it has no pair.
    assert not any(pair["session_id"] == "c" for pair in pairs)


def test_triplets_require_three_consecutive_exposures():
    lifts = _lifts(
        {"session_id": "a", "date": "2026-01-01", "mean_u": -1.0},
        {"session_id": "b", "date": "2026-01-05", "mean_u": 0.0},
        {"session_id": "c", "date": "2026-01-10", "mean_u": 1.0},
    )
    triplets = build_triplets(lifts)
    assert len(triplets) == 1
    assert triplets[0]["u_prev"] == pytest.approx(-1.0)
    assert triplets[0]["u_t"] == pytest.approx(0.0)

    spaced = _lifts(
        {"session_id": "a", "date": "2026-01-01", "mean_u": -1.0},
        {"session_id": "b", "date": "2026-02-01", "mean_u": 0.0},
        {"session_id": "c", "date": "2026-02-05", "mean_u": 1.0},
    )
    assert build_triplets(spaced) == []


def test_lift_levels_collapse_sparse_exercises():
    family_of = {"bench_press": "bench", "bench_press_narrow": "bench", "squat": "squat"}
    rows = [
        {"exercise_id": "bench_press"} for _ in range(3)
    ] + [
        {"exercise_id": "bench_press_narrow"} for _ in range(2)
    ] + [
        {"exercise_id": "squat"} for _ in range(2)
    ]
    levels = assign_lift_levels(rows, family_of)
    assert levels[:3] == ["bench_press"] * 3
    assert levels[3:] == ["bench"] * 2 + ["other"] * 2


# --- model and label ---------------------------------------------------------


def _pair_rows(**overrides) -> list[dict]:
    rows = []
    for index, u_t in enumerate((-2.0, -1.0, 0.0, 1.0, 2.0, 0.0)):
        rows.append({
            "session_id": f"s{index}",
            "exercise_id": "bench_press",
            "date": f"2026-01-{index + 1:02d}",
            "u_t": u_t,
            "u_next": 0.5 * u_t,
            "days": 7,
            "n_sets": 3,
            "time": 0.0,
            "lift_level": "bench_press",
            "modified": False,
            **overrides,
        })
    return rows


def test_model_recovers_a_known_slope():
    result = _model(_pair_rows())
    assert result is not None
    assert result["beta_u_t"] == pytest.approx(0.5, abs=1e-6)
    assert result["n"] == 6


def _report(*, pairs=60, sessions=25, exercises=4, beta=0.5, low=0.2,
            p2=None) -> dict:
    return {
        "coverage": {"pairs": pairs, "sessions": sessions, "exercises_with_pairs": exercises},
        "p1": {"beta_u_t": beta, "cluster_ci": {"low": low, "high": 0.9}},
        "p2": p2,
    }


def test_label_is_inconclusive_without_yield():
    assert _gate(_report(pairs=10))["code"] == "inconclusive"


def test_label_is_not_confirmed_below_the_beta_gate():
    assert _gate(_report(beta=0.1, low=-0.1))["code"] == "not-confirmed"


def test_label_is_carry_over_without_p2():
    assert _gate(_report())["code"] == "carry-over"


def test_label_is_stable_level_when_the_latest_deviation_adds_nothing():
    p2 = {"beta_u_t": 0.05, "beta_u_prev": 0.4}
    assert _gate(_report(p2=p2))["code"] == "stable-level"


def test_label_falls_back_when_p2_is_uninterpretable():
    p2 = {"beta_u_t": 0.05, "beta_u_prev": 0.1}
    assert _gate(_report(p2=p2))["code"] == "not-confirmed"


# --- database smoke ----------------------------------------------------------


def _empty_database(tmp_path) -> str:
    path = tmp_path / "coach.db"
    db.Store(str(path)).close()
    return str(path)


def test_empty_database_is_inconclusive(tmp_path):
    path = _empty_database(tmp_path)
    report = analyse(path)

    assert report["coverage"]["pairs"] == 0
    assert report["label"]["code"] == "inconclusive"
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
