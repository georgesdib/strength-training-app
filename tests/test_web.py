"""The local web UI: the API mirrors the core and the CLI remains untouched."""

from __future__ import annotations

import json
import re
import threading
from datetime import date
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import quote

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
    assert "prescribe-selection-confirm" in page
    assert "Apply selection:" in page
    assert "class A" in page and "class B" in page and "class C" in page
    assert "prescribe-minimum-options" in page
    assert "Only used when minimum session is ticked" in page
    assert "A/B/C remains" not in page
    assert "Language model" in page
    assert "Regime change" in page
    assert "rejected as predictor" in page
    assert 'id="toast"' in page
    assert 'id="settings-theme"' in page
    assert 'id="form-trend-result"' in page
    assert 'id="form-followup"' in page
    assert "selection-include-different" in page
    assert "validation-run" in page
    assert "view-workout" in page
    assert "sidebar" in page and "menu-toggle" in page
    assert "section-help" in page
    assert "docs/UI-MAP.md" in page
    assert "view-history" in page and "history.js" in page
    assert "view-longevity" in page and "longevity-form" in page
    assert "workout.js" in page
    assert page.count('class="section-help"') >= 60
    assert page.count("#docs?doc=") >= 50
    assert "&amp;anchor=" in page  # nested/dialog links use section anchors
    # The guided workflow owns readiness → preview → workout → post-workout.
    assert page.index('id="workflow-readiness"') < page.index('id="workflow-preview"')
    assert page.index('id="workflow-preview"') < page.index('id="workout-start-panel"')
    assert page.index('id="workout-start-panel"') < page.index('id="workout-active-panel"')
    assert page.index('id="workout-active-panel"') < page.index('id="workout-ended-panel"')
    assert 'data-workflow-step="post"' in page
    assert 'id="readiness-form"' in page and 'id="prescribe-form"' in page
    assert 'id="workflow-ack"' in page and 'id="workout-start-ack"' in page
    assert "Exercise details" in page  # dialog remains a P2 subsection
    # CLI/UI parity: the recent capture surfaces are reachable from the shell.
    assert "Cardio" in page and "Measures" in page
    assert "cardio-weeks" in page
    assert "fatigue-model" in page
    assert "selection-result" in page
    assert 'id="programme-apply-selection"' in page
    assert 'id="programme-selection-llm"' in page
    assert 'id="programme-selection-confirm"' in page
    # Import page explains that calibration is a later, separate step.
    assert "After the import" in page and "import-next" in page
    assert "calibration is not an import step" in page

    status, body = get(server, "/api/overview")
    assert status == 200
    data = json.loads(body)
    assert data["sessions"][0]["session_id"] == "2024-01-01"
    assert data["form_evaluation"]["target_events"] == 10


def test_every_ui_doc_link_resolves_through_the_api(server):
    status, page = get(server, "/")
    assert status == 200
    hrefs = set(re.findall(r'href="#docs\?doc=([^"&]+)', page))
    status, script = get(server, "/static/app.js")
    assert status == 200
    hrefs |= set(re.findall(r"#docs\?doc=([^\"&]+)", script))
    hrefs = {name for name in hrefs if "{" not in name and "}" not in name}
    assert hrefs
    for name in sorted(hrefs):
        doc_status, body = get(server, "/api/docs/" + quote(name, safe=""))
        assert doc_status == 200, name
        assert json.loads(body)["name"] == name


def test_ui_linked_docs_have_related_footer(server):
    status, page = get(server, "/")
    assert status == 200
    names = set(re.findall(r"#docs\?doc=([^\"&]+)", page))
    root = Path(__file__).resolve().parents[1]
    missing = []
    for name in names:
        path = root / name
        if not path.is_file() or "## Related" not in path.read_text(encoding="utf-8"):
            missing.append(name)
    assert not missing, missing
    data = post(server, "/api/prescribe", {"date": "2024-01-08", "session_type": "squat"})
    assert data["session_type"] == "squat"
    assert data["items"]
    assert all("e1rm_source_sets" in item for item in data["items"])

    status, body = get(server, "/api/state")
    assert status == 200
    state = json.loads(body)
    assert state["injury_signal"]["status"] in {
        "unknown", "insufficient", "active", "monitoring", "review"
    }
    assert state["constraints"][0]["forbidden_exercises"] == ["back_extension"]
    assert isinstance(state["e1rm_calibration"], list)
    # P1 coverage is part of the same payload so the page cannot show one without the other.
    assert isinstance(state["e1rm_tests_needed"], list)
    assert {"ssb_squat", "bench_press", "trap_bar_deadlift"} <= {
        row["exercise_id"] for row in state["e1rm_tests_needed"]
    }
    assert all(row["min_tests"] == 3 and row["needed"] >= 0
               for row in state["e1rm_tests_needed"])


