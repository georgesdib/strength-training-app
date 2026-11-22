"""Per-set heart-rate recovery is display-only and never invents a value."""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach import history
from strength_coach.features import hr_recovery
from strength_coach.store import db, importer


def _imported_store() -> db.Store:
    store = db.Store(":memory:")
    training = make_training([
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press",
         "Weight_Used": "80", "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{"Date": "2024-01-01"}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_an_imported_session_has_no_recovery_values():
    # No linked workout, no samples: every set reports absent, and the session reports null.
    store = _imported_store()
    try:
        session_id = history.list_sessions(store.connection)["sessions"][0]["session_id"]
        detail = history.detail(store.connection, session_id)
    finally:
        store.close()
    assert detail["hr_recovery"] is None
    assert detail["sets"]
    assert all(item["hrr60_bpm"] is None for item in detail["sets"])


def test_an_empty_corpus_reports_no_signal():
    store = db.Store(":memory:")
    try:
        report = hr_recovery.report(store.connection)
    finally:
        store.close()
    assert report["sessions"] == 0
    assert report["sets_matched"] == 0
    assert report["coverage"] == 0.0
    assert report["worth_pursuing"] is False
    assert report["caveat"] == hr_recovery.CAVEAT


def test_endpoints_require_a_sample_inside_tolerance():
    series = [(100.0, 150.0), (160.0, 140.0), (220.0, 130.0)]
    assert hr_recovery._endpoint(series, 104.0, 10.0) == 150.0
    assert hr_recovery._endpoint(series, 120.0, 10.0) is None
    assert hr_recovery._nearest(series, 162.0, 15.0) == 140.0
    assert hr_recovery._nearest(series, 190.0, 15.0) is None
    assert hr_recovery._corr([1.0, 2.0], [1.0, 2.0]) is None  # too few points to correlate


def test_the_report_is_plain_json_serialisable():
    import json

    store = db.Store(":memory:")
    try:
        json.dumps(hr_recovery.report(store.connection))
    finally:
        store.close()
