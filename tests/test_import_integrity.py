"""Import atomicity: a failed import leaves no partial data."""

from __future__ import annotations

import pytest
from conftest import make_readiness, make_training

from strength_coach.store import db, importer

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


def test_failed_import_rolls_back_data_and_marks_run_error(monkeypatch):
    store = db.Store(":memory:")
    try:
        conn = store.connection
        training = make_training(ROWS)
        readiness = make_readiness([{"Date": "2024-01-01"}])

        def boom(*_args, **_kwargs):
            raise RuntimeError("injected import failure")

        monkeypatch.setattr(importer.repo, "store_clean_sets", boom)
        with pytest.raises(RuntimeError, match="injected import failure"):
            importer.import_export(
                conn, training, readiness,
                training_sha256=importer.sha256_frame(training),
                readiness_sha256=importer.sha256_frame(readiness),
            )
        assert conn.execute("SELECT COUNT(*) AS c FROM raw_row").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM clean_set").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM session").fetchone()["c"] == 0
        run = conn.execute(
            "SELECT status FROM run ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        assert run["status"] == "error"
    finally:
        store.close()
