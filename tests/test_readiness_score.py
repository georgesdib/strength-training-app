"""Readiness score: global, category, overrides and the required-before-workout gate."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.features import readiness as readiness_feature
from strength_coach.features import readiness_score
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer, queries, repositories

TODAY = dt.date.today().isoformat()
ROWS = [
    {"Date": TODAY, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": TODAY, "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


@contextmanager
def store_with(readiness_rows=None, rows=ROWS):
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{"Date": rows[0]["Date"]}])
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


def item(prescription, exercise_id):
    return next(i for i in prescription.items if i.exercise_id == exercise_id)


def test_all_fours_is_neutral_and_does_not_reduce_loads():
    with store_with() as store:
        assessment = readiness_score.compute(store.connection, TODAY)
        prescription = build_prescription(store.connection, for_date=TODAY, session_day="A")

    assert assessment.status == "ready"
    assert assessment.score == 0.8
    assert item(prescription, "ssb_squat").load_kg == 105.5
    assert prescription.fallback_level == "full"


def test_partial_fields_cannot_form_a_score():
    with store_with() as store:
        store.connection.execute("DELETE FROM readiness_day")
        readiness_feature.record_manual(
            store.connection, TODAY, {"sleep": 2, "energy": 4}
        )
        assessment = readiness_score.compute(store.connection, TODAY)
        prescription = build_prescription(store.connection, for_date=TODAY, session_day="A")

    assert assessment.status == "insufficient"
    assert assessment.score is None
    assert prescription.fallback_level == "fatigue_reduced"       # old sleep/energy floor
    assert any("readiness insufficient" in warning for warning in prescription.warnings)


def test_global_override_wins_and_changes_the_load():
    with store_with() as store:
        repositories.append_readiness_override(
            store.connection, effective_on=TODAY, scope="global", value=0.50,
            reason="felt worse than the form suggested",
        )
        assessment = readiness_score.compute(store.connection, TODAY)
        prescription = build_prescription(store.connection, for_date=TODAY, session_day="A")

    assert assessment.score == 0.50
    assert item(prescription, "ssb_squat").load_kg < 105.5
    refs = item(prescription, "ssb_squat").rationale_refs
    assert any(ref.startswith("readiness_override:") for ref in refs)


def test_category_override_only_affects_that_category():
    with store_with() as store:
        repositories.append_readiness_override(
            store.connection, effective_on=TODAY, scope="category:squat", value=0.50,
            reason="squat positioning felt off",
        )
        prescription = build_prescription(store.connection, for_date=TODAY, session_day="A")

    squat = item(prescription, "ssb_squat")
    bench = item(prescription, "bench_press")
    assert squat.load_kg < 105.5
    assert bench.load_kg == 84.5


def test_injury_ceiling_caps_a_high_score():
    with store_with() as store:
        conn = store.connection
        repositories.append_symptom(
            conn, logged_on=TODAY, timing="pre_session", region="low_back",
            level=2, settled_within_48h=0,
        )
        assessment = readiness_score.compute(conn, TODAY)
        prescription = build_prescription(conn, for_date=TODAY, session_day="A")

    assert assessment.score == 0.8
    assert item(prescription, "ssb_squat").load_kg < 105.5


def test_cli_requires_readiness_for_today(tmp_path):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training(ROWS)
    readiness = make_readiness([{"Date": TODAY}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.connection.execute("DELETE FROM readiness_day")
    store.close()

    assert cli.main(["--db", str(path), "run", "--date", TODAY, "--day", "A"]) == 2

    assert cli.main(["--db", str(path), "readiness", "set", "--date", TODAY,
                     "--sleep", "4", "--energy", "4", "--mood", "4",
                     "--soreness", "4", "--stress", "4"]) == 0
    assert cli.main(["--db", str(path), "run", "--date", TODAY, "--day", "A"]) == 0


def test_legacy_fields_are_not_manual_inputs():
    with store_with() as store:
        try:
            readiness_feature.record_manual(
                store.connection, TODAY, {"squat_readiness": 3}
            )
        except ValueError as exc:
            assert "legacy calibration label" in str(exc)
        else:
            raise AssertionError("legacy field was accepted as input")

def test_calibration_report_runs_on_labels():
    rows = []
    readiness = []
    start = dt.date(2024, 1, 1)
    for offset in range(30):
        day = (start + dt.timedelta(days=offset)).isoformat()
        rows.append({"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
                     "RIR": "2", "Reps_Done": "5"})
        readiness.append({"Date": day, "Sleep": "4", "Energy": "4", "Mood": "4",
                          "Stress": "4", "Soreness": "4", "Squat_Readiness": "4",
                          "Bench_Readiness": "4", "Deadlift_Readiness": "4"})
    with store_with(rows=rows, readiness_rows=readiness) as store:
        from strength_coach.features import readiness_calibration

        text = readiness_calibration.report(store.connection, minimum=10)
    assert "MIMICRY" in text.upper()
    assert "squat_readiness" in text

def test_combined_readiness_and_gap_reduction_is_capped():
    rows = [{"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
             "RIR": "2", "Reps_Done": "5"}]
    with store_with(rows=rows) as store:
        conn = store.connection
        readiness_feature.record_manual(
            conn, "2024-03-01",
            {"sleep": 1, "energy": 1, "mood": 1, "stress": 1, "soreness": 1},
        )
        prescription = build_prescription(conn, for_date="2024-03-01", session_day="A")

    squat = item(prescription, "ssb_squat")
    assert squat.load_kg == 84.0       # 105.5 * 0.80, not 0.85 * 0.90
    assert any("capped at 20%" in warning for warning in prescription.warnings)

def _readiness_with_history(history_values, current):
    from datetime import date, timedelta
    today = date.fromisoformat(TODAY)
    rows = []
    for offset, values in history_values:
        rows.append({"Date": (today - timedelta(days=offset)).isoformat(), **values})
    rows.append({"Date": TODAY, **current})
    return rows


def test_hrv_and_rhr_need_a_baseline():
    rows = _readiness_with_history(
        [], {"Sleep": "4", "Energy": "4", "Mood": "4", "Stress": "4", "Soreness": "4",
             "HRV": "80", "RHR": "50"},
    )
    with store_with(readiness_rows=rows) as store:
        assessment = readiness_score.compute(store.connection, TODAY)

    assert assessment.status == "ready"
    assert assessment.score == 0.8
    assert not any(c.field in {"hrv_ms", "rhr_bpm"} for c in assessment.components)
    assert "baseline 0/7" in assessment.basis


def test_hrv_and_rhr_move_the_score_only_with_a_baseline():
    baseline = [(d, {"HRV": "60", "RHR": "60"}) for d in range(1, 8)]
    good = _readiness_with_history(
        baseline, {"Sleep": "4", "Energy": "4", "Mood": "4", "Stress": "4",
                   "Soreness": "4", "HRV": "90", "RHR": "45"},
    )
    bad = _readiness_with_history(
        baseline, {"Sleep": "4", "Energy": "4", "Mood": "4", "Stress": "4",
                   "Soreness": "4", "HRV": "30", "RHR": "90"},
    )
    with store_with(readiness_rows=good) as store:
        high = readiness_score.compute(store.connection, TODAY)
    with store_with(readiness_rows=bad) as store:
        low = readiness_score.compute(store.connection, TODAY)

    assert high.score > 0.8
    assert low.score < 0.8
    assert any(c.field == "hrv_ms" for c in high.components)
    assert any(c.field == "rhr_bpm" for c in high.components)


def test_optional_wearable_score_is_low_weight_and_a_global_override_still_wins():
    with store_with() as store:
        plain = readiness_score.compute(store.connection, TODAY)
    rows = _readiness_with_history([], {
        "Sleep": "4", "Energy": "4", "Mood": "4", "Stress": "4", "Soreness": "4",
        "Wearable_Score": "100",
    })
    with store_with(readiness_rows=rows) as store:
        perfect = readiness_score.compute(store.connection, TODAY)
    low_rows = _readiness_with_history([], {
        "Sleep": "4", "Energy": "4", "Mood": "4", "Stress": "4", "Soreness": "4",
        "Wearable_Score": "0",
    })
    with store_with(readiness_rows=low_rows) as store:
        zero = readiness_score.compute(store.connection, TODAY)
        repositories.append_readiness_override(
            store.connection, effective_on=TODAY, scope="global", value=0.50,
            reason="manual override",
        )
        overridden = readiness_score.compute(store.connection, TODAY)

    assert plain.score == 0.8
    assert perfect.score == pytest.approx(0.82)
    assert zero.score == pytest.approx(0.72)
    assert overridden.score == 0.50


def test_wearable_score_rejects_out_of_range():
    with store_with() as store:
        try:
            readiness_feature.record_manual(store.connection, TODAY, {"wearable_score": 101})
        except ValueError as exc:
            assert "0 to 100" in str(exc)
        else:
            raise AssertionError("wearable score >100 was accepted")
