"""Read-only regime-change detection."""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach.features import regime_change
from strength_coach.store import db, importer


def _store(rows):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def _row(day, exercise, load):
    return {"Date": day, "Exercise": exercise, "Weight_Used": load,
            "RIR": "2", "Reps_Done": "5"}


def test_main_lift_collapse_with_same_category_substitute():
    rows = [
        _row("2023-12-11", "Safety Squat Bar", "100"),
        _row("2023-12-18", "Safety Squat Bar", "100"),
        _row("2023-12-25", "Safety Squat Bar", "100"),
        _row("2024-01-01", "Safety Squat Bar", "100"),
        _row("2024-01-08", "Split Squat", "30"),
        _row("2024-01-15", "Split Squat", "30"),
    ]
    store = _store(rows)
    try:
        before = store.connection.execute("SELECT COUNT(*) FROM clean_set").fetchone()[0]
        report = regime_change.detect(
            store.connection, on_date="2024-03-01", weeks=8
        )
        after = store.connection.execute("SELECT COUNT(*) FROM clean_set").fetchone()[0]
    finally:
        store.close()
    assert before == after
    finding = report["findings"][0]
    assert finding["main_lift"] == "ssb_squat"
    assert finding["kind"] == "disappeared"
    assert finding["current_sets"] == 0
    assert finding["substitutes"][0]["exercise_id"] == "split_squat"
    assert finding["substitutes"][0]["increase"] == 2


def test_no_finding_when_main_lift_volume_is_maintained():
    rows = [
        _row("2023-12-11", "Safety Squat Bar", "100"),
        _row("2023-12-18", "Safety Squat Bar", "100"),
        _row("2023-12-25", "Safety Squat Bar", "100"),
        _row("2024-01-01", "Safety Squat Bar", "100"),
        _row("2024-01-08", "Safety Squat Bar", "100"),
        _row("2024-01-15", "Safety Squat Bar", "100"),
    ]
    store = _store(rows)
    try:
        report = regime_change.detect(
            store.connection, on_date="2024-03-01", weeks=8
        )
    finally:
        store.close()
    assert report["findings"] == []
    assert report["coverage"]["main_lifts_checked"] >= 1
