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
    assert "Programme" in page and "Terminal" in page
    # CLI/UI parity: the recent capture surfaces are reachable from the shell.
    assert "Cardio" in page and "Measures" in page
    assert "cardio-weeks" in page
    assert "fatigue-model" in page
    assert "selection-result" in page
    # Import page explains that calibration is a later, separate step.
    assert "After the import" in page and "import-next" in page
    assert "calibration is not an import step" in page

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
    assert isinstance(state["e1rm_calibration"], list)


def test_readiness_round_trip_uses_manual_source(server):
    data = post(server, "/api/readiness", {
        "date": "2024-01-01", "values": {"sleep": 2, "bodyweight_kg": 80.5},
        "note": "web",
    })
    assert data["sleep"] == 2
    assert data["sources"]["sleep"] == "manual"
    assert data["sources"]["energy"] == "import"
    assert data["bodyweight_kg"] == 80.5
    assert data["sources"]["bodyweight_kg"] == "manual"
    assert data["volume_valve"]["enabled"] is True
    assert data["volume_valve"]["sets"] == 1


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

def test_rubric_calibration_endpoint(server):
    status, body = get(server, "/api/calibrate")
    assert status == 200
    assert "no marks yet" in json.loads(body)["text"]

def post_status(base: str, path: str, payload: dict) -> tuple[int, str]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_programme_endpoint(server):
    data = post(server, "/api/programme", {
        "weeks": 2, "start": "2024-01-02", "start_day": "A",
    })
    assert len(data["entries"]) == 6
    assert data["entries"][0]["date"] == "2024-01-03"
    assert data["entries"][0]["day"] == "A"
    assert data["entries"][0]["prescription"]["items"]


def test_terminal_accepts_only_strength_coach(server):
    status, body = post_status(server, "/api/terminal", {"command": "ls"})
    assert status == 400
    assert "only strength-coach" in body

    status, body = post_status(server, "/api/terminal", {
        "command": "strength-coach web",
    })
    assert status == 400
    assert "cannot run" in body

    status, body = post_status(server, "/api/terminal", {
        "command": "strength-coach state --db other.db",
    })
    assert status == 400
    assert "--db" in body

    status, body = post_status(server, "/api/terminal", {
        "command": "strength-coach review",
    })
    assert status == 400
    assert "interactive" in body


def test_terminal_runs_a_valid_command(server):
    status, body = post_status(server, "/api/terminal", {
        "command": "strength-coach programme --weeks 1 --start 2024-01-02 --start-day A",
    })
    assert status == 200
    data = json.loads(body)
    assert data["returncode"] == 0
    assert "forecast only" in data["output"]

def test_readiness_settings_and_shadow_endpoints(server):
    data = post(server, "/api/readiness/settings", {
        "date": "2024-01-01",
        "baseline_days": 14,
        "baseline_min_readings": 4,
        "hrv_slope": 0.4,
        "rhr_slope": 0.4,
        "hrv_weight": 0.4,
        "rhr_weight": 0.4,
        "wearable_weight": 0.1,
    })
    assert data["settings"]["setting_source"] == "athlete"
    assert data["settings"]["baseline_days"] == 14

    status, body = get(server, "/api/readiness/shadow")
    assert status == 200
    assert "SHADOW BASELINE" in json.loads(body)["text"]


def test_cardio_round_trip_and_overview(server):
    today = date.today().isoformat()
    data = post(server, "/api/cardio", {
        "date": today, "modality": "walk", "minutes": 30,
        "avg_hr": 110, "max_hr": 130, "srpe": 3,
    })
    assert data["sessions"] == 1
    assert data["total_minutes"] == 30.0
    assert data["by_modality"] == {"walk": 1}

    status, body = get(server, "/api/cardio?weeks=4")
    assert status == 200
    assert json.loads(body)["sessions"] == 1

    # The API accepts the same window anchor as `cardio --show --date`.
    status, body = get(server, f"/api/cardio?weeks=4&date={today}")
    assert status == 200
    assert json.loads(body)["to_date"] == today

    overview = json.loads(get(server, "/api/overview")[1])
    assert overview["cardio"]["sessions"] == 1
    assert overview["cardio"]["reference_min"] == 150


