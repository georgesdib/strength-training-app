"""Strength fitness-fatigue shadow model: fit, refuse when unidentified, no load effect."""

from __future__ import annotations

from conftest import make_readiness, make_training

from strength_coach.features import fatigue_fitness
from strength_coach.store import db, importer


def store_with(rows):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_a_fit_is_reported_with_its_limits():
    rows = []
    for index, day in enumerate(
        ["2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29",
         "2024-02-05", "2024-02-12", "2024-02-19", "2024-02-26", "2024-03-04"]
    ):
        load = 80 + index * 4
        for _ in range(2 + index % 5):
            rows.append({"Date": day, "Exercise": "Safety Squat Bar",
                         "Weight_Used": str(load), "RIR": "2", "Reps_Done": "5"})
    with store_with(rows) as store:
        models = fatigue_fitness.compute(store.connection, "2024-03-05")

    assert models[0].exercise_id == "overall"
    model = next(m for m in models if m.exercise_id == "ssb_squat")
    assert model.n_observations >= 8
    assert model.status in {"ok", "weak fit", "unstable"}
    assert model.latest_e1rm is not None
    assert model.as_dict()["status"] == model.status


def test_insufficient_history_is_refused_rather_than_fitted():
    rows = [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "105",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        models = fatigue_fitness.compute(store.connection, "2024-01-09")
    model = next(m for m in models if m.exercise_id == "ssb_squat")
    assert model.status == "insufficient"
    assert model.predicted_e1rm is None
    assert model.params is None


def test_cli_fatigue_reports_the_shadow_model(tmp_path, capsys):
    from conftest import make_readiness, make_training

    from strength_coach import cli
    from strength_coach.store import db, importer

    rows = []
    for index, day in enumerate(
        ["2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29",
         "2024-02-05", "2024-02-12", "2024-02-19", "2024-02-26", "2024-03-04"]
    ):
        load = 80 + index * 4
        rows.append({"Date": day, "Exercise": "Safety Squat Bar",
                     "Weight_Used": str(load), "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{}])
    path = tmp_path / "coach.db"
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    assert cli.main(["--db", str(path), "fatigue", "--date", "2024-03-05"]) == 0
    out = capsys.readouterr().out
    assert "ssb_squat" in out and "shadow" in out
