"""Read-only exploratory monitoring analysis tests."""

from __future__ import annotations

import hashlib
import json
import subprocess

import pandas as pd
from conftest import make_readiness, make_training

from strength_coach.features import monitoring_analysis as analysis_service
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


def test_tonnage_distinguishes_zero_from_missing():
    empty = pd.DataFrame()
    assert analysis_service._session_tonnage(empty, empty) == (0.0, "zero_no_sets")

    timed = pd.DataFrame([{"tonnage_kg": None}])
    assert analysis_service._session_tonnage(timed, timed) == (
        None, "unavailable_missing_tonnage"
    )

    zero = pd.DataFrame([{"tonnage_kg": 0.0}])
    assert analysis_service._session_tonnage(zero, zero) == (0.0, "observed_zero")


def test_analysis_association_statuses_are_explicit():
    assert analysis_service._corr([(1.0, 2.0)])["status"] == "insufficient"
    assert analysis_service._corr([(1.0, 2.0), (1.0, 3.0), (1.0, 4.0)])["status"] == "no_variation"


def test_analysis_default_output_is_private(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitignore").write_text("private/\n", encoding="utf-8")
    path = _store(tmp_path)
    monkeypatch.chdir(repo)

    assert monitoring_analysis.main(["--db", str(path), "--as-of", "2024-01-31"]) == 0
    output = repo / "private" / "docs" / "MONITORING-ANALYSIS.md"
    assert output.is_file()
    subprocess.run(
        ["git", "check-ignore", "-q", str(output)], cwd=repo, check=True
    )
    tracked = subprocess.run(
        ["git", "ls-files", "--", str(output)], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout
    assert tracked.strip() == ""
    assert "Monitoring exploratory analysis" in output.read_text()
