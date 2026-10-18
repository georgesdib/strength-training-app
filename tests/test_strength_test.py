"""Strength tests: a measured e1RM with a declared-test exception.

A test is an assessment, not a training set. It is stored as an e1RM override (source=measured)
and never enters clean_sets, so it cannot count as volume or trip the RIR rule. A true 1RM is
allowed but requires --max, confirmation, and a minimum interval.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer, queries

HISTORY = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
]


def prepare(tmp_path):
    path = tmp_path / "coach.db"
    training = make_training(HISTORY)
    readiness = make_readiness([{}])
    store = db.Store(path)
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
    finally:
        store.close()
    return path


def run_cli(path, *args):
    return cli.main(["--db", str(path), "test", *args])


def test_3rm_records_a_measured_override_and_feeds_the_prescription(tmp_path, capsys):
    path = prepare(tmp_path)
    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "140", "--reps", "3",
                   "--date", "2024-01-15", "--yes") == 0
    out = capsys.readouterr().out
    assert "e1RM 154.0 kg" in out
    assert "e1rm_override:" in out

    expected = e1rm_mod.epley_rir_adjusted(140, 3, 0)
    store = db.Store(path)
    try:
        row = queries.e1rm_override(store.connection, "ssb_squat", "2024-02-01")
        assert row["e1rm_kg"] == pytest.approx(expected)
        assert row["source"] == "measured"
        prescription = build_prescription(store.connection, for_date="2024-02-01",
                                          session_day="A")
    finally:
        store.close()

    squat = next(i for i in prescription.items if i.exercise_id == "ssb_squat")
    # 154 / (1 + (3+2)/30) = 132.0, rounded down to 0.5
    assert squat.load_kg == pytest.approx(132.0)
    assert squat.rationale_refs[1].startswith("e1rm_override:")


def test_a_supplied_e1rm_overrides_the_formula(tmp_path, capsys):
    path = prepare(tmp_path)
    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "140", "--reps", "3",
                   "--date", "2024-01-15", "--e1rm", "160", "--yes") == 0
    out = capsys.readouterr().out
    assert "using the supplied e1RM instead: 160.0 kg" in out

    store = db.Store(path)
    try:
        row = queries.e1rm_override(store.connection, "ssb_squat", "2024-02-01")
        assert row["e1rm_kg"] == pytest.approx(160.0)
    finally:
        store.close()


def test_a_single_rep_needs_the_max_flag(tmp_path, capsys):
    path = prepare(tmp_path)
    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "160", "--reps", "1",
                   "--date", "2024-01-15") == 2
    assert "true 1RM" in capsys.readouterr().out

    store = db.Store(path)
    try:
        assert queries.last_measured_override(store.connection, "ssb_squat") is None
    finally:
        store.close()


def test_declining_a_1rm_records_nothing(tmp_path, monkeypatch):
    path = prepare(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "160", "--reps", "1",
                   "--date", "2024-01-15", "--max") == 1

    store = db.Store(path)
    try:
        assert queries.last_measured_override(store.connection, "ssb_squat") is None
    finally:
        store.close()


def test_a_second_1rm_within_the_interval_is_refused_unless_forced(tmp_path, capsys):
    path = prepare(tmp_path)
    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "160", "--reps", "1",
                   "--date", "2024-01-01", "--max", "--yes") == 0
    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "165", "--reps", "1",
                   "--date", "2024-01-15", "--max", "--yes") == 2
    assert "minimum interval" in capsys.readouterr().out

    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "165", "--reps", "1",
                   "--date", "2024-01-15", "--max", "--yes", "--force") == 0


def test_frequent_submaximal_testing_warns_but_records(tmp_path, capsys):
    path = prepare(tmp_path)
    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "140", "--reps", "3",
                   "--date", "2024-01-01", "--yes") == 0
    assert run_cli(path, "--exercise", "ssb_squat", "--kg", "145", "--reps", "3",
                   "--date", "2024-01-08", "--yes") == 0
    out = capsys.readouterr().out
    assert "stimulus, not a measurement" in out
