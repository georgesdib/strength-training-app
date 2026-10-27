"""Readiness score: global, category, overrides and the required-before-workout gate."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.features import readiness as readiness_feature
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.features import readiness_score
from strength_coach.prescribe import build_prescription, loads
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
        prescription = build_prescription(store.connection, for_date=TODAY, session_type="squat")

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
        prescription = build_prescription(store.connection, for_date=TODAY, session_type="squat")

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
        prescription = build_prescription(store.connection, for_date=TODAY, session_type="squat")

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
        prescription = build_prescription(store.connection, for_date=TODAY, session_type="squat")

    squat = item(prescription, "ssb_squat")
    bench = item(prescription, "bench_press")
    assert squat.load_kg < 105.5
    assert bench.load_kg == 84.5


def test_category_override_applies_when_no_score_can_be_formed():
    """READINESS-SCORE §2.2a: a partial day keeps the athlete's explicit category override."""
    with store_with() as store:
        store.connection.execute("DELETE FROM readiness_day")
        readiness_feature.record_manual(store.connection, TODAY, {"sleep": 4, "energy": 4})
        repositories.append_readiness_override(
            store.connection, effective_on=TODAY, scope="category:squat", value=0.50,
            reason="squat positioning felt off",
        )
        assessment = readiness_score.compute(store.connection, TODAY)
        prescription = build_prescription(store.connection, for_date=TODAY, session_type="squat")

    # No numeric score is invented: the override is the only readiness statement.
    assert assessment.status == "insufficient"
    assert assessment.score is None
    assert assessment.category_scores["squat"] == 0.50
    squat = item(prescription, "ssb_squat")
    assert squat.load_kg < 105.5
    assert "MOD-FAT-001" in squat.rationale_refs
    assert any(ref.startswith("readiness_override:") for ref in squat.rationale_refs)
    assert not any(ref.startswith("readiness_score:") for ref in squat.rationale_refs)
    # The override is scoped to its category; the bench keeps its normal load.
    assert item(prescription, "bench_press").load_kg == 84.5


def test_global_override_applies_when_no_score_can_be_formed():
    with store_with() as store:
        store.connection.execute("DELETE FROM readiness_day")
        readiness_feature.record_manual(store.connection, TODAY, {"sleep": 4, "energy": 4})
        repositories.append_readiness_override(
            store.connection, effective_on=TODAY, scope="global", value=0.50,
            reason="felt worse than the partial form says",
        )
        assessment = readiness_score.compute(store.connection, TODAY)
        prescription = build_prescription(store.connection, for_date=TODAY, session_type="squat")

    assert assessment.status == "insufficient"
    assert assessment.score is None
    assert assessment.category_scores["hinge"] == 0.50
    assert item(prescription, "ssb_squat").load_kg < 105.5
    assert item(prescription, "bench_press").load_kg < 84.5


def test_override_applies_on_a_day_with_no_readiness_entry():
    with store_with() as store:
        store.connection.execute("DELETE FROM readiness_day")
        repositories.append_readiness_override(
            store.connection, effective_on=TODAY, scope="global", value=0.50,
            reason="no form today",
        )
        assessment = readiness_score.compute(store.connection, TODAY)
        prescription = build_prescription(store.connection, for_date=TODAY, session_type="squat")

    assert assessment.status == "unknown"
    assert assessment.score is None
    assert item(prescription, "ssb_squat").load_kg < 105.5


def test_a_partial_day_without_an_override_changes_nothing():
    """Guard: the override path must not become a way to apply an injury ceiling on partial days."""
    with store_with() as store:
        store.connection.execute("DELETE FROM readiness_day")
        readiness_feature.record_manual(store.connection, TODAY, {"sleep": 4, "energy": 4})
        assessment = readiness_score.compute(store.connection, TODAY)
        prescription = build_prescription(store.connection, for_date=TODAY, session_type="squat")

    assert assessment.status == "insufficient"
    assert assessment.category_scores == {}
    assert item(prescription, "ssb_squat").load_kg == 105.5
    assert prescription.fallback_level == "full"


def test_an_unknown_category_scope_is_rejected():
    with store_with() as store:
        with pytest.raises(ValueError, match="unknown readiness category"):
            repositories.append_readiness_override(
                store.connection, effective_on=TODAY, scope="category:sqaut", value=0.50,
                reason="typo",
            )
        assert queries.readiness_overrides(store.connection, TODAY) == {}


