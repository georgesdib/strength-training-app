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


def test_final_set_recovery_anchors_on_the_last_set_not_the_finish_tap():
    # Series: 150 bpm at the last set, 128 a minute later, 118 two minutes later. A finish tap
    # three minutes after the set must not be what the number is measured from.
    anchor = 1000.0
    series = [(anchor, 150.0), (anchor + 60.0, 128.0), (anchor + 120.0, 118.0),
              (anchor + 180.0, 110.0)]
    recovery = hr_recovery._after_final_set(series, anchor)
    assert recovery["hr_end_bpm"] == 150
    assert recovery["hrr60_bpm"] == 22
    assert recovery["hrr120_bpm"] == 32
    assert recovery["anchor"] == "last_set_completed"
    assert recovery["caveat"] == hr_recovery.CAVEAT


def test_final_set_recovery_reports_each_horizon_independently():
    anchor = 1000.0
    # No sample near +120 s: the 1-minute value survives, the 2-minute one is absent.
    series = [(anchor, 150.0), (anchor + 60.0, 128.0)]
    recovery = hr_recovery._after_final_set(series, anchor)
    assert recovery["hrr60_bpm"] == 22
    assert recovery["hrr120_bpm"] is None
    # No start sample: nothing is reported at all rather than measured from the wrong point.
    assert hr_recovery._after_final_set([(anchor - 90.0, 150.0)], anchor) is None


def test_a_session_without_samples_reports_no_final_set_recovery():
    store = _imported_store()
    try:
        session_id = history.list_sessions(store.connection)["sessions"][0]["session_id"]
        assert hr_recovery.after_final_set(store.connection, session_id) is None
    finally:
        store.close()