def test_form_trend_endpoint_is_read_only(server):
    status, body = get(server, "/api/form-trend?weeks=4&date=2024-02-01")
    assert status == 200
    data = json.loads(body)
    assert data["window"]["weeks"] == 4
    assert "forms" in data


def test_regime_endpoint_is_read_only(server):
    status, body = get(server, "/api/regime?weeks=8&date=2024-02-01")
    assert status == 200
    data = json.loads(body)
    assert data["window"]["weeks"] == 8
    assert "findings" in data and "coverage" in data


def test_settings_endpoint_masks_the_key(server):
    status, body = get(server, "/api/settings")
    assert status == 200
    data = json.loads(body)
    assert "llm" in data and "llm_config_path" in data
    assert data["local_only"] is True
    assert "secret" not in body.lower()


def test_settings_save_and_disable_round_trip(server, tmp_path, monkeypatch):
    path = tmp_path / "llm.local.toml"
    monkeypatch.setenv("STRENGTH_COACH_LLM_CONFIG", str(path))
    monkeypatch.delenv("STRENGTH_COACH_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("STRENGTH_COACH_LLM_API_KEY", raising=False)
    data = post(server, "/api/settings/llm", {
        "enabled": True, "model": "test-model", "base_url": "http://127.0.0.1:1/v1",
        "api_key": "secret-key", "temperature": 0.2, "max_tokens": 700, "timeout_s": 10,
    })
    assert data["enabled"] is True
    assert data["api_key"] == "secr…-key"
    assert "secret-key" not in json.dumps(data)
    disabled = post(server, "/api/settings/llm", {
        "enabled": False, "model": "test-model", "base_url": "http://127.0.0.1:1/v1",
        "temperature": 0.2, "max_tokens": 700, "timeout_s": 10,
    })
    assert disabled["enabled"] is False
    assert disabled["provider"] == "null"


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
    assert "docs/UI-MAP.md" in names

    status, body = get(server, "/api/docs/USER-GUIDE.md")
    assert status == 200
    assert "<h1 id=" in json.loads(body)["html"]


def test_markdown_tables_and_links():
    rendered = markdown.render("# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert '<h1 id="title">Title</h1>' in rendered
    assert "<table>" in rendered

    root = Path(__file__).resolve().parents[1]
    linked = markdown.render("[x](CONTINUITY.md)", docs_root=root, base_dir=root / "docs")
    assert 'href="#docs?doc=docs/CONTINUITY.md"' in linked
    anchored = markdown.render("[x](CONTINUITY.md#gap-detection)", docs_root=root,
                               base_dir=root / "docs")
    assert 'href="#docs?doc=docs/CONTINUITY.md&amp;anchor=gap-detection"' in anchored
    duplicate = markdown.render("## Same\n\n## Same", docs_root=root, base_dir=root / "docs")
    assert duplicate.count('id="same"') == 1
    assert 'id="same-2"' in duplicate

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
        post(server, "/api/prescribe", {"date": today, "session_type": "squat"})
    assert excinfo.value.code == 409


def test_prescribe_can_proceed_with_acknowledged_unknown_readiness(server):
    today = date.today().isoformat()
    data = post(server, "/api/prescribe", {
        "date": today, "session_type": "squat", "allow_unknown_readiness": True,
    })
    assert data["items"]
    assert any("readiness" in warning.lower() for warning in data["warnings"])


def test_start_accepts_acknowledged_partial_readiness(server):
    today = date.today().isoformat()
    plan = post(server, "/api/prescribe", {
        "date": today, "session_type": "squat", "allow_unknown_readiness": True,
    })
    data = post(server, "/api/workout/start", {
        "date": today, "plan": plan, "readiness": {"sleep": 2},
        "readiness_ack": True,
    })
    assert data["workout"]["status"] == "in_progress"
    assert data["workout"]["readiness"] == {"sleep": 2.0}


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
        "weeks": 2, "start": "2024-01-02", "start_session_type": "squat",
    })
    assert len(data["entries"]) == 6
    assert data["entries"][0]["date"] == "2024-01-03"
    assert data["entries"][0]["session_type"] == "squat"
    assert data["entries"][0]["prescription"]["items"]


