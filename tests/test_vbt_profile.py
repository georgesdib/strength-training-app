"""Read-only VBT load-velocity profile: fit gates and the display-only e1RM."""

import pandas as pd
import pytest
from conftest import make_readiness, make_training

from strength_coach.features import derived
from strength_coach.features import vbt_profile as profile


def enriched(rows: list[dict]) -> pd.DataFrame:
    result = clean_sets(rows)
    return derived.enrich(result)


def clean_sets(rows: list[dict]):
    from strength_coach.ingest import clean

    return clean.build_clean_sets(make_training(rows), make_readiness([{}])).sets


def bench_rows(loads, velocity, *, rir="2", days=("2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22")):
    rows = []
    for day in days:
        for load in loads:
            rows.append({
                "Date": day,
                "Exercise": "Competition Bench Press",
                "Weight_Used": str(load),
                "Reps_Done": "3",
                "RIR": rir,
                "Avg_velocity": f"{velocity(load):.6f}",
            })
    return rows


def build(rows, **kwargs):
    return profile.build(enriched(rows), "bench_press", family="horizontal_push", **kwargs)


def test_a_clean_line_is_fitted_and_an_e1rm_is_implied():
    data = build(bench_rows([80, 95, 110, 125], lambda load: 1.05 - 0.0045 * load))
    assert data.status == "fitted"
    assert data.rep_count == 3
    assert (data.n_sets, data.n_sessions, data.n_loads) == (16, 4, 4)
    assert data.slope < 0
    assert data.r2 is not None and data.r2 > 0.99
    assert len(data.points) == 16
    # (0.17 - 1.05) / -0.0045 = 195.6 kg; inside the 2.5x-max-load guard.
    assert abs(data.e1rm_kg - 195.6) < 1.5
    assert data.e1rm_mvt_mps == 0.17


def test_rir_is_a_covariate_when_it_varies():
    rows = []
    for day in ("2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22"):
        for load in (80, 95, 110, 125):
            for rir in (1, 3):
                rows.append({
                    "Date": day,
                    "Exercise": "Competition Bench Press",
                    "Weight_Used": str(load),
                    "Reps_Done": "3",
                    "RIR": str(rir),
                    "Avg_velocity": f"{0.95 - 0.004 * load - 0.02 * rir:.6f}",
                })
    data = profile.build(enriched(rows), "bench_press", family="horizontal_push")
    assert data.status == "fitted"
    assert data.rir_coef is not None
    assert abs(data.rir_coef + 0.02) < 0.002


def test_too_few_sets_is_refused_not_guessed():
    data = build(bench_rows([80, 95, 110], lambda load: 1.0 - 0.004 * load,
                            days=("2024-01-01",)))
    assert data.status == "insufficient"
    assert "12" in data.reason


def test_a_narrow_load_range_is_refused():
    data = build(bench_rows([80, 82, 84], lambda load: 1.0 - 0.004 * load))
    assert data.status == "insufficient"
    assert "narrow" in data.reason


def test_an_implausible_extrapolation_yields_no_e1rm():
    data = build(bench_rows([80, 95, 110, 125], lambda load: 0.55 - 0.0005 * load))
    assert data.status == "fitted"
    assert data.e1rm_kg is None


def test_a_rising_line_is_not_a_load_velocity_profile():
    data = build(bench_rows([80, 95, 110, 125], lambda load: 0.2 + 0.002 * load))
    assert data.status == "insufficient"
    assert data.reason == "no usable slope"


def test_available_reps_lists_the_fittable_rep_counts():
    rows = bench_rows([80, 95, 110, 125], lambda load: 1.05 - 0.0045 * load)
    rows += [
        {"Date": "2024-02-01", "Exercise": "Competition Bench Press",
         "Weight_Used": "100", "Reps_Done": "5", "RIR": "2", "Avg_velocity": "0.600000"}
    ]
    data = profile.build(enriched(rows), "bench_press", family="horizontal_push")
    by_reps = {item["reps"]: item for item in data.available_reps}
    assert by_reps[3]["fitted"] is True
    assert by_reps[5]["fitted"] is False
    assert data.rep_count == 3


def weekly_rows(weeks: int, *, start="2024-01-01", offset_weeks: int = 0):
    import datetime as dt

    first = dt.date.fromisoformat(start)
    rows = []
    for week in range(offset_weeks, offset_weeks + weeks):
        day = (first + dt.timedelta(days=7 * week)).isoformat()
        for load in (80, 95, 110, 125):
            velocity = 1.05 + 0.002 * week - 0.0045 * load
            rows.append({
                "Date": day,
                "Exercise": "Competition Bench Press",
                "Weight_Used": str(load),
                "Reps_Done": "3",
                "RIR": "2",
                "Avg_velocity": f"{velocity:.6f}",
            })
    return rows


def test_e1rm_series_is_point_in_time():
    base_rows = weekly_rows(16)
    base = profile.build(enriched(base_rows), "bench_press", family="horizontal_push")
    assert len(base.e1rm_series) >= 5
    dates = [point["date"] for point in base.e1rm_series]
    assert dates == sorted(dates)
    assert all(point["n_sets"] >= 12 for point in base.e1rm_series)

    # Four much heavier, faster future weeks must not move any earlier value.
    future = weekly_rows(4, offset_weeks=16)
    for row in future:
        row["Weight_Used"] = str(float(row["Weight_Used"]) + 40)
        row["Avg_velocity"] = f"{float(row['Avg_velocity']) + 0.10:.6f}"
    extended = profile.build(enriched(base_rows + future), "bench_press", family="horizontal_push")
    earlier = {point["date"]: point["e1rm_kg"] for point in base.e1rm_series}
    widened = {point["date"]: point["e1rm_kg"] for point in extended.e1rm_series}
    for date_value, e1rm in earlier.items():
        assert widened[date_value] == e1rm


def test_e1rm_series_is_capped_and_chronological():
    data = profile.build(enriched(weekly_rows(60)), "bench_press", family="horizontal_push")
    assert len(data.e1rm_series) <= 52
    assert [point["date"] for point in data.e1rm_series] == sorted(
        point["date"] for point in data.e1rm_series
    )


def test_the_pooled_model_is_reported_across_rep_counts():
    rows = []
    for day in ("2024-01-01", "2024-01-08", "2024-01-15"):
        for load in (80, 95, 110, 125):
            for reps in (2, 3):
                rows.append({
                    "Date": day, "Exercise": "Competition Bench Press",
                    "Weight_Used": str(load), "Reps_Done": str(reps), "RIR": "2",
                    "Avg_velocity": f"{1.10 - 0.0045 * load - 0.03 * reps:.6f}",
                })
    data = profile.build(
        enriched(rows), "bench_press", family="horizontal_push", rep_count=1,
    )
    assert data.status == "insufficient"        # no 1-rep sets, so no 1-rep line
    assert data.pooled_status == "fitted"
    assert data.pooled_rep_coef == pytest.approx(-0.03, abs=1e-3)
    assert (data.pooled_reps_min, data.pooled_reps_max) == (2, 3)
    observed = {item["reps"]: item["n_sets"] for item in data.pooled_observed_reps}
    assert observed == {2: 12, 3: 12}


def test_no_stored_sets_reports_why():
    empty = enriched(bench_rows([80], lambda load: 1.0)).iloc[0:0]
    data = profile.build(empty, "bench_press", family="horizontal_push")
    assert data.status == "no_data"
