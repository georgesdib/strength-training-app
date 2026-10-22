"""Retrospective walk-forward report: labels, no writes, no prescription effect."""

from __future__ import annotations

from contextlib import contextmanager

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.features import retrospective_validation
from strength_coach.store import db, importer

ROWS = [
    {"Date": f"2024-01-{day:02d}", "Exercise": "Safety Squat Bar",
     "Weight_Used": str(90 + day), "RIR": "2", "Reps_Done": "5"}
    for day in range(1, 15)
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


def test_report_is_labelled_retrospective_and_changes_nothing():
    with store_with() as store:
        before = store.connection.execute(
            "SELECT COUNT(*) AS c FROM prescription"
        ).fetchone()["c"]
        text = retrospective_validation.report(store.connection, max_dates=3)
        after = store.connection.execute(
            "SELECT COUNT(*) AS c FROM prescription"
        ).fetchone()["c"]

    assert "RETROSPECTIVE WALK-FORWARD" in text
    assert "not prospective" in text
    assert "No prescription" in text
    assert "VOLUME" in text
    assert before == after == 0


def test_validate_cli(tmp_path, capsys):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()
    assert cli.main(["--db", str(path), "validate", "--max-dates", "2"]) == 0
    assert "RETROSPECTIVE WALK-FORWARD" in capsys.readouterr().out