def test_programme_endpoint_accepts_selection_flags(server):
    data = post(server, "/api/programme", {
        "weeks": 1, "start": "2024-01-02", "start_session_type": "squat",
        "apply_selection": True, "selection_llm": True,
    })
    assert data["entries"]
    selection = data["entries"][0]["prescription"]["notes"]["selection"]
    assert selection["requested"] is True
    assert selection["llm_requested"] is True


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
        "command": "strength-coach programme --weeks 1 --start 2024-01-02 --start-session-type squat",
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
    status, body = get(server, "/api/selection?date=2024-01-01&session_type=hinge")
    assert status == 200
    data = json.loads(body)
    assert data["session_type"] == "hinge"
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
    unconfirmed = post(server, "/api/prescribe", {
        "date": "2024-01-15", "session_type": "squat", "apply_selection": True,
    })
    assert unconfirmed["notes"]["selection"]["requested"] is True
    assert unconfirmed["notes"]["selection"]["applied"] is False
    assert any(slot["blocked_reason"] for slot in unconfirmed["notes"]["selection"]["slots"])

    data = post(server, "/api/prescribe", {
        "date": "2024-01-15", "session_type": "squat",
        "apply_selection": True, "selection_confirmed": True,
    })
    assert data["notes"]["selection"]["requested"] is True
    assert "slots" in data["notes"]["selection"]


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
    assert data["session_type"] == "hinge"
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
    assert "heavy_spinal" in data
    assert data["heavy_spinal"]["rir_max"] == 1


def test_volume_budget_endpoint_is_read_only(server):
    status, body = get(server, "/api/volume/budget?date=2024-01-01")
    assert status == 200
    data = json.loads(body)
    assert data["on_date"] == "2024-01-01"
    assert data["session_cap"]["total"] == 30
    assert "targets" in data and "plan" in data
    assert "per_pattern" in data
    assert "compensation" in data
    assert data["note"].startswith("Read-only")


def test_programme_accepts_a_start_session_type(server):
    data = post(server, "/api/programme", {
        "weeks": 1, "sessions_per_week": 1, "start_session_type": "bench_hinge",
    })
    assert data["entries"][0]["session_type"] == "bench_hinge"
    assert data["entries"][0]["session_type"] == "bench_hinge"


def test_prescribe_suggests_a_scheduled_deload_and_applies_only_when_confirmed(server):
    post(server, "/api/state/profile", {
        "primary_goal": "strength", "effective_from": "2024-01-01",
        "block_start_date": "2024-01-01",
    })
    suggested = post(server, "/api/prescribe", {
        "date": "2024-02-05", "session_type": "squat",
    })
    assert suggested["notes"]["deload_suggestion"]["trigger"] == "scheduled"
    assert "deload" not in suggested["notes"]
    suggested_squat = next(
        item for item in suggested["items"] if item["exercise_id"] == "ssb_squat"
    )
    assert suggested_squat["sets"] == 5

    applied = post(server, "/api/prescribe", {
        "date": "2024-02-05", "session_type": "squat", "deload_confirmed": True,
    })
    assert applied["notes"]["deload"]["trigger"] == "scheduled"
    assert applied["fallback_level"] == "fatigue_reduced"
    squat = next(item for item in applied["items"] if item["exercise_id"] == "ssb_squat")
    assert squat["sets"] == 4


def test_progress_dashboard_endpoint(server):
    status, body = get(server, "/api/progress?date=2024-01-15")
    assert status == 200
    data = json.loads(body)
    assert "coverage" in data
    assert "performance" in data
    assert "volume" in data
    assert "no prescription change" in data["note"]

