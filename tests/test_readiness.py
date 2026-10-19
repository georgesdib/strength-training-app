"""Readiness merge (OPEN-QUESTIONS Q6 default): most complete row wins, ties to latest.

The point of these tests is provenance: whichever row wins, the reason it won is recorded and
the losers stay visible.
"""

from __future__ import annotations

import json

import pandas as pd

from conftest import make_readiness
from strength_coach.ingest import readiness as rd

ALL_FIELDS = [
    "Sleep", "Energy", "Mood", "Soreness", "Stress", "Nutrition", "Hydration",
    "Squat_Readiness", "Bench_Readiness", "Deadlift_Readiness",
    "HRV", "RHR", "Weight", "Fat_Percent", "Grip_Strength",
]


def sparse(**keep):
    row = {field: "" for field in ALL_FIELDS}
    row.update(keep)
    return row


def test_most_complete_row_wins():
    frame = make_readiness([
        {**sparse(Date="2024-01-01", Sleep="3"), "Date": "2024-01-01"},
        {"Date": "2024-01-01", "Sleep": "4", "Energy": "2"},
    ])
    result = rd.build_readiness_day(frame)
    [day] = result.days.to_dict(orient="records")
    assert day["sleep"] == 4 and day["energy"] == 2
    note = json.loads(day["merge_note"])
    assert note["reason"] == "most_complete"
    assert note["considered"] == 2


def test_a_tie_goes_to_the_latest_row():
    frame = make_readiness([
        {"Date": "2024-01-01", "Sleep": "3"},
        {"Date": "2024-01-01", "Sleep": "5"},
    ])
    result = rd.build_readiness_day(frame)
    [day] = result.days.to_dict(orient="records")
    assert day["sleep"] == 5
    assert json.loads(day["merge_note"])["reason"] == "latest_tie"


def test_zero_sentinels_become_missing():
    frame = make_readiness([{"Date": "2024-01-01", "Weight": "0.0", "HRV": "0", "RHR": "0"}])
    result = rd.build_readiness_day(frame)
    [day] = result.days.to_dict(orient="records")
    assert day["bodyweight_kg"] is None or day["bodyweight_kg"] != day["bodyweight_kg"]
    assert day["hrv_ms"] is None or day["hrv_ms"] != day["hrv_ms"]


def test_rows_without_a_date_are_dropped():
    frame = make_readiness([{"Date": "(null)"}, {"Date": "2024-01-02"}])
    result = rd.build_readiness_day(frame)
    assert list(result.days["on_date"]) == ["2024-01-02"]


def test_duplicate_and_conflict_counts():
    frame = make_readiness([
        {"Date": "2024-01-01", "Sleep": "3"},
        {"Date": "2024-01-01", "Sleep": "4"},   # same date, conflicting value
        {"Date": "2024-01-02"},
    ])
    result = rd.build_readiness_day(frame)
    assert result.duplicate_rows == 1
    assert result.conflicting_dates == 1


def test_composite_is_left_empty_until_metrics_are_declared():
    result = rd.build_readiness_day(make_readiness([{"Date": "2024-01-01"}]))
    [day] = result.days.to_dict(orient="records")
    assert day["composite"] is None
    assert day["composite_basis"] is None

def test_grip_strength_is_imported_and_zero_is_missing():
    frame = make_readiness([
        {"Date": "2024-01-01", "Grip_Strength": "45.5"},
        {"Date": "2024-01-02", "Grip_Strength": "0"},
    ])
    result = rd.build_readiness_day(frame)
    by_date = result.days.set_index("on_date")
    assert by_date.loc["2024-01-01", "grip_strength_kg"] == 45.5
    assert pd.isna(by_date.loc["2024-01-02", "grip_strength_kg"])