def test_cli_rejects_an_unknown_category_scope(tmp_path, capsys):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training(ROWS)
    readiness = make_readiness([{"Date": TODAY}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    code = cli.main(["--db", str(path), "readiness", "override", "--date", TODAY,
                     "--scope", "category:sqaut", "--value", "0.5", "--reason", "typo"])
    assert code == 2
    assert "unknown readiness category" in capsys.readouterr().out


def test_injury_ceiling_caps_a_high_score():
    with store_with() as store:
        conn = store.connection
        repositories.append_symptom(
            conn, logged_on=TODAY, timing="pre_session", region="low_back",
            level=2, settled_within_48h=0,
        )
        assessment = readiness_score.compute(conn, TODAY)
        prescription = build_prescription(conn, for_date=TODAY, session_type="squat")

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

    assert cli.main(["--db", str(path), "run", "--date", TODAY, "--session-type", "squat"]) == 2

    assert cli.main(["--db", str(path), "readiness", "set", "--date", TODAY,
                     "--sleep", "4", "--energy", "4", "--mood", "4",
                     "--soreness", "4", "--stress", "4"]) == 0
    assert cli.main(["--db", str(path), "run", "--date", TODAY, "--session-type", "squat"]) == 0


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
        prescription = build_prescription(conn, for_date="2024-03-01", session_type="squat")

    squat = item(prescription, "ssb_squat")
    # 105.5 * 0.80, then re-solved at the bumped RIR (DEC-READINESS-18).
    assert squat.load_kg == 79.5
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

def test_athlete_setting_overrides_baseline_and_weights():
    baseline = [(d, {"HRV": "60", "RHR": "60"}) for d in range(1, 8)]
    rows = _readiness_with_history(
        baseline, {"Sleep": "4", "Energy": "4", "Mood": "4", "Stress": "4",
                   "Soreness": "4", "HRV": "90", "RHR": "45"},
    )
    with store_with(readiness_rows=rows) as store:
        default = readiness_score.compute(store.connection, TODAY)
        repositories.append_readiness_setting(
            store.connection, effective_from=TODAY, baseline_days=14,
            baseline_min_readings=7, hrv_slope=0.25, rhr_slope=0.25,
            hrv_weight=1.0, rhr_weight=1.0, wearable_weight=0.10,
            note="test",
        )
        configured = readiness_score.compute(store.connection, TODAY)
        effective = readiness_score.effective_settings(store.connection, TODAY)

    assert effective.setting_source == "athlete"
    assert effective.baseline_days == 14
    assert configured.score != default.score
    assert "athlete score setting" in configured.basis
    assert any(c.weight == 1.0 for c in configured.components if c.field == "hrv_ms")


def test_baseline_shadow_report_does_not_apply_a_baseline():
    baseline = [(d, {"HRV": str(60 + d), "RHR": str(60 - d)}) for d in range(1, 10)]
    rows = _readiness_with_history(
        baseline, {"Sleep": "4", "Energy": "4", "Mood": "4", "Stress": "4",
                   "Soreness": "4", "HRV": "80", "RHR": "50"},
    )
    with store_with(readiness_rows=rows) as store:
        before = readiness_score.compute(store.connection, TODAY).score
        from strength_coach.features import readiness_baseline

        report = readiness_baseline.report(store.connection, TODAY)
        after = readiness_score.compute(store.connection, TODAY).score

    assert "SHADOW BASELINE" in report
    assert "No prescription uses" in report
    assert before == after


def test_score_is_independent_of_the_legacy_composite_flag():
    with store_with() as store:
        config = readiness_feature.ReadinessConfig.load()
        day = queries.readiness_day(store.connection, TODAY)
        assessment = readiness_score.compute(store.connection, TODAY)
    assert config.composite_enabled is False
    assert day["composite"] is None
    assert assessment.status == "ready"
    assert assessment.score == pytest.approx(0.8)


def test_readiness_rir_bump_re_solves_the_load_at_the_bumped_rir():
    low_rows = [{
        "Date": TODAY, "Sleep": "1", "Energy": "1", "Mood": "1",
        "Stress": "1", "Soreness": "1",
    }]
    with store_with() as store:
        neutral = build_prescription(
            store.connection, for_date=TODAY, session_type="squat",
        )
    with store_with(readiness_rows=low_rows) as store:
        reduced = build_prescription(
            store.connection, for_date=TODAY, session_type="squat",
        )

    base = item(neutral, "ssb_squat")
    low = item(reduced, "ssb_squat")
    assert low.rir_target > base.rir_target
    assert low.load_factor < 1.0
    base_e1rm = e1rm_mod.epley_rir_adjusted(
        base.load_kg, base.reps_low, base.rir_target,
    )
    expected = loads.solve_load(
        base_e1rm * low.load_factor,
        low.reps_low,
        low.rir_target,
        low.rounding_increment_kg,
    )
    assert low.load_kg == expected
    assert low.load_kg != loads.round_down(
        base.load_kg * low.load_factor, low.rounding_increment_kg,
    )