def test_retrospective_validation_endpoint(server):
    status, body = get(server, "/api/validation?max_dates=2")
    assert status == 200
    assert "RETROSPECTIVE WALK-FORWARD" in json.loads(body)["text"]


def test_workout_start_active_and_end(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    data = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan, "readiness": readiness,
    })
    workout_id = data["workout"]["workout_id"]
    assert data["workout"]["status"] == "in_progress"
    assert data["workout"]["prescription_id"]

    active = json.loads(get(server, "/api/workout/active")[1])
    assert active["workout"]["workout_id"] == workout_id

    added = post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
    })
    assert len(added["workout"]["sets"]) == 1

    ended = post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 50,
    })
    assert ended["workout"]["status"] == "completed"
    assert ended["workout"]["duration_min"] == 50
    assert ended["workout"]["comparison"]["items"][0]["status"] == "under"
    assert ended["workout"]["comparison"]["items"][0]["actual_sets"] == 1
    assert json.loads(get(server, "/api/workout/active")[1])["workout"] is None


def test_review_marks_close_the_workout(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    data = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan, "readiness": readiness,
    })
    workout_id = data["workout"]["workout_id"]
    post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
    })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 50,
    })
    saved = post(server, f"/api/review/{workout_id}", {
        "scores": {"RIR_ADHERENCE": 0.5}, "confidence": "high",
    })
    assert saved["written"] == 1
    assert saved["reviewed_workout"] is True
    assert saved["postprocess"]["workout_closed"] is True
    sheet = json.loads(get(server, f"/api/review/{workout_id}")[1])
    assert sheet["workout"]["comparison"]["items"][0]["actual_sets"] == 1


def test_workout_plan_overrides_api(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    data = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan, "readiness": readiness,
    })
    workout_id = data["workout"]["workout_id"]
    swapped = post(server, f"/api/workout/{workout_id}/plan/swap", {
        "item_index": 0, "exercise_id": "conventional_deadlift",
    })
    assert swapped["workout"]["plan"]["items"][0]["exercise_id"] == "conventional_deadlift"
    assert swapped["workout"]["original_plan"]["items"][0]["exercise_id"] == "trap_bar_deadlift"

    added = post(server, f"/api/workout/{workout_id}/plan/add-exercise", {
        "exercise_id": "lat_pulldown", "sets": 2, "reps_low": 10, "reps_high": 12,
    })
    assert any(item["exercise_id"] == "lat_pulldown" for item in added["workout"]["plan"]["items"])

    changed = post(server, f"/api/workout/{workout_id}/plan/set-count", {
        "item_index": 0, "delta": 1,
    })
    assert changed["workout"]["plan"]["items"][0]["sets"] == 6

    index = next(
        i for i, item in enumerate(changed["workout"]["plan"]["items"])
        if item["exercise_id"] == "lat_pulldown"
    )
    removed = post(server, f"/api/workout/{workout_id}/plan/remove-exercise", {
        "item_index": index,
    })
    assert all(item["exercise_id"] != "lat_pulldown" for item in removed["workout"]["plan"]["items"])


def test_workout_csv_import_preview_and_apply(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    data = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan, "readiness": readiness,
    })
    workout_id = data["workout"]["workout_id"]
    text = "Exercise,Set,RPE,Value,Weight,Reps\nPush Press,1,4,???,20.0kg,4\nPush Press,2,5.5,0.67m/s,40.0kg,5\n"
    preview = post(server, f"/api/workout/{workout_id}/import", {"text": text, "apply": False})
    assert preview["preview"]["errors"] == []
    assert preview["preview"]["rows"][0]["rir"] == 6
    applied = post(server, f"/api/workout/{workout_id}/import", {"text": text, "apply": True})
    assert len(applied["workout"]["sets"]) == 2
    again = post(server, f"/api/workout/{workout_id}/import", {"text": text, "apply": True})
    assert len(again["workout"]["sets"]) == 2

    rep_text = (
        "Exercise Name,Set Number,Metric Name,Rep Number,Velocity\n"
        "Push Press,1,Mean Concentric Velocity,,0.780\n"
        "Push Press,1,Mean Concentric Velocity,1,0.740\n"
        "Push Press,1,Mean Concentric Velocity,2,0.740\n"
        "Push Press,1,Mean Concentric Velocity,3,0.750\n"
        "Push Press,1,Mean Concentric Velocity,4,0.880\n"
    )
    with_rep = post(server, f"/api/workout/{workout_id}/import", {
        "text": text, "rep_text": rep_text, "apply": False,
    })
    assert with_rep["preview"]["rep"]["sets"][0]["reps"][0]["rep_index"] == 1
    applied = post(server, f"/api/workout/{workout_id}/import", {
        "text": text, "rep_text": rep_text, "apply": True,
    })
    row = next(item for item in applied["workout"]["sets"]
               if item["exercise_id"] == "push_press" and item["set_index"] == 1)
    assert row["rep_summary"]["count"] == 4

    post(server, f"/api/workout/{workout_id}/end", {"session_rpe": 7})
    status, body = get(server, f"/api/rep-velocity?session={workout_id}")
    assert status == 200
    report = json.loads(body)
    assert report["available"] is True
    assert report["sets"][0]["summary"]["count"] == 4

    status, body = get(server, "/api/rep-velocity/analysis?date=2024-01-10&weeks=4")
    assert status == 200
    analysis = json.loads(body)
    assert analysis["available"] is True
    assert analysis["set_count"] == 1
    assert all(row["status"] == "insufficient" for row in analysis["correlations"])


