"""Performance CLI parity tests."""

from __future__ import annotations

import json

from conftest import make_readiness, make_training

from strength_coach import cli
from strength_coach.store import db, importer


def test_performance_cli_e1rm_json(tmp_path, capsys):
    path = tmp_path / "coach.db"
    training = make_training([
        {"Date": "2024-01-01", "Exercise": "Competition Squat",
         "Weight_Used": "100", "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-08", "Exercise": "Competition Squat",
         "Weight_Used": "105", "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{"Date": "2024-01-01"}, {"Date": "2024-01-08"}])
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    assert cli.main([
        "--db", str(path), "performance", "e1rm",
        "--exercise", "competition_squat", "--from", "2024-01-01",
        "--to", "2024-01-31", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["basis"] == "raw_formula_epley_rir"
    assert len(payload["points"]) == 2
