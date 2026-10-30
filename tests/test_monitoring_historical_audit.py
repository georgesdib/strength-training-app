"""Synthetic tests for the Phase 0 historical audit."""

from __future__ import annotations

import hashlib
import json

from conftest import make_readiness, make_training

from strength_coach.features import high_intensity_exposure
from strength_coach.features import strength_observations as obs
from strength_coach.store import db, importer
from strength_coach.store import repositories as repo
from tools import monitoring_historical_audit as audit


def _store(tmp_path, *, include_power=False):
    database = db.Store(tmp_path / "coach.db")
    dates = ["2024-01-01", "2024-01-03", "2024-01-05"]
    rows = [
        {
            "Date": date,
            "Workout": "Sheiko",
            "Exercise": "Competition Squat",
            "Weight_Used": str(100 + index * 5),
            "Reps_Done": "5",
            "RIR": "2",
        }
        for index, date in enumerate(dates)
    ] + [
        {
            "Date": date,
            "Workout": "Sheiko",
            "Exercise": "Bench Press",
            "Weight_Used": "80",
            "Reps_Done": "5",
            "RIR": "2",
        }
        for date in dates
    ]
    readiness_dates = list(dates)
    if include_power:
        rows.append(
            {
                "Date": "2024-01-06",
                "Workout": "Sheiko",
                "Exercise": "Jump Squats",
                "Weight_Used": "20",
                "Reps_Done": "5",
                "RIR": "2",
            }
        )
        readiness_dates.append("2024-01-06")
    training = make_training(rows)
    readiness = make_readiness([{"Date": date} for date in readiness_dates])
    importer.import_export(
        database.connection,
        training,
        readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return database


def _add_measured_tests(conn):
    for index, date in enumerate(["2024-01-10", "2024-01-17", "2024-02-01"]):
        override_id = repo.append_e1rm_override(
            conn,
            exercise_id="competition_squat",
            e1rm_kg=130.0 + index,
            effective_from=date,
            source="measured",
        )
        high_intensity_exposure.register_test(
            conn,
            override_id=override_id,
            exercise_id="competition_squat",
            performed_on=date,
            test_type="3RM",
        )


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_audit_reports_coverage_and_no_measured_tests(tmp_path):
    database = _store(tmp_path)
    try:
        report = audit.build_audit(
            database.connection,
            as_of="2024-02-10",
            db_path=database.path,
        )
    finally:
        database.close()

    assert report["inventory"]["sets"] == 6
    assert report["inventory"]["sessions"] == 3
    assert report["inventory"]["exercises"] == 2
    assert report["measured_tests"]["recorded"] == 0
    assert report["calibration"]["eligible_points"] == 0
    assert report["monitoring"]["descriptive_series_possible"] is True
    assert report["meta"]["calibration_applied_to_raw_series"] is False
    assert report["meta"]["age_decay_applied_to_raw_series"] is False
    assert "no measured" in " ".join(report["limitations"]).lower()


def test_audit_links_measured_tests_and_reports_calibration(tmp_path):
    database = _store(tmp_path)
    try:
        _add_measured_tests(database.connection)
        report = audit.build_audit(
            database.connection,
            as_of="2024-02-10",
            db_path=database.path,
        )
    finally:
        database.close()

    measured = report["measured_tests"]
    calibration = report["calibration"]
    assert measured["recorded"] == 3
    assert measured["linked"] == 3
    assert measured["with_prior_raw"] == 3
    assert measured["test_types"] == {"3RM": 3}
    assert calibration["recorded_measured"] == 3
    assert calibration["eligible_points"] == 3
    assert calibration["rows"]
    row = calibration["rows"][0]
    assert row["exercise_id"] == "competition_squat"
    assert row["point_count"] == 3
    assert row["factor"] is not None
    assert row["ci_low"] is not None
    assert row["ci_high"] is not None
    assert row["leave_one_out"]["factor_min"] is not None


def test_audit_reports_power_and_exposure_exclusions(tmp_path):
    database = _store(tmp_path, include_power=True)
    try:
        set_row = database.connection.execute(
            "SELECT set_id, session_id FROM clean_set "
            "WHERE exercise_id = 'competition_squat' ORDER BY set_id LIMIT 1"
        ).fetchone()
        repo.append_high_intensity_exposure(
            database.connection,
            performed_on="2024-01-01",
            kind="max_attempt",
            exercise_id="competition_squat",
            session_id=str(set_row["session_id"]),
            set_id=int(set_row["set_id"]),
            region_load="lower",
            source="set_link",
            source_id=f"set:{int(set_row['set_id'])}",
        )
        report = audit.build_audit(
            database.connection,
            as_of="2024-02-10",
            db_path=database.path,
        )
    finally:
        database.close()

    reasons = report["eligibility"]["reasons"]
    exclusions = report["eligibility"]["exclusions"]
    assert exclusions["power_sets"] >= 1
    assert exclusions["set_linked_total"] == 1
    assert exclusions["set_linked_by_kind"] == {"max_attempt": 1}
    assert any(obs.REASON_POWER in reason for reason in reasons)
    assert any(obs.REASON_EXPOSURE_PREFIX in reason for reason in reasons)
    assert report["inventory"]["warmup_sets"] == 0
    assert report["inventory"]["warmup_share"] == 0.0
    by_exercise = {row["exercise_id"]: row for row in report["eligibility"]["by_exercise"]}
    assert "jump_squats" in by_exercise
    assert by_exercise["competition_squat"]["rep_ranges"]["1-5"] >= 1
    assert "rir_missing" in by_exercise["competition_squat"]


def test_missing_database_returns_error(tmp_path, capsys):
    output = tmp_path / "audit.md"
    code = audit.main(
        [
            "--db",
            str(tmp_path / "missing.db"),
            "--out",
            str(output),
            "--as-of",
            "2024-02-10",
        ]
    )

    assert code == 2
    assert "does not exist" in capsys.readouterr().err
    assert not output.exists()


def test_malformed_database_returns_error(tmp_path, capsys):
    bad = tmp_path / "bad.db"
    bad.write_text("not a sqlite database")
    output = tmp_path / "audit.md"
    code = audit.main(
        [
            "--db",
            str(bad),
            "--out",
            str(output),
            "--as-of",
            "2024-02-10",
        ]
    )

    assert code == 2
    assert "audit error" in capsys.readouterr().err
    assert not output.exists()


def test_deterministic_markdown_output(tmp_path):
    database = _store(tmp_path)
    try:
        first = audit.build_audit(database.connection, as_of="2024-02-10")
        second = audit.build_audit(database.connection, as_of="2024-02-10")
    finally:
        database.close()

    assert audit.render_markdown(first) == audit.render_markdown(second)


def test_audit_is_deterministic_and_json_serialisable(tmp_path):
    database = _store(tmp_path)
    try:
        first = audit.build_audit(database.connection, as_of="2024-02-10")
        second = audit.build_audit(database.connection, as_of="2024-02-10")
    finally:
        database.close()

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_cli_is_read_only_and_defaults_to_a_private_report(tmp_path):
    database = _store(tmp_path)
    database.close()
    path = tmp_path / "coach.db"
    before = _hash(path)
    output = tmp_path / "audit.md"

    code = audit.main(
        [
            "--db",
            str(path),
            "--out",
            str(output),
            "--as-of",
            "2024-02-10",
        ]
    )

    assert code == 0
    assert _hash(path) == before
    text = output.read_text()
    assert "# Monitoring historical audit" in text
    assert "Calibration applied to raw series: False" in text
    assert "Measured tests recorded: 0" in text


def test_cli_json_output(tmp_path):
    database = _store(tmp_path)
    database.close()
    output = tmp_path / "audit.json"

    code = audit.main(
        [
            "--db",
            str(database.path),
            "--out",
            str(output),
            "--format",
            "json",
            "--as-of",
            "2024-02-10",
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text())
    assert payload["meta"]["read_only"] is True
    assert payload["inventory"]["exercises"] == 2