def test_test_recording_auto_registers_an_exposure_and_blocks_a_second(server):
    data = post(server, "/api/state/test", {
        "exercise_id": "bench_press", "kg": 100, "reps": 3, "date": "2024-01-08",
    })
    assert data["profile"] is not None or data["injury_signal"]

    status, body = get(server, "/api/exposures?date=2024-01-08")
    assert status == 200
    report = json.loads(body)
    assert report["status"] == "blocked"
    assert any(row["kind"] == "test" for row in report["exposures"])

    code, _ = post_status(server, "/api/state/test", {
        "exercise_id": "bench_press", "kg": 95, "reps": 5, "date": "2024-01-08",
    })
    assert code == 400


def test_outcomes_endpoint_is_read_only(server):
    status, body = get(server, "/api/outcomes?weeks=4&date=2024-01-31")
    assert status == 200
    data = json.loads(body)
    assert data["window"]["weeks"] == 4
    assert "strength" in data and "longevity" in data
    assert data["note"].startswith("Descriptive")


def test_quick_readiness_preset_and_context_endpoints(server):
    data = post(server, "/api/readiness/preset", {
        "date": "2024-01-08", "name": "good_to_train",
    })
    assert data["score"]["status"] == "ready"
    assert data["context_flags"] == []

    data = post(server, "/api/readiness/context", {
        "date": "2024-01-08", "flags": ["travel", "alcohol"],
    })
    assert set(data["context_flags"]) == {"travel", "alcohol"}
    assert data["score"]["status"] == "ready"


def test_readiness_feedback_endpoint_is_descriptive(server):
    status, body = get(server, "/api/readiness/feedback?weeks=4&date=2024-01-31")
    assert status == 200
    data = json.loads(body)
    assert data["events"] == []
    assert data["aggregate"]["n_events"] == 0
    assert data["note"].startswith("Association only")


def test_minimum_session_prescription_is_explicit_and_volume_only(server):
    data = post(server, "/api/prescribe", {
        "date": "2024-01-01", "session_type": "hinge",
        "minimum_session": True, "target_minutes": 30,
    })
    note = data["notes"]["minimum_session"]
    assert note["requested"] is True
    assert note["target_minutes"] == 30
    assert "MOD-MIN-001" in " ".join(data["warnings"])


def test_prospective_endpoint_is_read_only(server):
    status, body = get(server, "/api/prospective?weeks=4&date=2024-02-01")
    assert status == 200
    data = json.loads(body)
    assert data["window"]["weeks"] == 4
    assert "strength" in data and "flags" in data
    assert data["note"].startswith("Descriptive only")


