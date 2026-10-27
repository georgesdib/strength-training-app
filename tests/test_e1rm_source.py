"""Choosing which e1RM to prescribe from (DEC-E1RM-SOURCE-01).

The selector used to be a config value that nothing read: changing `e1rm_source` left every
prescription identical. These tests pin that each named selector actually selects, and that a
name the code does not implement is an error rather than a silent default.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
import yaml
from conftest import make_readiness, make_training

from strength_coach.prescribe import build_prescription, config
from strength_coach.store import db, importer


def store_with(rows):
    dates = sorted({row["Date"] for row in rows})
    training = make_training(rows)
    readiness = make_readiness([{"Date": day} for day in dates])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection,
        training,
        readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def history(loads):
    """Three identical sets per training day: one observation per day, so the median is
    decided by the days rather than by how many sets a day happened to contain."""
    rows = []
    for day, load in loads:
        for _ in range(3):
            rows.append({"Date": day, "Exercise": "Trap Bar Deadlift",
                         "Weight_Used": load, "RIR": "2", "Reps_Done": "5"})
            rows.append({"Date": day, "Exercise": "Bench Press (narrow grip)",
                         "Weight_Used": load, "RIR": "2", "Reps_Done": "5"})
    return rows


def prescribed(store, source, *, on_date="2024-01-24", robust_days=28):
    thresholds = replace(
        config.Thresholds.load(),
        e1rm_source=source,
        e1rm_robust_window_days=robust_days,
    )
    prescription = build_prescription(
        store.connection, for_date=on_date, session_type="hinge", thresholds=thresholds
    )
    item = next(i for i in prescription.items if i.exercise_id == "trap_bar_deadlift")
    return item, prescription


OUTLIER_HISTORY = [
    ("2024-01-01", "150"),
    ("2024-01-08", "152"),
    ("2024-01-15", "151"),
    ("2024-01-22", "153"),
    ("2024-01-23", "185"),   # one great day
]


def test_median_ignores_a_single_outlier_day():
    with store_with(history(OUTLIER_HISTORY)) as store:
        best, _ = prescribed(store, config.E1RM_BEST_USABLE)
        median, _ = prescribed(store, config.E1RM_MEDIAN)
    assert best.load_kg > median.load_kg


def test_median_matches_best_when_the_history_is_uniform():
    uniform = [("2024-01-01", "150"), ("2024-01-08", "150"), ("2024-01-15", "150")]
    with store_with(history(uniform)) as store:
        best, _ = prescribed(store, config.E1RM_BEST_USABLE)
        median, _ = prescribed(store, config.E1RM_MEDIAN)
    assert median.load_kg == best.load_kg


def test_median_falls_back_to_the_best_when_nothing_is_recent():
    # Older than the 28-day robust window but inside the 84-day window: the median must not
    # throw the history away, which would turn a returning athlete into a NO_LOAD.
    old = [("2023-12-01", "150"), ("2023-12-08", "150")]
    with store_with(history(old)) as store:
        best, _ = prescribed(store, config.E1RM_BEST_USABLE)
        median, _ = prescribed(store, config.E1RM_MEDIAN)
    assert median.load_kg == best.load_kg
    assert median.e1rm_source_sets == best.e1rm_source_sets


def test_most_recent_follows_the_latest_set_rather_than_the_best():
    declining = [("2024-01-01", "160"), ("2024-01-22", "140")]
    with store_with(history(declining)) as store:
        best, _ = prescribed(store, config.E1RM_BEST_USABLE)
        latest, _ = prescribed(store, config.E1RM_MOST_RECENT)
    assert latest.load_kg < best.load_kg


def test_the_median_reports_what_it_summarised():
    with store_with(history(OUTLIER_HISTORY)) as store:
        item, prescription = prescribed(store, config.E1RM_MEDIAN)
    assert any("median of" in warning for warning in prescription.warnings)
    # Five training days x three sets each, all inside the 28-day robust window.
    assert item.e1rm_source_sets == 15


def test_an_unknown_selector_is_rejected(tmp_path):
    path = tmp_path / "thresholds.yaml"
    path.write_text(
        yaml.safe_dump({"load": {"e1rm_source": "best"}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unsupported e1rm_source"):
        config.Thresholds.load(path)


def test_a_robust_window_wider_than_the_window_is_rejected(tmp_path):
    path = tmp_path / "thresholds.yaml"
    path.write_text(
        yaml.safe_dump({"load": {"e1rm_window_days": 28, "e1rm_robust_window_days": 84}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not exceed e1rm_window_days"):
        config.Thresholds.load(path)

def test_a_warmup_set_is_never_selected():
    # DEC-RIR-01: RIR 6 marks a warm-up. It still carries a much lower formula e1RM, so it
    # must not become the "most recent" set and must not drag the median down.
    rows = []
    for day in ("2024-01-01", "2024-01-08", "2024-01-15"):
        for _ in range(3):
            rows.append({"Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
                         "RIR": "2", "Reps_Done": "5"})
            rows.append({"Date": day, "Exercise": "Bench Press (narrow grip)",
                         "Weight_Used": "150", "RIR": "2", "Reps_Done": "5"})
    # A light warm-up pair on the latest day, after every working set.
    rows.append({"Date": "2024-01-20", "Exercise": "Trap Bar Deadlift", "Weight_Used": "60",
                 "RIR": "6", "Reps_Done": "5"})
    rows.append({"Date": "2024-01-20", "Exercise": "Bench Press (narrow grip)",
                 "Weight_Used": "40", "RIR": "6", "Reps_Done": "5"})

    with store_with(rows) as store:
        median, _ = prescribed(store, config.E1RM_MEDIAN, on_date="2024-01-22")
        latest, _ = prescribed(store, config.E1RM_MOST_RECENT, on_date="2024-01-22")
    assert latest.load_kg == median.load_kg
    # A 60 kg warm-up would have produced roughly 60 kg, not this.
    assert latest.load_kg > 100
