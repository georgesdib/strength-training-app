"""The command line, and the calibration loop it closes.

`run` must persist a critique and a prescription inside one trace; `review` must append
marks; `calibrate` must report from those marks. The loop is the product: every review should
leave the system with more evidence than before.
"""

from __future__ import annotations

import yaml

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.eval import load_marks
from strength_coach.store import db, importer

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5", "RIR": "2",
     "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30", "RIR": "3",
     "Reps_Done": "8"},
]


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "coach.db"
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()
    return path


def count(path, table: str) -> int:
    store = db.Store(path)
    try:
        return store.connection.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    finally:
        store.close()


def test_run_persists_a_critique_and_a_prescription(database, capsys):
    tables = ("critique", "rubric_score", "prescription", "prescription_item", "run", "run_event")
    before = {table: count(database, table) for table in tables}

    code = cli.main(["--db", str(database), "run", "--date", "2024-02-01"])
    assert code == 0

    out = capsys.readouterr().out
    assert "prescription 2024-02-01" in out
    assert "critique 2024-01-01" in out
    assert "PRG-RIR-001" in out

    after = {table: count(database, table) for table in tables}
    # The fixture import is itself a run; only the deltas belong to this command.
    assert after["critique"] - before["critique"] == 1
    assert after["rubric_score"] - before["rubric_score"] == 8
    assert after["prescription"] - before["prescription"] == 1
    assert after["prescription_item"] - before["prescription_item"] == 4
    assert after["run"] - before["run"] == 1
    assert after["run_event"] - before["run_event"] == 1
    run = db.Store(database)
    try:
        row = run.connection.execute("SELECT status FROM run").fetchone()
        assert row["status"] == "ok"
    finally:
        run.close()


def test_run_day_a_uses_the_a_template(tmp_path, capsys):
    path = tmp_path / "all_days.db"
    rows = []
    for day in ("2024-01-04", "2024-01-11"):
        rows += [
            {"Date": day, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Competition Bench Press", "Weight_Used": "80",
             "RIR": "2", "Reps_Done": "5"},
            {"Date": day, "Exercise": "Back Extension", "Weight_Used": "0",
             "RIR": "2", "Reps_Done": "12"},
            {"Date": day, "Exercise": "Lateral Raise", "Weight_Used": "12.5",
             "RIR": "2", "Reps_Done": "10"},
        ]
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    assert cli.main(["--db", str(path), "run", "--date", "2024-02-01", "--day", "A"]) == 0
    out = capsys.readouterr().out
    assert "day A" in out
    assert "ssb_squat" in out

    store = db.Store(path)
    try:
        row = store.connection.execute("SELECT session_day FROM prescription").fetchone()
        assert row["session_day"] == "A"
        item = store.connection.execute(
            "SELECT exercise_id FROM prescription_item ORDER BY order_index"
        ).fetchone()
        assert item["exercise_id"] == "ssb_squat"
    finally:
        store.close()


def test_rerunning_the_same_date_appends_nothing(database, capsys):
    cli.main(["--db", str(database), "run", "--date", "2024-02-01"])
    capsys.readouterr()
    before = {t: count(database, t) for t in ("critique", "prescription", "run")}

    assert cli.main(["--db", str(database), "run", "--date", "2024-02-01"]) == 0
    assert "already prescribed" in capsys.readouterr().out
    # V0-SCOPE §4.6: idempotent in content, no duplicate artifacts.
    assert {t: count(database, t) for t in before} == before

    # --force is the explicit way to regenerate.
    assert cli.main(["--db", str(database), "run", "--date", "2024-02-01", "--force"]) == 0
    assert count(database, "prescription") - before["prescription"] == 1


def test_review_records_marks_and_reports(database, tmp_path, capsys):
    scores = {
        item: 0.75
        for item in (
            "RIR_ADHERENCE", "PROGRESSION_ADHERENCE", "WEEKLY_SPINAL_COST",
            "ESSENTIAL_WORK", "REDUNDANCY", "ROTATION", "SESSION_DURATION", "VELOCITY_LOSS",
        )
    }
    labels = tmp_path / "marks.yaml"
    labels.write_text(yaml.safe_dump({
        "version": 1,
        "sessions": {"2024-01-01": {"confidence": "high", "scores": scores}},
    }), encoding="utf-8")

    code = cli.main([
        "--db", str(database), "review", "--session", "2024-01-01", "--scores", str(labels),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "recorded 8 marks" in out
    assert "headline" in out
    assert count(database, "rubric_mark") == 8


def test_review_interactively_takes_scores(database, monkeypatch, capsys):
    responses = iter(["0.9", "", "0.5", "", "", "", "", "", "high"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(responses))

    code = cli.main(["--db", str(database), "review", "--session", "2024-01-01"])
    assert code == 0
    # Two non-empty scores out of eight items, plus the confidence prompt.
    assert count(database, "rubric_mark") == 2

    store = db.Store(database)
    try:
        labels = load_marks(store.connection)
    finally:
        store.close()
    assert labels.sessions["2024-01-01"].confidence == "high"


def test_calibrate_without_marks_exits_two(database, capsys):
    code = cli.main(["--db", str(database), "calibrate"])
    assert code == 2
    assert "no marks yet" in capsys.readouterr().out


def test_calibrate_reports_after_a_review(database, tmp_path, capsys):
    scores = {"RIR_ADHERENCE": 0.9}
    labels = tmp_path / "marks.yaml"
    labels.write_text(yaml.safe_dump({
        "version": 1,
        "sessions": {"2024-01-01": {"confidence": "high", "scores": scores}},
    }), encoding="utf-8")
    cli.main(["--db", str(database), "review", "--session", "2024-01-01",
              "--scores", str(labels)])
    capsys.readouterr()

    assert cli.main(["--db", str(database), "calibrate"]) == 0
    out = capsys.readouterr().out
    assert "headline (high confidence only)" in out
    assert "RIR_ADHERENCE" in out


def test_review_of_an_unknown_session_fails_cleanly(database, capsys):
    code = cli.main(["--db", str(database), "review", "--session", "1999-01-01"])
    assert code == 2
    assert "session:" in capsys.readouterr().out

def test_review_with_no_marks_is_not_reported_as_success(database, tmp_path, capsys):
    labels = tmp_path / "empty.yaml"
    labels.write_text(yaml.safe_dump({
        "version": 1,
        "sessions": {"2024-01-01": {"scores": {}, "confidence": "high"}},
    }), encoding="utf-8")

    code = cli.main(["--db", str(database), "review", "--session", "2024-01-01",
                     "--scores", str(labels)])
    assert code == 2
    assert "still unreviewed" in capsys.readouterr().out
    assert count(database, "rubric_mark") == 0