def test_history_endpoint_lists_and_edits_a_session(server):
    status, body = get(server, "/api/history?limit=10&offset=0")
    assert status == 200
    page = json.loads(body)
    assert page["total"] >= 1
    session_id = page["sessions"][0]["session_id"]

    status, body = get(server, f"/api/history/{session_id}")
    assert status == 200
    detail = json.loads(body)
    first = detail["sets"][0]

    result = post(server, f"/api/history/{session_id}/edit", {
        "sets": [{**first, "load_kg": float(first["load_kg"] or 0) + 2.5}, *detail["sets"][1:]],
        "forms": [{"exercise_id": first["exercise_id"], "rating": 4}],
        "duration_min": 45,
        "notes": "history correction",
        "reason": "typo",
    })
    assert result["edit_id"]
    assert result["session"]["needs_review"] == 1
    assert result["session"]["edited_at"]
    assert result["session"]["forms"][0]["rating"] == 4


def test_history_void_and_vbt_endpoints(server):
    _, body = get(server, "/api/history?limit=5")
    session_id = json.loads(body)["sessions"][0]["session_id"]
    _, body = get(server, f"/api/history/{session_id}")
    detail = json.loads(body)
    set_id = detail["sets"][0]["set_id"]

    result = post(server, f"/api/history/{session_id}/vbt", {
        "sets": [{"set_id": set_id, "mean": 0.81,
                  "reps": [{"rep_index": 1, "velocity_mps": 0.84}]}],
    })
    assert result["session"]["vbt_override_count"] >= 1

    edited = post(server, f"/api/history/{session_id}/edit", {
        "sets": [{"set_id": set_id, "exercise_id": detail["sets"][0]["exercise_id"],
                  "load_kg": detail["sets"][0]["load_kg"],
                  "reps": detail["sets"][0]["reps"],
                  "rir": detail["sets"][0]["rir"],
                  "vbt_mean": 0.82,
                  "vbt_reps": [{"rep_index": 1, "velocity_mps": 0.85}]}],
    })
    assert edited["session"]["sets"][0]["vbt_mean"] == 0.82

    voided = post(server, f"/api/history/{session_id}/void", {"reason": "test"})
    assert voided["voided"] == 1
    status, body = get(server, f"/api/history/{session_id}")
    assert json.loads(body)["voided"] == 1
    restored = post(server, f"/api/history/{session_id}/void", {"unvoid": True})
    assert restored["voided"] == 0

def test_the_exercise_tab_offers_an_e1rm_override(server):
    status, page = get(server, "/")
    assert status == 200
    assert 'id="exercise-e1rm-panel"' in page
    assert 'id="exercise-e1rm-form"' in page
    assert 'id="exercise-e1rm-id"' in page
    # The catalogue row action lives in the client bundle.
    status, js = get(server, "/static/app.js")
    assert status == 200
    assert "data-e1rm-exercise" in js
    assert "/api/state/e1rm" in js


def test_the_athlete_page_shows_the_tests_needed_table(server):
    # The table is rendered from the same /api/state payload the CLI builds; the browser
    # adds no gate logic of its own.
    status, js = get(server, "/static/app.js")
    assert status == 200
    assert "e1rm_tests_needed" in js
    assert "Measured tests needed" in js
    assert "#docs?doc=ROADMAP.md" in js


def test_the_symptom_form_names_the_settle_window_and_links_the_workflow(server):
    # The field label is the only place the 48-hour window is stated in the UI, and the
    # workflow it belongs to is reachable from the same panel.
    status, js = get(server, "/static/app.js")
    assert status == 200
    assert "Settled within 48 hours" in js
    assert 'data-symptom="settled"' in js
    assert "#docs?doc=docs/SYMPTOM-LOGGING.md" in js


def test_a_declared_break_can_be_recorded_and_cancelled(server):
    data = post(server, "/api/state/break", {
        "starts_on": "2024-01-08", "ends_on": "2024-01-10", "reason": "test",
    })
    break_id = data["break_id"]
    assert any(row["reason"] == "test" for row in data["breaks"])

    status, body = get(server, "/api/breaks")
    assert status == 200
    assert any(row["reason"] == "test" for row in json.loads(body)["breaks"])

    # The state payload carries the list so the Athlete panel renders from the same source.
    status, body = get(server, "/api/state")
    assert any(row["break_id"] == break_id for row in json.loads(body)["declared_breaks"])

    cancelled = post(server, "/api/state/break/cancel", {"break_id": break_id})
    assert next(row for row in cancelled["breaks"]
                if row["break_id"] == break_id)["cancelled"] is True


