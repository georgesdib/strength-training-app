"""Pure load-base selector tests."""

from __future__ import annotations

import pandas as pd
import pytest

from strength_coach.features import e1rm_source


def frame(rows):
    return pd.DataFrame(rows)


def row(set_id, date, exercise_id="squat", e1rm=100.0, working=True):
    return {
        "set_id": set_id,
        "session_id": f"s{set_id}",
        "date": date,
        "exercise_id": exercise_id,
        "e1rm_kg": e1rm,
        "is_working_set": working,
    }


def select(rows, **overrides):
    values = {
        "exercise_id": "squat",
        "for_date": "2026-02-01",
        "window_days": 84,
        "robust_window_days": 28,
        "source": "median",
        "override": None,
        "calibration_factor": 1.0,
        "decay_factor": lambda age: 1.0,
        "history_equivalents": ("squat",),
    }
    values.update(overrides)
    return e1rm_source.select_load_base(frame(rows), **values)


def test_best_usable_selects_the_highest_and_prefers_recent_ties():
    result = select(
        [row(1, "2026-01-01", e1rm=120.0), row(2, "2026-01-02", e1rm=120.0)],
        source="best_usable",
    )

    assert result is not None
    assert result.kg == 120.0
    assert result.ref == "set:s2/2"
    assert result.coverage == 2
    assert result.selector == "best_usable"
    assert result.age_days == 30


def test_median_uses_the_robust_window_and_latest_contributor():
    result = select(
        [
            row(1, "2025-12-01", e1rm=200.0),
            row(2, "2026-01-20", e1rm=100.0),
            row(3, "2026-01-25", e1rm=110.0),
            row(4, "2026-01-30", e1rm=120.0),
        ]
    )

    assert result is not None
    assert result.kg == 110.0
    assert result.ref == "set:s4/4"
    assert result.coverage == 3
    assert result.selector == "median"


def test_median_falls_back_to_the_outer_window():
    result = select([row(1, "2025-12-01", e1rm=100.0), row(2, "2025-12-02", e1rm=120.0)])

    assert result is not None
    assert result.kg == 110.0
    assert result.coverage == 2


def test_most_recent_uses_the_latest_set():
    result = select(
        [row(1, "2026-01-01", e1rm=160.0), row(2, "2026-01-31", e1rm=140.0)],
        source="most_recent",
    )

    assert result is not None
    assert result.kg == 140.0
    assert result.ref == "set:s2/2"


def test_override_wins_and_keeps_its_decay_and_age():
    result = select(
        [row(1, "2026-01-01", e1rm=100.0)],
        override={"override_id": 7, "e1rm_kg": 200.0, "effective_from": "2026-01-01"},
        decay_factor=lambda age: 0.99 ** age,
    )

    assert result is not None
    assert result.kg == 200.0 * (0.99 ** 31)
    assert result.ref == "e1rm_override:7"
    assert result.calibrated is False
    assert result.decayed is True
    assert result.age_days == 31


def test_calibration_factor_is_applied_without_changing_the_reference():
    result = select([row(1, "2026-01-01", e1rm=100.0)], calibration_factor=1.1)

    assert result is not None
    assert result.kg == pytest.approx(110.0)
    assert result.calibrated is True
    assert result.ref == "set:s1/1"


def test_history_equivalents_are_used_only_when_supplied():
    rows = [row(1, "2026-01-01", exercise_id="hyperextension", e1rm=100.0)]

    with_equivalent = select(
        rows,
        exercise_id="back_extension",
        history_equivalents=("back_extension", "hyperextension"),
    )
    without = select(rows, exercise_id="back_extension", history_equivalents=("back_extension",))

    assert with_equivalent is not None
    assert with_equivalent.kg == 100.0
    assert without is None


def test_window_and_warmups_are_excluded():
    result = select(
        [
            row(1, "2025-10-01", e1rm=500.0),
            row(2, "2026-01-01", e1rm=100.0),
            row(3, "2026-01-02", e1rm=200.0, working=False),
        ],
        source="best_usable",
    )

    assert result is not None
    assert result.kg == 100.0
    assert result.coverage == 1


def test_empty_or_missing_e1rm_returns_none():
    assert select([]) is None
    assert e1rm_source.select_load_base(
        frame([row(1, "2026-01-01")]).drop(columns=["e1rm_kg"]),
        exercise_id="squat",
        for_date="2026-02-01",
        window_days=84,
        robust_window_days=28,
        source="median",
        override=None,
        calibration_factor=1.0,
        decay_factor=lambda age: 1.0,
        history_equivalents=("squat",),
    ) is None
