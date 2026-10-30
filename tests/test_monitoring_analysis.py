"""Read-only exploratory monitoring analysis tests."""

from __future__ import annotations

import hashlib
import json

from conftest import make_readiness, make_training

from strength_coach.store import db, importer
from tools import monitoring_analysis


def _store(tmp_path):
    path = tmp_path / "coach.db"
    rows = []
    for index, day in enumerate(("2024-01-01", "2024-01-08", "2024-01-15", "2024-01-22")):
        rows.append({"Date": day, "Exercise": "Competition Squat",
                     "Weight_Used": str(100 + index * 5), "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([{"Date": row["Date"]} for row in rows])
    store = db.Store(path)
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()
    return path


def test_analysis_is_deterministic_and_read_only(tmp_path):
    path = _store(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    output = tmp_path / "analysis.json"
    assert monitoring_analysis.main([
        "--db", str(path), "--out", str(output), "--format", "json",
        "--as-of", "2024-01-31",
    ]) == 0
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = json.loads(output.read_text())
    assert before == after
    assert payload["meta"]["read_only"] is True
    assert payload["meta"]["seed"] == 0
    assert payload["dose"]
    assert payload["associations"]


def test_analysis_default_output_is_private(tmp_path, monkeypatch):
    path = _store(tmp_path)
    output = tmp_path / "analysis.md"
    assert monitoring_analysis.main([
        "--db", str(path), "--out", str(output), "--as-of", "2024-01-31",
    ]) == 0
    text = output.read_text()
    assert "Monitoring exploratory analysis" in text
    assert "Descriptive associations only" in text
