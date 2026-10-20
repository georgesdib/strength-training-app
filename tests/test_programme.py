"""Rolling programme forecast and reactive deload."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.features import programme
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


@contextmanager
def store_with(rows=ROWS):
    training = make_training(rows)
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


def test_programme_is_a_weekday_abc_forecast_and_persists_nothing():
    with store_with() as store:
        before = store.connection.execute(
            "SELECT COUNT(*) AS c FROM prescription"
        ).fetchone()["c"]
        entries = programme.build_programme(
            store.connection, start="2024-01-02", weeks=2,
            per_week=3, start_day="A",
        )
        after = store.connection.execute(
            "SELECT COUNT(*) AS c FROM prescription"
        ).fetchone()["c"]

    assert len(entries) == 6
    assert [e.day for e in entries] == ["A", "B", "C", "A", "B", "C"]
    assert all(dt.date.fromisoformat(e.on_date).weekday() in (0, 2, 4) for e in entries)
    assert before == after == 0


def test_two_flaring_sessions_trigger_a_reactive_deload():
    rows = ROWS + [
        {"Date": "2024-01-03", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "3"},
        {"Date": "2024-01-03", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "80",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        conn = store.connection
        for day in ("2024-01-01", "2024-01-03"):
            repositories.append_symptom(
                conn, logged_on=day, timing="pre_session", region="low_back",
                level=2, settled_within_48h=0,
            )
        entries = programme.build_programme(
            conn, start="2024-01-04", weeks=1, per_week=3, start_day="A",
        )

    assert entries[0].deload_reason is not None
    assert entries[0].prescription.fallback_level == "fatigue_reduced"
    assert "reactive deload" in " ".join(entries[0].prescription.warnings)


def test_programme_cli_prints_a_horizon(tmp_path, capsys):
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

    assert cli.main(["--db", str(path), "programme", "--weeks", "2",
                     "--start", "2024-01-02", "--start-day", "A"]) == 0
    out = capsys.readouterr().out
    assert "forecast only" in out
    assert "2024-01-03" in out
    assert "Day A" not in out  # column format, not prose