def test_the_history_edit_sheet_can_backfill_per_rep_velocity(server):
    status, page = get(server, "/")
    assert status == 200
    assert 'id="history-vbt"' in page
    assert 'id="history-vbt-save"' in page
    status, js = get(server, "/static/history.js")
    assert status == 200
    assert "renderHistoryVbt" in js and "saveHistoryVbt" in js
    assert "(backfilled)" in js  # backfilled sRPE/duration surface in the details sheet


def test_the_athlete_page_exposes_declared_breaks(server):
    status, js = get(server, "/static/app.js")
    assert status == 200
    assert "Declared break" in js
    assert "/api/state/break" in js
    assert "#docs?doc=docs/CONTINUITY.md" in js


def test_the_post_workout_screen_offers_an_e1rm(server):
    status, js = get(server, "/static/workout.js")
    assert status == 200
    assert 'id="post-test-form"' in js
    assert 'id="post-e1rm-form"' in js
    assert "/api/state/test" in js
    assert "/api/state/e1rm" in js
    # LIM-47: the ended screen shows target, estimate and measured duration together.
    assert "minimum_session" in js and "Minimum session (MOD-MIN-001)" in js


def test_an_e1rm_override_can_start_today_and_be_replaced(server):
    # The exercise tab and the post-workout panel both append, never edit: the latest
    # applicable row wins, which is the same contract the Athlete page and CLI use.
    first = post(server, "/api/state/e1rm", {
        "exercise_id": "trap_bar_deadlift", "e1rm_kg": 180, "reason": "first",
    })
    second = post(server, "/api/state/e1rm", {
        "exercise_id": "trap_bar_deadlift", "e1rm_kg": 185, "reason": "second",
    })
    rows = [row for row in second["e1rm_overrides"]
            if row["exercise_id"] == "trap_bar_deadlift"]
    assert len(rows) == len([row for row in first["e1rm_overrides"]
                             if row["exercise_id"] == "trap_bar_deadlift"]) + 1
    assert max(row["e1rm_kg"] for row in rows) == 185

def test_the_technique_throttle_is_available_from_the_api(server):
    baseline = post(server, "/api/prescribe", {"date": "2024-01-08", "session_type": "squat"})
    throttled = post(server, "/api/prescribe", {
        "date": "2024-01-08", "session_type": "squat", "technique_throttle": True,
    })
    assert any("MOD-TECH-001" in warning for warning in throttled["warnings"])
    base = {item["exercise_id"]: item["load_kg"] for item in baseline["items"]}
    dropped = [
        item for item in throttled["items"]
        if item["load_kg"] is not None and base.get(item["exercise_id"]) is not None
        and item["load_kg"] < base[item["exercise_id"]]
    ]
    assert dropped
    # The throttle can only lower a load, so it must not change executability either way:
    # if the baseline is already unexecutable for another reason, the throttle is not a fix.
    assert throttled["executable"] == baseline["executable"]


def test_the_technique_throttle_can_be_scoped_to_one_pattern(server):
    baseline = post(server, "/api/prescribe", {"date": "2024-01-08", "session_type": "squat"})
    scoped = post(server, "/api/prescribe", {
        "date": "2024-01-08", "session_type": "squat",
        "technique_throttle": True, "technique_throttle_pattern": "squat",
    })
    assert any("MOD-TECH-001" in warning for warning in scoped["warnings"])
    base = {item["exercise_id"]: item["load_kg"] for item in baseline["items"]}
    scoped_loads = {item["exercise_id"]: item["load_kg"] for item in scoped["items"]}
    assert scoped_loads["ssb_squat"] < base["ssb_squat"]
    assert scoped_loads["bench_press"] == base["bench_press"]


def test_a_technique_throttle_pattern_with_no_match_says_so(server):
    data = post(server, "/api/prescribe", {
        "date": "2024-01-08", "session_type": "squat",
        "technique_throttle": True, "technique_throttle_pattern": "not_a_pattern",
    })
    assert any("MOD-TECH-001 not applied" in warning for warning in data["warnings"])


def test_the_page_exposes_the_technique_throttle_controls(server):
    status, page = get(server, "/")
    assert status == 200
    assert 'id="prescribe-technique"' in page
    assert 'id="prescribe-throttle-pattern"' in page