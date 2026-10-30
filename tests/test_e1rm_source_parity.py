"""Parity between the extracted selector and the pre-extraction implementation."""

from __future__ import annotations

import pandas as pd
import pytest

from strength_coach.features import e1rm_source


def legacy_select(
    sets,
    *,
    exercise_id,
    for_date,
    window_days,
    robust_window_days,
    source,
    override,
    calibration_factor,
    decay_factor,
    history_equivalents,
):
    """The pre-extraction selector body, copied for parity evidence only."""
    if override is not None:
        age = (pd.Timestamp(for_date) - pd.Timestamp(override["effective_from"])).days
        decay = decay_factor(age)
        return (
            float(override["e1rm_kg"]) * decay,
            f"e1rm_override:{override['override_id']}",
            False,
            decay != 1.0,
            None,
            decay,
        )
    if sets is None or sets.empty or "e1rm_kg" not in sets:
        return None
    frame = sets
    cutoff = pd.Timestamp(for_date) - pd.Timedelta(days=window_days)
    usable = frame[
        frame["exercise_id"].isin(history_equivalents)
        & frame["e1rm_kg"].notna()
        & (frame["date"] >= cutoff)
    ]
    if "is_working_set" in usable.columns:
        usable = usable[usable["is_working_set"].astype(bool)]
    if usable.empty:
        return None
    usable = usable.assign(_age_days=(pd.Timestamp(for_date) - usable["date"]).dt.days)
    usable["_decay"] = [decay_factor(age) for age in usable["_age_days"]]
    usable["_effective"] = usable["e1rm_kg"] * usable["_decay"]
    factor = float(calibration_factor)

    if source == "median":
        robust_start = pd.Timestamp(for_date) - pd.Timedelta(days=robust_window_days)
        pool = usable[usable["date"] >= robust_start]
        if pool.empty:
            pool = usable
        raw_median = float(pool["e1rm_kg"].median())
        effective_median = float(pool["_effective"].median())
        decay = effective_median / raw_median if raw_median > 0 else 1.0
        row = pool.sort_values(["date", "set_id"]).iloc[-1]
        return (
            effective_median * factor,
            f"set:{row['session_id']}/{int(row['set_id'])}",
            factor != 1.0,
            decay < 1.0 - 1e-9,
            int(len(pool)),
            decay,
        )

    if source == "most_recent":
        row = usable.sort_values(["date", "set_id"]).iloc[-1]
        decay = float(row["_decay"])
        return (
            float(row["e1rm_kg"]) * factor * decay,
            f"set:{row['session_id']}/{int(row['set_id'])}",
            factor != 1.0,
            decay != 1.0,
            int(len(usable)),
            decay,
        )

    row = usable.sort_values(
        ["_effective", "date", "set_id"], ascending=[False, False, False]
    ).iloc[0]
    decay = float(row["_decay"])
    return (
        float(row["e1rm_kg"]) * factor * decay,
        f"set:{row['session_id']}/{int(row['set_id'])}",
        factor != 1.0,
        decay != 1.0,
        int(len(usable)),
        decay,
    )


def frame(rows):
    return pd.DataFrame(rows)


def row(set_id, date, exercise_id="squat", e1rm=100.0, working=True):
    return {
        "set_id": set_id,
        "session_id": f"s{set_id}",
        "date": pd.Timestamp(date),
        "exercise_id": exercise_id,
        "e1rm_kg": e1rm,
        "is_working_set": working,
    }


def assert_parity(
    rows,
    *,
    exercise_id="squat",
    for_date="2026-02-01",
    window_days=84,
    robust_window_days=28,
    source="median",
    override=None,
    calibration_factor=1.0,
    decay_factor=lambda age: 0.99 ** age,
    history_equivalents=("squat",),
):
    data = frame(rows)
    legacy = legacy_select(
        data,
        exercise_id=exercise_id,
        for_date=for_date,
        window_days=window_days,
        robust_window_days=robust_window_days,
        source=source,
        override=override,
        calibration_factor=calibration_factor,
        decay_factor=decay_factor,
        history_equivalents=history_equivalents,
    )
    extracted = e1rm_source.select_load_base(
        data,
        exercise_id=exercise_id,
        for_date=for_date,
        window_days=window_days,
        robust_window_days=robust_window_days,
        source=source,
        override=override,
        calibration_factor=calibration_factor,
        decay_factor=decay_factor,
        history_equivalents=history_equivalents,
    )
    assert legacy is not None
    assert extracted is not None
    assert extracted.kg == pytest.approx(legacy[0])
    assert extracted.ref == legacy[1]
    assert extracted.calibrated is legacy[2]
    assert extracted.decayed is legacy[3]
    assert extracted.coverage == legacy[4]
    assert extracted.decay == pytest.approx(legacy[5])


def test_override_precedence_parity():
    assert_parity(
        [row(1, "2026-01-01")],
        override={"override_id": 9, "e1rm_kg": 200.0, "effective_from": "2026-01-01"},
    )


def test_all_three_selectors_parity():
    rows = [
        row(1, "2026-01-01", e1rm=120.0),
        row(2, "2026-01-20", e1rm=100.0),
        row(3, "2026-01-30", e1rm=110.0),
    ]
    assert_parity(rows, source="best_usable")
    assert_parity(rows, source="median")
    assert_parity(rows, source="most_recent")


def test_robust_window_fallback_parity():
    assert_parity(
        [row(1, "2025-12-01", e1rm=100.0), row(2, "2025-12-02", e1rm=120.0)]
    )


def test_history_equivalent_parity():
    assert_parity(
        [row(1, "2026-01-01", exercise_id="hyperextension")],
        exercise_id="back_extension",
        history_equivalents=("back_extension", "hyperextension"),
    )


def test_per_set_decay_parity():
    assert_parity(
        [row(1, "2025-12-01", e1rm=150.0), row(2, "2026-01-25", e1rm=140.0)],
        source="best_usable",
    )


def test_calibration_factor_parity():
    assert_parity([row(1, "2026-01-01", e1rm=100.0)], calibration_factor=1.1)


def test_long_gap_decay_exception_parity():
    def decay(age):
        return 1.0 if age >= 28 else 0.99 ** age

    assert_parity(
        [row(1, "2025-12-01", e1rm=150.0), row(2, "2025-12-15", e1rm=140.0)],
        source="most_recent",
        decay_factor=decay,
    )