def test_measurements_round_trip(server):
    data = post(server, "/api/measurements", {
        "metric": "vo2max", "value": 45.2, "date": "2024-01-02",
        "method": "step test",
    })
    row = next(r for r in data["summary"] if r["key"] == "vo2max")
    assert row["latest_value"] == 45.2
    assert row["latest_on"] == "2024-01-02"
    assert data["entries"][-1]["method"] == "step test"

    status, body = get(server, "/api/measurements")
    assert status == 200
    assert json.loads(body)["entries"][-1]["value"] == 45.2


def test_review_accepts_optional_session_detail(server):
    data = post(server, "/api/review/2024-01-01", {
        "scores": {"RIR_ADHERENCE": 0.9},
        "confidence": "high",
        "session_rpe": 7,
        "session_minutes": 75,
    })
    assert data["feedback"]["srpe"] == 7
    assert data["feedback"]["duration_min"] == 75

    status, body = get(server, "/api/review/2024-01-01")
    assert status == 200
    assert json.loads(body)["feedback"]["srpe"] == 7

    # Session detail can be saved without adding marks (the review stays optional).
    data = post(server, "/api/review/2024-01-01", {"scores": {}, "session_rpe": 8})
    assert data["written"] == 0
    assert data["feedback"]["srpe"] == 8


def test_fatigue_model_endpoint_is_shadow_only(server):
    status, body = get(server, "/api/fatigue")
    assert status == 200
    data = json.loads(body)
    assert data["on_date"]
    assert isinstance(data["models"], list)


def test_exercise_selection_endpoint_is_shadow_only(server):
    status, body = get(server, "/api/selection?date=2024-01-01&day=B")
    assert status == 200
    data = json.loads(body)
    assert data["day"] == "B"
    assert isinstance(data["slots"], list)


def test_exercise_catalog_endpoint(server):
    status, body = get(server, "/api/exercises/catalog")
    assert status == 200
    data = json.loads(body)
    assert data["entities"]
    assert "patterns" in data
    assert any(row["id"] == "ssb_squat" for row in data["entities"])


def test_exercise_post_rejects_an_invalid_id_without_writing(server):
    status, _ = post_status(server, "/api/exercises", {
        "id": "Bad Id",
        "props": {"display": "Bad", "log_names": ["Bad"], "pattern": "squat"},
    })
    assert status == 400


def test_prescribe_can_apply_selection(server):
    data = post(server, "/api/prescribe", {
        "date": "2024-01-15", "day": "A", "apply_selection": True,
    })
    assert data["notes"]["selection"]["applied"] is True
    assert "selection" in data["notes"]


def test_continuity_calibration_endpoint(server):
    status, body = get(server, "/api/continuity?date=2024-01-15")
    assert status == 200
    data = json.loads(body)
    assert data["on_date"] == "2024-01-15"
    assert "bands" in data["calibration"]
    assert isinstance(data["allow_relax_fixed"], bool)


def test_prescribe_accepts_a_session_type(server):
    data = post(server, "/api/prescribe", {
        "date": "2024-01-15", "session_type": "hinge",
    })
    assert data["session_type"] == "hinge"
    assert data["session_day"] == "B"
    assert any(row["exercise_id"] == "trap_bar_deadlift" for row in data["items"])


def test_prescribe_auto_session_type_is_rolling(server):
    data = post(server, "/api/prescribe", {"date": "2024-01-15"})
    assert data["session_type"] in {"squat", "hinge", "bench_squat", "bench_hinge"}


def test_volume_ledger_endpoint(server):
    status, body = get(server, "/api/volume?date=2024-01-15&weeks=4")
    assert status == 200
    data = json.loads(body)
    assert "patterns" in data
    assert data["window_weeks"] == 4
    assert any(row["mrv"] is not None for row in data["patterns"])
