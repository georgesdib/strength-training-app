"""e1RM calibration is a report: measured tests vs the formula estimate, no auto-correction."""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach.features import e1rm_calibration
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
]


def store_with_sets():
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_a_measured_test_is_compared_with_the_prior_formula_estimate():
    with store_with_sets() as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=120.0,
            effective_from="2024-02-01", reason="3RM test", source="measured",
        )
        report = e1rm_calibration.build(conn)
        [row] = report

    assert row.exercise_id == "ssb_squat"
    assert row.n == 1
    assert row.points[0].measured_kg == 120.0
    assert row.points[0].predicted_kg > 0
    assert row.median_ratio is not None
    assert "1 test" in row.status
    # Both sources are shown; the measured override is the active one and is decayed.
    assert row.formula_raw is not None and row.formula_effective is not None
    assert row.override_raw == 120.0
    assert row.override_effective is not None and 0 < row.override_effective <= 120.0
    assert row.active_source == "override"
    assert row.active_e1rm == row.override_effective


def test_a_test_without_a_prior_estimate_is_skipped():
    with store_with_sets() as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="bench_press", e1rm_kg=100.0,
            effective_from="2024-02-01", reason="test", source="measured",
        )
        assert e1rm_calibration.build(conn) == []


def test_cli_calibrate_prints_the_report(tmp_path, capsys):
    from strength_coach import cli
    from strength_coach.store import db, importer

    training = make_training(ROWS)
    readiness = make_readiness([{}])
    path = tmp_path / "coach.db"
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_e1rm_override(
        store.connection, exercise_id="ssb_squat", e1rm_kg=120.0,
        effective_from="2024-02-01", reason="3RM test", source="measured",
    )
    store.close()

    assert cli.main(["--db", str(path), "e1rm", "calibrate"]) == 0
    out = capsys.readouterr().out
    assert "ssb_squat" in out and "bounded correction" in out


def _store_with_three_tests():
    rows = []
    for day in ("2024-01-20", "2024-02-20", "2024-03-20"):
        rows.append({"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
                     "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    for day in ("2024-02-01", "2024-03-01", "2024-04-01"):
        repositories.append_e1rm_override(
            store.connection, exercise_id="ssb_squat", e1rm_kg=125.0,
            effective_from=day, expires_on=day, reason="test", source="measured",
        )
    return store


def test_consistent_bias_is_applied_within_the_configured_bound():
    with _store_with_three_tests() as store:
        [row] = e1rm_calibration.build(store.connection)
    assert row.n == 3
    assert row.correction_applied is True
    assert 1.0 < row.correction_factor <= 1.10
    assert row.ci_low is not None and row.ci_low > 1.0


def test_three_identical_ratios_are_not_enough_when_the_ci_straddles_one():
    # This guards the implementation, not the statistics: with a single constant ratio the
    # bootstrap CI is degenerate, so the correction is applied. A mixed sample is the case
    # that must be refused.
    from strength_coach.features import e1rm_calibration as cal

    cfg = cal.E1RMCalibrationConfig.load()
    factor, low, high, applied, _ = cal._correction([0.98, 1.02, 1.00], cfg)
    assert applied is False
    assert factor == 1.0
    assert low <= 1.0 <= high


def test_the_prescription_applies_the_calibrated_factor_and_cites_it():
    from strength_coach.prescribe import build_prescription

    with _store_with_three_tests() as store:
        prescription = build_prescription(
            store.connection, for_date="2024-04-02", session_type="squat"
        )

    calibration = prescription.notes["e1rm_calibration"]["ssb_squat"]
    assert calibration["factor"] > 1.0
    squat = next(item for item in prescription.items if item.exercise_id == "ssb_squat")
    assert "MOD-E1RM-001" in squat.rationale_refs
    assert any("e1RM calibrated" in warning for warning in prescription.warnings)


def test_formula_only_lifts_are_still_shown_with_their_current_e1rm():
    with store_with_sets() as store:
        report = e1rm_calibration.build(store.connection, as_of="2024-01-02")

    [row] = report
    assert row.exercise_id == "ssb_squat"
    assert row.n == 0
    assert row.latest_e1rm is not None and row.latest_e1rm > 0
    assert row.latest_on == "2024-01-01"
    assert row.status == "no measured test; formula only"
