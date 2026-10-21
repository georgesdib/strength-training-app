"""Advisory recent-stress decay: fixed constants, no load effect."""

from __future__ import annotations

import pandas as pd

from strength_coach.features import recent_stress

CONFIG = recent_stress.StressConfig.load()


def frame(rows):
    return pd.DataFrame(rows).assign(date=lambda d: pd.to_datetime(d["date"]))


def sets_on(day, exercise="ssb_squat", count=1, rir=2):
    return [
        {"date": day, "exercise_id": exercise, "is_working_set": True, "rir": rir}
        for _ in range(count)
    ]


def test_decay_halves_a_hard_set_after_one_half_life():
    report = recent_stress.compute(
        frame(sets_on("2024-01-06", count=4)), "2024-01-08", CONFIG,
    )
    entry = report["ssb_squat"]
    # Four sets, 48 h old -> half their weight.
    assert entry.decayed_sets == 2.0
    assert entry.last_hours == 48.0
    assert entry.status == "low"


def test_status_thresholds_and_warning_window():
    high = recent_stress.compute(
        frame(sets_on("2024-01-08", count=10)), "2024-01-09", CONFIG,
    )
    assert high["ssb_squat"].status == "high"
    warnings = recent_stress.advisories(
        high, ("ssb_squat",), CONFIG,
    )
    assert "recent stress: ssb_squat high" in warnings[0]

    old = recent_stress.compute(
        frame(sets_on("2024-01-06", count=10)), "2024-01-08", CONFIG,
    )
    assert old["ssb_squat"].status == "normal"       # 10 sets * 0.5 at 48 h
    assert recent_stress.advisories(old, ("ssb_squat",), CONFIG) == []


def test_warmups_and_high_rir_do_not_count():
    rows = sets_on("2024-01-08", count=10, rir=6)
    assert recent_stress.compute(frame(rows), "2024-01-09", CONFIG) == {}


def test_hyperextension_counts_as_back_extension():
    rows = sets_on("2024-01-08", count=4, exercise="hyperextension")
    report = recent_stress.compute(frame(rows), "2024-01-09", CONFIG)
    assert report["back_extension"].set_count == 4
    assert "hyperextension" not in report
