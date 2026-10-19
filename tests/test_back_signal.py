"""Back signal: counts evidence for a review, never grants clearance."""

from __future__ import annotations

from contextlib import contextmanager

from conftest import make_readiness, make_training
from strength_coach.features import back_signal
from strength_coach.prescribe.config import Thresholds
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
     "RIR": "2", "Reps_Done": "3"}
    for day in ("2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29")
]


@contextmanager
def store_with():
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def log(conn, day, level, settled=None):
    repositories.append_symptom(
        conn, logged_on=day, timing="pre_session", region="low_back",
        level=level, settled_within_48h=settled,
    )


def test_no_symptom_data_is_unknown_not_fine():
    with store_with() as store:
        signal = back_signal.compute(store.connection, "2024-03-01", Thresholds.load())
    assert signal.status == "unknown"
    assert signal.symptom_free_days is None


def test_an_old_entry_is_insufficient():
    with store_with() as store:
        log(store.connection, "2024-01-01", 0)
        signal = back_signal.compute(store.connection, "2024-03-01", Thresholds.load())
    assert signal.status == "insufficient"
    assert "days old" in signal.summary


def test_four_weeks_symptom_free_with_loaded_sessions_recommends_a_review():
    with store_with() as store:
        conn = store.connection
        log(conn, "2024-01-01", 0)
        log(conn, "2024-03-01", 0)
        signal = back_signal.compute(conn, "2024-03-01", Thresholds.load())

    assert signal.status == "review"
    assert signal.symptom_free_days >= 28
    assert signal.loaded_sessions >= 4
    assert signal.recommendation is not None
    assert "Not medical clearance" in signal.disclaimer


def test_a_current_symptom_blocks_the_review():
    with store_with() as store:
        conn = store.connection
        log(conn, "2024-01-01", 0)
        log(conn, "2024-03-01", 2)
        signal = back_signal.compute(conn, "2024-03-01", Thresholds.load())

    assert signal.status == "monitoring"
    assert signal.symptom_free_days == 0
    assert signal.recommendation is None
