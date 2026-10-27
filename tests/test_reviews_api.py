"""The review API uses the same append-only feature as the CLI/dashboard."""

from __future__ import annotations

import json
import threading
import urllib.request

from conftest import make_readiness, make_training

from strength_coach.store import db, importer
from strength_coach.web.server import create_server


def _post(base: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode())


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path) as response:
        return json.loads(response.read().decode())


def test_reviews_endpoint_completes_a_periodic_task(tmp_path):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training([
        {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{"Date": "2024-01-01"}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()
    httpd = create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        before = _get(base, "/api/reviews?date=2024-01-15")
        task = next(t for t in before["tasks"] if t["key"] == "readiness_thresholds")
        assert task["status"] == "due"
        after = _post(base, "/api/reviews", {
            "task_key": "readiness_thresholds", "action": "completed",
            "date": "2024-01-15", "decision": "kept", "note": "test",
        })
        task = next(t for t in after["tasks"] if t["key"] == "readiness_thresholds")
        assert task["status"] == "not_due"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
