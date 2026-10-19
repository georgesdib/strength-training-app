"""The local web UI: the API mirrors the core and the CLI remains untouched."""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path
import urllib.error
import urllib.request

import pytest

from conftest import make_readiness, make_training
from strength_coach.store import db, importer, repositories
from strength_coach.web import markdown
from strength_coach.web.server import create_server

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


@pytest.fixture
def server(tmp_path):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training(ROWS)
    readiness = make_readiness([{"Date": "2024-01-01"}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_athlete_constraint(
        store.connection, kind="injury", region="low_back", severity="monitor",
        forbidden_exercises=["back_extension"],
    )
    store.close()

    httpd = create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def get(base: str, path: str) -> tuple[int, str]:
    with urllib.request.urlopen(base + path) as response:
        return response.status, response.read().decode()


def post(base: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode())


def test_the_page_and_overview_are_served(server):
    status, page = get(server, "/")
    assert status == 200
    assert "Strength" in page

    status, body = get(server, "/api/overview")
    assert status == 200
    data = json.loads(body)
    assert data["sessions"][0]["session_id"] == "2024-01-01"


def test_prescribe_and_state_endpoints(server):
    data = post(server, "/api/prescribe", {"date": "2024-01-08", "day": "A"})
    assert data["session_day"] == "A"
    assert data["items"]

    status, body = get(server, "/api/state")
    assert status == 200
    state = json.loads(body)
    assert state["injury_signal"]["status"] in {
        "unknown", "insufficient", "active", "monitoring", "review"
    }
    assert state["constraints"][0]["forbidden_exercises"] == ["back_extension"]


def test_readiness_round_trip_uses_manual_source(server):
    data = post(server, "/api/readiness", {
        "date": "2024-01-01", "values": {"sleep": 2, "grip_strength_kg": 45.5},
        "note": "web",
    })
    assert data["sleep"] == 2
    assert data["sources"]["sleep"] == "manual"
    assert data["sources"]["energy"] == "import"
    assert data["grip_strength_kg"] == 45.5
    assert data["sources"]["grip_strength_kg"] == "manual"


def test_review_sheet_and_marks(server):
    data = get(server, "/api/review/2024-01-01")
    assert data[0] == 200
    sheet = json.loads(data[1])
    assert {item["key"] for item in sheet["items"]} >= {"RIR_ADHERENCE", "ROTATION"}

    saved = post(server, "/api/review/2024-01-01", {
        "scores": {"RIR_ADHERENCE": 1.0}, "confidence": "high",
    })
    assert saved["written"] == 1
    assert "session" in saved["calibration"]["text"]


def test_docs_are_rendered_local(server):
    status, body = get(server, "/api/docs")
    assert status == 200
    names = {entry["name"] for entry in json.loads(body)}
    assert "USER-GUIDE.md" in names

    status, body = get(server, "/api/docs/USER-GUIDE.md")
    assert status == 200
    assert "<h1>" in json.loads(body)["html"]


def test_markdown_tables_and_links():
    rendered = markdown.render("# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<h1>Title</h1>" in rendered
    assert "<table>" in rendered

    root = Path(__file__).resolve().parents[1]
    linked = markdown.render("[x](CONTINUITY.md)", docs_root=root, base_dir=root / "docs")
    assert 'href="/docs/CONTINUITY.md"' in linked

def test_upload_imports_both_csvs(server):
    training = make_training(ROWS).to_csv(index=False)
    readiness = make_readiness([{"Date": "2024-01-01"}]).to_csv(index=False)
    data = post(server, "/api/import", {
        "training": {"name": "training.csv", "text": training},
        "readiness": {"name": "readiness.csv", "text": readiness},
    })
    assert data["window_start"] == "2024-01-01"
    assert data["readiness_days"] >= 1
    assert data["sessions_written"] >= 1


def test_upload_requires_both_files(server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        post(server, "/api/import", {"training": {"name": "t.csv", "text": "x"}})
    assert excinfo.value.code == 400

def test_readiness_score_and_override(server):
    data = post(server, "/api/readiness", {
        "date": "2024-01-01",
        "values": {"sleep": 4, "energy": 4, "mood": 4, "soreness": 4, "stress": 4},
    })
    assert data["score"]["status"] == "ready"
    assert data["score"]["score"] == 0.8

    overridden = post(server, "/api/readiness/override", {
        "date": "2024-01-01", "scope": "global", "value": 0.5,
        "reason": "felt worse than the form",
    })
    assert overridden["score"]["score"] == 0.5


def test_prescribe_requires_readiness_for_today(server):
    today = date.today().isoformat()
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        post(server, "/api/prescribe", {"date": today, "day": "A"})
    assert excinfo.value.code == 409


def test_legacy_readiness_field_is_not_an_input(server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        post(server, "/api/readiness", {
            "date": "2024-01-01", "values": {"squat_readiness": 3},
        })
    assert excinfo.value.code == 400

def test_readiness_calibration_endpoint(server):
    status, body = get(server, "/api/readiness/calibrate")
    assert status == 200
    assert "readiness calibration" in json.loads(body)["text"]

def test_state_can_be_edited(server):
    state = post(server, "/api/state/profile", {
        "primary_goal": "strength",
        "goal_rank": ["strength", "longevity"],
        "focus_lifts": ["ssb_squat"],
        "sessions_per_week_target": 3,
        "max_session_minutes": 90,
        "block_start_date": "2024-01-01",
    })
    assert state["profile"]["primary_goal"] == "strength"
    assert state["profile"]["goal_rank"] == ["strength", "longevity"]

    post(server, "/api/state/constraint", {
        "kind": "injury", "region": "low_back", "severity": "monitor",
        "forbidden_exercises": ["good_morning"], "evidence": "test",
    })
    post(server, "/api/state/suitability", {
        "exercise_id": "ssb_squat", "can_do": True, "will_do": True,
        "feels_bad": False,
    })
    post(server, "/api/state/e1rm", {
        "exercise_id": "ssb_squat", "e1rm_kg": 155, "reason": "test",
    })
    post(server, "/api/state/test", {
        "exercise_id": "ssb_squat", "kg": 120, "reps": 3, "date": "2024-01-01",
    })
    post(server, "/api/state/symptom", {
        "region": "low_back", "level": 1, "settled": "yes",
    })
    state = post(server, "/api/state/block", {"date": "2024-01-01", "force": True})
    assert state["block_week"] == 1
    assert any(c["forbidden_exercises"] == ["good_morning"] for c in state["constraints"])
    assert state["suitability"]["ssb_squat"]["can_do"] == 1
    assert state["e1rm_overrides"]
    assert any(row["source"] == "measured" for row in state["e1rm_overrides"])
    assert state["symptoms"]

def test_exercise_catalogue_is_served(server):
    status, body = get(server, "/api/exercises")
    assert status == 200
    assert any(row["id"] == "ssb_squat" for row in json.loads(body))
