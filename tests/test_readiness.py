"""Readiness merge (OPEN-QUESTIONS Q6 default): most complete row wins, ties to latest.

The point of these tests is provenance: whichever row wins, the reason it won is recorded and
the losers stay visible.
"""

from __future__ import annotations

import json

import pytest
from conftest import make_readiness

from strength_coach.ingest import readiness as rd

ALL_FIELDS = [
    "Sleep", "Energy", "Mood", "Soreness", "Stress",
    "Squat_Readiness", "Bench_Readiness", "Deadlift_Readiness",
    "HRV", "RHR", "Weight", "Fat_Percent",
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


def test_composite_columns_are_not_part_of_the_imported_row():
    result = rd.build_readiness_day(make_readiness([{"Date": "2024-01-01"}]))
    [day] = result.days.to_dict(orient="records")
    assert "composite" not in day
    assert "composite_basis" not in day


def test_nutrition_and_hydration_are_ignored_not_rejected():
    # DEC-READINESS-20: old exports still carry the columns; the import must survive them
    # without turning them into readiness fields.
    frame = make_readiness([{"Date": "2024-01-01", "Nutrition": "2", "Hydration": "1"}])
    result = rd.build_readiness_day(frame)
    [day] = result.days.to_dict(orient="records")
    assert "nutrition" not in day
    assert "hydration" not in day


def test_a_reimport_preserves_historical_nutrition_values():
    # The columns stay for provenance; a re-import must not NULL them just because the
    # exporter no longer feeds them.
    from strength_coach.store import db, repositories

    with db.Store(":memory:") as store:
        conn = store.connection
        conn.execute(
            "INSERT INTO readiness_day (on_date, nutrition, hydration, fat_pct) "
            "VALUES ('2024-01-01', 3, 2, 21.0)"
        )
        frame = rd.build_readiness_day(make_readiness([{"Date": "2024-01-01"}])).days
        repositories.upsert_readiness_days(conn, frame)
        row = conn.execute(
            "SELECT nutrition, hydration, fat_pct FROM readiness_day "
            "WHERE on_date = '2024-01-01'"
        ).fetchone()
    assert tuple(row) == (3, 2, 21.0)


def test_the_removed_fields_are_not_accepted_as_manual_readings():
    from strength_coach.utils import readiness as readiness_utils

    for field in ("nutrition", "hydration", "fat_pct"):
        assert field not in readiness_utils.READINESS_FIELDS
        with pytest.raises(ValueError, match="unknown readiness field"):
            readiness_utils.validate(field, 4)


def test_the_baseline_readiness_summary_uses_the_five_scored_fields():
    # The raw export still carries Nutrition/Hydration (old files must import), but the
    # baseline profile must report only the fields readiness still accepts.
    from strength_coach.features import baseline

    summary = baseline.readiness_summary(
        make_readiness([{"Date": "2024-01-01"}]), as_of="2024-01-02", days=7
    )
    assert set(summary) == {"sleep", "energy", "mood", "soreness", "stress"}


def test_body_fat_measurements_are_extracted_from_the_export():
    # DEC-MEASURE-02: Fat_Percent feeds the measurement log; the last row with a value wins,
    # and the zero sentinel is not a measurement.
    frame = make_readiness([
        {"Date": "2024-01-01", "Fat_Percent": "22.5"},
        {"Date": "2024-01-01", "Fat_Percent": "23.5"},
        {"Date": "2024-01-02", "Fat_Percent": "0"},
    ])
    rows = rd.body_fat_measurements(frame)
    assert rows == [{"measured_on": "2024-01-01", "value": 23.5}]

def test_grip_strength_is_not_a_readiness_input():
    # DEC-GRIP-01: grip is capacity, tracked with `measure`; readiness no longer accepts it.
    from strength_coach.utils import readiness as readiness_utils

    assert "grip_strength_kg" not in readiness_utils.READINESS_FIELDS
    with pytest.raises(ValueError, match="unknown readiness field"):
        readiness_utils.validate("grip_strength_kg", 45.5)
