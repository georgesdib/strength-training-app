"""The command line: the deterministic slice and its read-only reports.

`run` must persist a prescription inside one trace. The rubric calibration loop is retired
(DEC-EVAL-09), so there is no `review` or `calibrate` command; `observations` reports the
AFC-3 longitudinal observations.
"""

from __future__ import annotations

import datetime
import json

import pytest
from conftest import make_readiness, make_training

from strength_coach import cli
from strength_coach.store import db, importer
from strength_coach.utils import paths

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5", "RIR": "2",
     "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30", "RIR": "3",
     "Reps_Done": "8"},
    {"Date": "2024-01-01", "Exercise": "Lying Leg Curls", "Weight_Used": "30", "RIR": "2",
     "Reps_Done": "10"},
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


def test_resolver_policy_validation_and_preview_failure(capsys):
    code = cli.main([
        "resolver", "validate", "--file", str(paths.template_resolver_yaml()),
    ])
    assert code == 0
    assert "resolver policy valid" in capsys.readouterr().out

    code = cli.main(["resolver", "policy", "show"])
    assert code == 0
    assert "digest" in capsys.readouterr().out


def test_resolver_preview_enforces_readiness_and_date_rules(database, capsys):
    today = datetime.date.today().isoformat()
    code = cli.main([
        "--db", str(database), "resolver", "preview", "--date", today,
        "--session-type", "squat",
    ])
    assert code == 2
    assert "readiness required" in capsys.readouterr().out

    code = cli.main([
        "--db", str(database), "resolver", "preview", "--date", "not-a-date",
    ])
    assert code == 2
    assert "YYYY-MM-DD" in capsys.readouterr().out

    code = cli.main([
        "--db", str(database), "resolver", "preview", "--date", today,
        "--session-type", "squat", "--allow-unknown-readiness", "--json",
    ])
    assert code == 2
    assert '"stage": "dispatch"' in capsys.readouterr().out


def test_cli_resolver_enable_requires_acknowledgement(database, capsys):
    code = cli.main([
        "--db", str(database), "settings", "profile", "set",
        "resolver.enabled=true", "--date", "2024-01-01",
    ])
    assert code == 2
    assert "resolver.enabled requires explicit confirmation" in capsys.readouterr().out

    code = cli.main([
        "--db", str(database), "settings", "profile", "set",
        "resolver.enabled=true", "--date", "2024-01-01",
        "--resolver-enable-confirm",
    ])
    assert code == 0
    assert "settings profile" in capsys.readouterr().out


def test_run_persists_a_prescription_without_a_critique(database, capsys):
    tables = ("critique", "rubric_score", "prescription", "prescription_item", "run", "run_event")
    before = {table: count(database, table) for table in tables}

    code = cli.main(["--db", str(database), "run", "--date", "2024-02-01", "--session-type", "hinge"])
    assert code == 0

    out = capsys.readouterr().out
    assert "prescription 2024-02-01" in out
    assert "critique" not in out.lower()
    assert "PRG-RIR-001" in out

    after = {table: count(database, table) for table in tables}
    # The fixture import is itself a run; only the deltas belong to this command.
    # The rubric is retired, so a prescription writes no critique or rubric rows.
    assert after["critique"] - before["critique"] == 0
    assert after["rubric_score"] - before["rubric_score"] == 0
    assert after["prescription"] - before["prescription"] == 1
    assert after["prescription_item"] - before["prescription_item"] == 7  # + knee flexion + broad jump
    assert after["run"] - before["run"] == 1
    assert after["run_event"] - before["run_event"] == 1
    run = db.Store(database)
    try:
        row = run.connection.execute("SELECT status FROM run").fetchone()
        assert row["status"] == "ok"
    finally:
        run.close()


def test_exposure_ratio_prints_the_read_only_report(database, capsys):
    code = cli.main(["--db", str(database), "exposure", "ratio", "--date", "2024-01-31"])
    assert code == 0
    out = capsys.readouterr().out
    assert "hard-set exposure 2024-01-31" in out
    assert "descriptive only" in out
    assert "abstained:" in out  # the fixture has no chronic-window work for that date


def test_programme_rejects_an_unbounded_horizon(tmp_path, capsys):
    code = cli.main(["--db", str(tmp_path / "x.db"), "programme", "--weeks", "27"])
    assert code == 2
    assert "between 1 and 26" in capsys.readouterr().out


def test_run_squat_uses_the_squat_template(tmp_path, capsys):
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

    assert cli.main(["--db", str(path), "run", "--date", "2024-02-01", "--session-type", "squat"]) == 0
    out = capsys.readouterr().out
    assert "squat" in out
    assert "ssb_squat" in out

    store = db.Store(path)
    try:
        row = store.connection.execute("SELECT session_type FROM prescription").fetchone()
        assert row["session_type"] == "squat"
        items = [
            row["exercise_id"] for row in store.connection.execute(
                "SELECT exercise_id FROM prescription_item ORDER BY order_index"
            )
        ]
        # The contract is "power before the main lift", not a hardcoded index.
        assert "box_jump" in items
        assert "ssb_squat" in items
        assert items.index("box_jump") < items.index("ssb_squat")
    finally:
        store.close()


def test_rerunning_the_same_date_appends_nothing(database, capsys):
    cli.main(["--db", str(database), "run", "--date", "2024-02-01", "--session-type", "hinge"])
    capsys.readouterr()
    before = {t: count(database, t) for t in ("critique", "prescription", "run")}

    assert cli.main(["--db", str(database), "run", "--date", "2024-02-01", "--session-type", "hinge"]) == 0
    assert "already prescribed" in capsys.readouterr().out
    # V0-SCOPE §4.6: idempotent in content, no duplicate artifacts.
    assert {t: count(database, t) for t in before} == before

    # --force is the explicit way to regenerate.
    assert cli.main(["--db", str(database), "run", "--date", "2024-02-01", "--force"]) == 0
    assert count(database, "prescription") - before["prescription"] == 1


def test_observations_command_reports_and_abstains(database, capsys):
    assert cli.main([
        "--db", str(database), "observations", "--date", "2024-03-01",
    ]) == 0
    out = capsys.readouterr().out
    assert "observations 2024-01-05 .. 2024-03-01" in out
    assert "abstain" in out

    assert cli.main([
        "--db", str(database), "observations", "--date", "2024-03-01", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "observations" in payload and "abstain" in payload
