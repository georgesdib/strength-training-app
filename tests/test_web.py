"""The local web UI: the API mirrors the core and the CLI remains untouched."""

from __future__ import annotations

import json
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlparse

import pytest
from conftest import make_readiness, make_training

from strength_coach.features import demands as demands_feature
from strength_coach.store import db, importer, repositories
from strength_coach.web import markdown
from strength_coach.web import server as web_server
from strength_coach.web.server import analysis_readonly_connection, create_server

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


def client_js(base: str) -> str:
    """The whole client bundle, so a feature move does not break a string contract."""
    names = ("core.js", "app.js", "exercises.js", "history.js", "workout.js", "summary.js", "performance.js")
    parts = []
    for name in names:
        status, body = get(base, "/static/" + name)
        assert status == 200, name
        parts.append(body)
    return "\n".join(parts)


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
    assert "Programme" in page
    assert "Terminal" not in page  # removed: a mutation surface with no auth
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
    assert "core.js" in page and "exercises.js" in page
    assert "view-longevity" in page and "longevity-form" in page
    assert "workout.js" in page
    assert "summary.js" in page
    assert "performance.js" in page
    assert 'data-view="performance"' in page
    assert 'id="view-performance"' in page
    assert "workout-end-productivity" in page
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
    script = client_js(server)
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

def test_readiness_preset_yaml_is_served_and_invalid_edits_rejected(server):
    status, body = get(server, "/api/readiness/presets")
    assert status == 200
    data = json.loads(body)
    assert "presets:" in data["yaml"]
    assert data["presets"]["good_to_train"]["values"]["sleep"] == 4
    assert data["path"].endswith("config/readiness-presets.v1.yaml")

    code, body = post_status(server, "/api/readiness/presets", {
        "yaml": "presets:\n  bad:\n    values: {sleep: 9, energy: 4, soreness: 5, stress: 4}\n",
    })
    assert code == 400
    assert "1-5" in body


def test_readiness_calibration_endpoint(server):
    status, body = get(server, "/api/readiness/calibrate")
    assert status == 200
    assert "readiness calibration" in json.loads(body)["text"]

def test_the_exposure_trim_flag_survives_an_unrelated_profile_save(server):
    state = post(server, "/api/state/profile", {
        "sessions_per_week_target": 3,
        "exposure_trim_enabled": True,
    })
    assert state["profile"]["exposure_trim_enabled"] == 1
    state = post(server, "/api/state/profile", {
        "sessions_per_week_target": 3,
    })
    assert state["profile"]["exposure_trim_enabled"] == 1


def test_canonical_options_are_served(server):
    status, body = get(server, "/api/options")
    assert status == 200
    options = json.loads(body)
    assert "goals" not in options
    assert {row["value"] for row in options["constraint_kinds"]} == {
        "injury", "contraindication", "mobility", "asymmetry",
    }
    assert "low_back" in {row["value"] for row in options["regions"]}
    assert "squat" in {row["value"] for row in options["patterns"]}


def test_athlete_state_rejects_noncanonical_values(server):
    cases = [
        ("/api/state/profile", {"main_lift_policy": "ignore"}),
        ("/api/state/constraint", {
            "kind": "rom", "region": "low_back", "severity": "monitor",
        }),
        ("/api/state/constraint", {
            "kind": "injury", "region": "elbow", "severity": "monitor",
        }),
        ("/api/state/constraint", {
            "kind": "injury", "region": "low_back", "severity": "monitor",
            "forbidden_patterns": ["sqaut"],
        }),
        ("/api/state/constraint", {
            "kind": "injury", "region": "low_back", "severity": "monitor",
            "forbidden_exercises": ["not_a_lift"],
        }),
        ("/api/state/suitability", {
            "exercise_id": "not_a_lift", "can_do": True, "will_do": True,
            "feels_bad": False,
        }),
    ]
    for path, payload in cases:
        code, body = post_status(server, path, payload)
        assert code == 400, (path, payload, body)


def test_validation_errors_name_the_field(server):
    cases = [
        ("/api/state/profile", {"main_lift_policy": "ignore"}, "main_lift_policy"),
        ("/api/state/constraint", {"kind": "rom", "region": "low_back"}, "kind"),
        ("/api/state/suitability", {"exercise_id": "not_a_lift"}, "exercise_id"),
        ("/api/state/e1rm", {"exercise_id": "ssb_squat", "e1rm_kg": "bad"}, "e1rm_kg"),
        ("/api/state/test", {"exercise_id": "ssb_squat", "kg": 100, "reps": 99}, "reps"),
        ("/api/readiness", {"date": "2024-01-08", "values": {"sleep": 9}}, "sleep"),
        ("/api/exercises", {
            "id": "bad_pattern_lift",
            "props": {
                "display": "Bad Pattern", "log_names": ["Bad Pattern"], "pattern": "sqaut",
            },
        }, "pattern"),
        ("/api/cardio", {"modality": "walk", "minutes": 0}, "minutes"),
        ("/api/measurements", {"metric": "not_a_metric", "value": 1}, "metric"),
        ("/api/state/symptom", {"region": "low_back", "level": 9}, "level"),
        ("/api/state/break", {
            "starts_on": "bad", "ends_on": "bad", "reason": "holiday",
        }, "starts_on"),
        ("/api/settings/drop", {"tolerance": 2}, "tolerance"),
        ("/api/settings/llm", {
            "enabled": True, "model": "x", "base_url": "bad",
            "temperature": 0.2, "max_tokens": 1, "timeout_s": 1,
        }, "base_url"),
    ]
    for path, payload, field in cases:
        code, body = post_status(server, path, payload)
        assert code == 400, (path, body)
        assert field in json.loads(body).get("fields", {}), (path, body)


def test_block_start_names_the_date_field(server):
    post(server, "/api/state/profile", {"sessions_per_week_target": 3})
    code, body = post_status(server, "/api/state/block", {"date": "not-a-date"})
    assert code == 400
    assert "date" in json.loads(body).get("fields", {})


def test_state_can_be_edited(server):
    state = post(server, "/api/state/profile", {
        "sessions_per_week_target": 3,
        "max_session_minutes": 90,
        "block_start_date": "2024-01-01",
    })
    assert state["profile"]["sessions_per_week_target"] == 3
    assert state["profile"]["block_start_date"] == "2024-01-01"

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


def test_the_shadow_review_endpoint_never_allows_activation(server):
    status, body = get(server, "/api/shadow?date=2024-01-31")
    data = json.loads(body)
    assert status == 200
    assert data["activation_allowed"] is False
    assert data["checks"]
    assert isinstance(data["rows"], int)


def test_the_residual_endpoint_abstains_without_linked_sets(server):
    status, body = get(server, "/api/residual?date=2024-01-31")
    data = json.loads(body)
    assert status == 200
    assert data["signal_available"] is False
    assert data["evaluation_ready"] is False
    assert data["abstain"]
    assert data["gates"]["min_observations"] == 5


def test_the_exposure_ratio_endpoint_is_served(server):
    status, body = get(server, "/api/exposure?date=2024-01-31")
    data = json.loads(body)
    assert status == 200
    assert data["signal"] in {"high", "normal", "low", "unknown"}
    assert data["windows"]["acute"]["start"] == "2024-01-25"
    assert isinstance(data["abstain"], list)
    assert data["flags"]["effort_max_rir"] == 4


def test_programme_endpoint(server):
    data = post(server, "/api/programme", {
        "weeks": 2, "start": "2024-01-02", "start_session_type": "squat",
    })
    assert len(data["entries"]) == 6
    assert data["entries"][0]["date"] == "2024-01-03"
    assert data["entries"][0]["session_type"] == "squat"
    assert data["entries"][0]["prescription"]["items"]




def test_programme_supports_four_and_five_days(server):
    four = post(server, "/api/programme", {
        "weeks": 1, "start": "2024-01-02", "sessions_per_week": 4,
        "start_session_type": "squat",
    })
    five = post(server, "/api/programme", {
        "weeks": 1, "start": "2024-01-02", "sessions_per_week": 5,
        "start_session_type": "squat",
    })
    assert len(four["entries"]) == 4
    assert len(five["entries"]) == 5


def test_programme_job_endpoint_returns_a_pollable_result(server):
    payload = {
        "weeks": 2, "start": "2024-01-02", "start_session_type": "squat",
    }
    key = post(server, "/api/programme/key", payload)["cache_key"]
    assert len(key) == 64
    job = post(server, "/api/programme/jobs", payload)
    assert job["status"] in {"running", "done"}
    for _ in range(300):
        status, body = get(server, "/api/programme/jobs/" + job["job_id"])
        assert status == 200
        current = json.loads(body)
        if current["status"] == "done":
            assert len(current["result"]["entries"]) == 6
            return
        assert current["status"] == "running"
        time.sleep(0.2)
    raise AssertionError("programme job did not finish")


def test_programme_endpoint_accepts_selection_flags(server):
    data = post(server, "/api/programme", {
        "weeks": 1, "start": "2024-01-02", "start_session_type": "squat",
        "apply_selection": True, "selection_llm": True,
    })
    assert data["entries"]
    selection = data["entries"][0]["prescription"]["notes"]["selection"]
    assert selection["requested"] is True
    assert selection["llm_requested"] is True
    assert selection["llm_unavailable"] is True
    assert any("NullLLM" in warning for warning in data["entries"][0]["prescription"]["warnings"])


def test_programme_cache_key_separates_llm_and_python_options(server):
    base = {
        "weeks": 1, "start": "2024-01-02", "start_session_type": "squat",
        "apply_selection": True, "selection_confirmed": True,
    }
    python_key = post(server, "/api/programme/key", {**base, "selection_llm": False})["cache_key"]
    llm_key = post(server, "/api/programme/key", {**base, "selection_llm": True})["cache_key"]
    assert python_key != llm_key


def test_programme_cache_key_changes_after_a_database_write(server):
    payload = {"weeks": 1, "start": "2024-01-02", "sessions_per_week": 1}
    before = post(server, "/api/programme/key", payload)["cache_key"]
    post(server, "/api/readiness", {
        "date": "2024-01-01", "values": {"sleep": 3}, "note": "cache revision",
    })
    after = post(server, "/api/programme/key", payload)["cache_key"]
    assert before != after


def test_logs_endpoint_returns_the_recent_tail(server):
    status, body = get(server, "/api/logs?limit=10")
    assert status == 200
    data = json.loads(body)
    assert isinstance(data["logs"], list)


def post_with_headers(base: str, path: str, payload: dict, headers: dict) -> tuple[int, str]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if not isinstance(payload, bytes) else payload,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_the_terminal_route_is_gone(server):
    status, body = post_status(server, "/api/terminal", {"command": "ls"})
    assert status == 404
    assert "not found" in body


def test_http_requests_are_not_origin_restricted(server):
    # The owner explicitly removed the loopback/origin boundary for home-network HTTP use.
    status, _body = post_with_headers(
        server, "/api/reads", {"x": 1},
        {"Content-Type": "application/json", "Host": "coach.home:8000",
         "Origin": "http://coach.home:8000", "Sec-Fetch-Site": "cross-site"},
    )
    assert status != 403


def test_a_non_json_content_type_is_refused(server):
    # text/plain is a browser "simple request": it skips the preflight, so it must not be a
    # way around the origin check.
    status, body = post_with_headers(
        server, "/api/reads", b'{"x": 1}',
        {"Content-Type": "text/plain"},
    )
    assert status == 415
    assert "application/json" in body


def test_the_programme_horizon_is_bounded(server):
    status, body = post_status(server, "/api/programme", {"weeks": 27})
    assert status == 400
    assert "between 1 and 26" in body


def test_only_one_programme_job_runs(monkeypatch, server):
    import threading

    from strength_coach.web import server as web_server

    started = threading.Event()
    release = threading.Event()

    def slow_payload(conn, body):
        started.set()
        release.wait(timeout=10)
        return {}

    monkeypatch.setattr(web_server, "programme_payload", slow_payload)
    first = post(server, "/api/programme/jobs", {"weeks": 1, "sessions_per_week": 1})
    assert first["status"] == "running"
    assert started.wait(timeout=10)
    status, body = post_status(server, "/api/programme/jobs", {"weeks": 1})
    assert status == 409
    assert "already running" in body
    release.set()


def test_a_same_origin_post_is_accepted(server):
    status, body = post_with_headers(
        server, "/api/reviews",
        {"task_key": "exercise_substitution", "action": "snoozed", "date": "2024-01-01"},
        {"Content-Type": "application/json", "Origin": server},
    )
    assert status == 200, body

def test_the_fatigue_review_can_be_acknowledged_over_the_api(server):
    status, body = post_status(server, "/api/reviews", {
        "task_key": "fatigue_signals", "action": "completed",
        "date": "2024-01-01", "decision": "kept",
    })
    assert status == 200
    data = json.loads(body)
    task = next(t for t in data["tasks"] if t["key"] == "fatigue_signals")
    assert task["status"] == "not_due"


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


def test_the_substitution_endpoint_abstains_without_data(server):
    status, body = get(server, "/api/substitution?date=2024-01-31&session_type=squat")
    data = json.loads(body)
    assert status == 200
    assert data["applied"] is False
    assert data["suggestions"] == []
    assert data["abstentions"]


def test_the_substitution_endpoint_rejects_an_unknown_session_type(server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(server, "/api/substitution?date=2024-01-31&session_type=nope")
    assert excinfo.value.code == 400


def test_exercise_catalog_endpoint(server):
    status, body = get(server, "/api/exercises/catalog")
    assert status == 200
    data = json.loads(body)
    assert data["entities"]
    assert "patterns" in data
    assert any(row["id"] == "ssb_squat" for row in data["entities"])
    assert data["demand_catalogue"]["in_scope"] == [
        "axial_spinal", "trunk_stability", "technical", "local_muscular"
    ]
    ssb = next(row for row in data["entities"] if row["id"] == "ssb_squat")
    assert ssb["demands"]["rated"] == 4
    assert ssb["demands"]["dimensions"]["axial_spinal"]["level"] == "high"
    assert ssb["demands"]["dimensions"]["axial_spinal"]["confidence"] == "provisional"
    seal = next(row for row in data["entities"] if row["id"] == "seal_row")
    assert seal["demands"]["rated"] == 0
    assert seal["demands"]["dimensions"]["axial_spinal"]["level"] == "unknown"


def test_a_demand_rating_can_be_saved_and_cleared_in_the_ui(server, tmp_path, monkeypatch):
    base = tmp_path / "demands.v1.yaml"
    base.write_text(json.dumps({
        "schema_version": "1.0.0",
        "reviewed_on": "2026-10-28",
        "evidence": {},
        "exercises": {"seal_row": {"axial_spinal": {
            "level": "low", "confidence": "provisional", "reason": "shipped read",
        }}},
    }), encoding="utf-8")
    monkeypatch.setattr(demands_feature.paths, "exercise_demands_yaml", lambda: base)

    data = post(server, "/api/exercises/demands", {
        "exercise_id": "seal_row", "dimension": "axial_spinal",
        "level": "moderate", "confidence": "provisional", "reason": "my own read",
    })
    assert data["demands"]["dimensions"]["axial_spinal"]["level"] == "moderate"
    assert data["overlay"] is True
    assert (tmp_path / "demands.local.yaml").is_file()

    cleared = post(server, "/api/exercises/demands", {
        "exercise_id": "seal_row", "dimension": "axial_spinal", "clear": True,
    })
    assert cleared["demands"]["dimensions"]["axial_spinal"]["level"] == "low"


def test_a_supported_demand_rating_needs_evidence(server, tmp_path, monkeypatch):
    base = tmp_path / "demands.v1.yaml"
    base.write_text(json.dumps({
        "schema_version": "1.0.0",
        "reviewed_on": "2026-10-28",
        "evidence": {},
        "exercises": {},
    }), encoding="utf-8")
    monkeypatch.setattr(demands_feature.paths, "exercise_demands_yaml", lambda: base)
    status, _ = post_status(server, "/api/exercises/demands", {
        "exercise_id": "seal_row", "dimension": "axial_spinal",
        "level": "moderate", "confidence": "supported", "reason": "unsupported",
    })
    assert status == 400
    assert not (tmp_path / "demands.local.yaml").exists()


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


def test_modalities_endpoint_lists_and_sets(server):
    status, body = get(server, "/api/modalities")
    assert status == 200
    data = json.loads(body)
    assert any(row["id"] == "deload" for row in data["modules"])
    saved = post(server, "/api/modalities/deload", {"enabled": False})
    assert saved["id"] == "deload"
    assert saved["enabled"] is False


def test_settings_drop_endpoint_writes_the_profile(server):
    saved = post(server, "/api/settings/drop", {
        "enabled": False, "competition_confirm_days": 9,
        "max_slots_per_group": 1, "technique_minutes": 30,
        "tolerance": 0.2,
        "slots": {"horizontal_push": [{
            "exercise_id": "dumbbell_bench_press", "sets": 3,
            "reps_low": 8, "reps_high": 12, "rir_low": 2, "rir_high": 3,
            "rest_s": 90, "load_source": "double_progression",
        }]},
    })
    assert saved["drop"]["tolerance"] == 0.2
    assert saved["drop"]["source"] == "profile"
    status, body = get(server, "/api/settings/profile")
    assert status == 200
    assert json.loads(body)["budget"]["tolerance"] == 0.2


def test_volume_settings_endpoint_reads_effective_budget_and_policy(server):
    status, body = get(server, "/api/settings/volume?date=2024-01-01")
    assert status == 200
    data = json.loads(body)
    assert data["date"] == "2024-01-01"
    assert data["budget"]["weekly_target"]["squat"] == 10
    assert data["budget"]["session_cap"]["total"] == 30
    assert data["policy"]["volume.ledger.coverage"] == "unknown"
    assert data["athlete"]["main_lift_policy"] == "preserve"
    assert data["source"] in ("config", "local overlay", "profile")


def test_volume_policy_changes_do_not_need_typed_confirmation(server):
    saved = post(server, "/api/settings/volume", {
        "policy": {"volume.ledger.coverage": "complete"},
        "reason": "switch coverage",
    })
    assert saved["policy"]["volume.ledger.coverage"] == "complete"
    assert saved["source"] == "profile"


def test_volume_settings_requires_reason_and_high_impact_confirmation(server):
    status, body = post_status(server, "/api/settings/volume", {
        "budget": {"tolerance": 0.2},
    })
    assert status == 400
    assert "reason" in body

    status, body = post_status(server, "/api/settings/volume", {
        "budget": {"weekly_target": {"squat": 11}, "weekly_total": 64},
        "reason": "increase squat target",
    })
    assert status == 400
    assert "VOLUME" in body

    saved = post(server, "/api/settings/volume", {
        "budget": {"weekly_target": {"squat": 11}, "weekly_total": 64},
        "reason": "increase squat target",
        "confirm_text": "VOLUME",
    })
    assert saved["budget"]["weekly_target"]["squat"] == 11
    assert saved["source"] == "profile"


def test_drop_window_endpoint_is_explicit_when_drop_mode_is_inactive(server):
    status, body = get(server, "/api/settings/drop/window?date=2024-01-01")
    assert status == 200
    data = json.loads(body)
    assert data["date"] == "2024-01-01"
    assert data["applies"] is False
    assert data["drop_mode_active"] is False
    assert data["in_window"] is False
    assert data["reason"] == "drop mode is not active"


def test_settings_profile_endpoint(server):
    status, body = get(server, "/api/settings/profile?date=2024-01-01")
    assert status == 200
    data = json.loads(body)
    assert data["profile_id"] is None

    saved = post(server, "/api/settings/profile", {
        "set": {"undulation.cycle_weeks": 3},
        "effective_from": "2024-01-01",
    })
    assert saved["profile_id"] is not None
    assert saved["resolved"]["undulation.cycle_weeks"] == 3


def test_programme_accepts_a_start_session_type(server):
    data = post(server, "/api/programme", {
        "weeks": 1, "sessions_per_week": 1, "start_session_type": "bench_hinge",
    })
    assert data["entries"][0]["session_type"] == "bench_hinge"
    assert data["entries"][0]["session_type"] == "bench_hinge"


def test_prescribe_suggests_a_scheduled_deload_and_applies_only_when_confirmed(server):
    post(server, "/api/state/profile", {
        "effective_from": "2024-01-01",
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


def test_manual_workout_sets_require_reps_and_bound_rir(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    workout_id = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan, "readiness": readiness,
    })["workout"]["workout_id"]

    code, body = post_status(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100,
    })
    assert code == 400
    assert "reps" in json.loads(body).get("fields", {})

    code, body = post_status(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 9,
    })
    assert code == 400
    assert "rir" in json.loads(body).get("fields", {})

    added = post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
    })
    assert len(added["workout"]["sets"]) == 1


def test_history_correction_bounds_reps_and_rir(server):
    _, body = get(server, "/api/history?limit=1")
    session_id = json.loads(body)["sessions"][0]["session_id"]
    _, body = get(server, f"/api/history/{session_id}")
    detail = json.loads(body)
    first = detail["sets"][0]
    code, body = post_status(server, f"/api/history/{session_id}/edit", {
        "sets": [{**first, "reps": None, "rir": 9}],
        "reason": "test",
    })
    assert code == 400
    fields = json.loads(body).get("fields", {})
    assert any(k.endswith(".reps") or k.endswith(".rir") for k in fields), fields


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


def test_history_edit_rejects_an_unknown_exercise(server):
    _, body = get(server, "/api/history?limit=1")
    session_id = json.loads(body)["sessions"][0]["session_id"]
    _, body = get(server, f"/api/history/{session_id}")
    detail = json.loads(body)
    first = detail["sets"][0]
    code, body = post_status(server, f"/api/history/{session_id}/edit", {
        "sets": [{**first, "exercise_id": "not_a_lift"}],
        "reason": "test",
    })
    assert code == 400, body
    assert "unknown exercise id" in body


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
    # The catalogue row action lives in the client bundle, not necessarily app.js.
    js = client_js(server)
    assert "data-e1rm-exercise" in js
    assert "/api/state/e1rm" in js


def test_the_athlete_page_shows_the_tests_needed_table(server):
    # The table is rendered from the same /api/state payload the CLI builds; the browser
    # adds no gate logic of its own.
    js = client_js(server)
    assert "e1rm_tests_needed" in js
    assert "Measured tests needed" in js
    assert "#docs?doc=ROADMAP.md" in js


def test_the_symptom_form_names_the_settle_window_and_links_the_workflow(server):
    # The field label is the only place the 48-hour window is stated in the UI, and the
    # workflow it belongs to is reachable from the same panel.
    js = client_js(server)
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
    js = client_js(server)
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


def test_the_technique_throttle_can_be_scoped_to_several_patterns(server):
    baseline = post(server, "/api/prescribe", {"date": "2024-01-08", "session_type": "squat"})
    scoped = post(server, "/api/prescribe", {
        "date": "2024-01-08", "session_type": "squat",
        "technique_throttle": True,
        "technique_throttle_pattern": ["squat", "horizontal_push"],
    })
    assert any("MOD-TECH-001" in warning for warning in scoped["warnings"])
    base = {item["exercise_id"]: item["load_kg"] for item in baseline["items"]}
    scoped_loads = {item["exercise_id"]: item["load_kg"] for item in scoped["items"]}
    assert scoped_loads["ssb_squat"] < base["ssb_squat"]
    assert scoped_loads["bench_press"] < base["bench_press"]


def test_all_lifts_and_a_pattern_are_combined(server):
    scoped = post(server, "/api/prescribe", {
        "date": "2024-01-08", "session_type": "squat",
        "technique_throttle": True,
        "technique_throttle_pattern": ["", "core"],
    })
    assert any("MOD-TECH-001" in warning for warning in scoped["warnings"])
    assert scoped["notes"]["technique_throttle"]["pattern"] == ["", "core"]


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
    assert '<select id="prescribe-throttle-pattern" multiple size="6">' in page
    assert '<option value="" selected>All lifts (main work)</option>' in page
    assert 'list="exercise-patterns"' not in page

def _raw_post(base: str, headers: list[str], body: bytes = b"") -> tuple[int, str]:
    parsed = urlparse(base)
    with socket.create_connection((parsed.hostname, parsed.port), timeout=3) as sock:
        head = (
            "POST /api/import HTTP/1.0\r\n"
            "Host: localhost\r\n"
            + "".join(f"{header}\r\n" for header in headers)
            + "\r\n"
        )
        sock.sendall(head.encode() + body)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    raw = b"".join(chunks).decode("latin1")
    return int(raw.split(" ", 2)[1]), raw


def test_oversized_body_is_rejected_before_read(monkeypatch, server):
    monkeypatch.setattr(web_server, "MAX_BODY_BYTES", 1024)
    status, raw = _raw_post(server, ["Content-Length: 100000"])
    assert status == 413
    assert "request body too large" in raw


def test_missing_content_length_is_411(server):
    status, _ = _raw_post(server, [])
    assert status == 411


def test_invalid_content_length_is_400(server):
    for value in ("abc", "-1", "5.0", "1" * 30):
        status, _ = _raw_post(server, [f"Content-Length: {value}"])
        assert status == 400, value


def test_duplicate_content_length_is_400(server):
    status, _ = _raw_post(server, ["Content-Length: 1", "Content-Length: 1"])
    assert status == 400


def test_chunked_transfer_is_rejected(server):
    status, _ = _raw_post(server, ["Transfer-Encoding: chunked"])
    assert status == 400


def test_malformed_json_and_non_object_are_400(server):
    cases = [
        (b"{", 1),
        (b"[]", 2),
        (b"\xff", 1),
    ]
    for body, length in cases:
        status, _ = _raw_post(
            server,
            [f"Content-Length: {length}", "Content-Type: application/json"],
            body,
        )
        assert status == 400, body


def test_body_at_limit_is_accepted_but_one_byte_over_is_413(monkeypatch, server):
    monkeypatch.setattr(web_server, "MAX_BODY_BYTES", 64)
    exact = json.dumps({"x": "a" * 56}, separators=(",", ":")).encode()
    assert len(exact) == 64
    status, _ = _raw_post(
        server, [f"Content-Length: {len(exact)}", "Content-Type: application/json"], exact
    )
    assert status == 400  # parsed, then rejected by the import handler
    status, _ = _raw_post(server, [f"Content-Length: {len(exact) + 1}"])
    assert status == 413


def test_zero_content_length_is_an_empty_object(server):
    status, _ = _raw_post(server, ["Content-Length: 0", "Content-Type: application/json"])
    assert status == 400  # import handler, not a framing error


def test_the_import_file_limit_is_used(monkeypatch, server):
    monkeypatch.setattr(web_server, "MAX_IMPORT_FILE_BYTES", 10)
    status, body = post_status(server, "/api/import", {
        "training": {"name": "t.csv", "text": "x" * 11},
        "readiness": {"name": "r.csv", "text": "x"},
    })
    assert status == 400
    assert "import limit" in body


def test_a_legitimate_import_survives_patched_limits(monkeypatch, server):
    monkeypatch.setattr(web_server, "MAX_BODY_BYTES", 20000)
    monkeypatch.setattr(web_server, "MAX_IMPORT_FILE_BYTES", 4096)
    training = make_training(ROWS[:1]).to_csv(index=False)
    readiness = make_readiness([{"Date": "2024-01-01"}]).to_csv(index=False)
    data = post(server, "/api/import", {
        "training": {"name": "training.csv", "text": training},
        "readiness": {"name": "readiness.csv", "text": readiness},
    })
    assert data["window_start"] == "2024-01-01"


def test_body_limit_constants_leave_import_headroom():
    assert web_server.MAX_BODY_BYTES >= 2 * web_server.MAX_IMPORT_FILE_BYTES + 4 * 1024 * 1024


def test_unexpected_errors_are_generic_and_logged(caplog, monkeypatch, server):
    def boom(self, conn):
        raise RuntimeError("secret path /tmp/coach.db")

    monkeypatch.setattr(web_server.Handler, "_overview", boom)
    with caplog.at_level("ERROR"), pytest.raises(urllib.error.HTTPError) as excinfo:
        get(server, "/api/overview")
    assert excinfo.value.code == 500
    body = excinfo.value.read().decode()
    assert "internal server error" in body
    assert "secret path" not in body
    assert "RuntimeError" in caplog.text


def test_workout_summary_api_status_and_productivity(server):
    plan = {
        "for_date": "2024-01-02",
        "session_type": "hinge",
        "items": [
            {"exercise_id": "trap_bar_deadlift", "sets": 2, "reps_low": 3,
             "reps_high": 5, "load_kg": 100, "rir_target": 2,
             "e1rm_kg": 120.0, "e1rm_ref": "set:s0/1",
             "e1rm_quality": "ok", "e1rm_age_days": 2},
        ],
    }
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-02", "plan": plan, "readiness": readiness,
    })["workout"]
    workout_id = started["workout_id"]
    post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
    })
    try:
        get(server, f"/api/workout/{workout_id}/summary")
    except urllib.error.HTTPError as exc:
        assert exc.code == 409
    else:
        raise AssertionError("in-progress summary should be 409")

    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 50, "productivity": 4,
    })
    payload = json.loads(get(server, f"/api/workout/{workout_id}/summary")[1])
    assert payload["summary"]["feedback"]["productivity"] == 4
    assert payload["summary"]["dose"]["per_exercise"]

    try:
        get(server, "/api/workout/missing/summary")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:
        raise AssertionError("unknown summary should be 404")


def test_performance_filters_change_e1rm_results(server):
    sessions = json.loads(get(server, "/api/sessions")[1])
    actual_type = sessions[0]["session_type"]
    base = "/api/performance/e1rm?exercise_id=ssb_squat&from=2024-01-01&to=2024-01-02"
    all_points = json.loads(get(server, base + "&session_type=" + actual_type)[1])
    excluded = json.loads(get(server, base + "&session_type=definitely-not-a-type")[1])
    degraded = json.loads(get(server, base + "&quality=degraded")[1])

    assert all_points["points"]
    assert excluded["points"] == []
    assert degraded["degraded"] == []
    assert degraded["filters"]["quality"] == "degraded"


def test_performance_api_e1rm_dose_and_ratios(server):
    e1rm = json.loads(get(
        server,
        "/api/performance/e1rm?exercise_id=ssb_squat&from=2024-01-01&to=2024-01-02",
    )[1])
    assert e1rm["basis"] == "raw_formula_epley_rir"
    assert len(e1rm["points"]) == 1
    assert e1rm["summary"]["n"] == 1

    dose = json.loads(get(
        server, "/api/performance/dose?from=2024-01-01&to=2024-01-02"
    )[1])
    assert dose["group_by"] == "session"
    assert dose["buckets"]

    ratios = json.loads(get(
        server, "/api/performance/ratios?from=2024-01-01&to=2024-01-02"
    )[1])
    assert ratios["basis"] == "raw_formula_epley_rir"
    assert ratios["relationships"]
    assert "current" in ratios["relationships"][0]
    assert "reason" in ratios["relationships"][0]["current"]
    assert "numerator_observations" in ratios["relationships"][0]["current"]


def test_analysis_readonly_connection_rejects_writes(tmp_path):
    path = tmp_path / "coach.db"
    db.Store(path).close()
    conn = analysis_readonly_connection(path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE forbidden_write (id INTEGER)")
    finally:
        conn.close()


def test_monitoring_analysis_api_structure_and_date_validation(server):
    payload = json.loads(get(
        server, "/api/monitoring-analysis?as_of=2024-01-02"
    )[1])
    assert payload["meta"]["analysis_version"] == "monitoring-analysis-v1"
    assert payload["meta"]["as_of"] == "2024-01-02"
    assert payload["meta"]["read_only"] is True
    assert "database_fingerprint" in payload["meta"]
    assert "dose" in payload and "associations" in payload
    assert payload["calibration"]["historical_state_reconstructable"] is False
    assert isinstance(payload["calibration"]["observations"], list)

    try:
        get(server, "/api/monitoring-analysis?as_of=not-a-date")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    else:
        raise AssertionError("invalid as_of should be 400")


def test_phase5a_review_completion_through_api_is_persisted(server):
    payload = post(server, "/api/reviews", {
        "task_key": "phase5a_review",
        "action": "completed",
        "date": "2027-01-22",
        "decision": "changed",
        "note": "proceed after review",
    })
    task = next(
        item for item in payload["tasks"] if item["key"] == "phase5a_review"
    )
    assert task["status"] == "completed"
    assert task["details"]["decision"] == "changed"
    assert task["details"]["last_completed"] == "2027-01-22"


def test_performance_ratios_are_cached(server, monkeypatch):
    from strength_coach.web import server as web_server

    calls = []
    original = web_server.Handler._performance_ratios

    def counted(self, conn, query):
        calls.append(1)
        return original(self, conn, query)

    monkeypatch.setattr(web_server.Handler, "_performance_ratios", counted)
    url = "/api/performance/ratios?from=2024-01-01&to=2024-01-02"
    assert get(server, url)[0] == 200
    assert get(server, url)[0] == 200
    assert len(calls) == 1


def test_relationship_options_and_validated_add(server, monkeypatch):
    from strength_coach.web import server as web_server

    options = json.loads(get(server, "/api/performance/relationship-options")[1])
    assert "variant_to_main" in options["relationship_types"]
    assert any(item["id"] == "bench_press" for item in options["exercises"])
    assert options["criteria"]

    captured = []
    monkeypatch.setattr(
        web_server.relative_strength_feature,
        "append_relationship",
        lambda relationship: captured.append(relationship) or [relationship],
    )
    payload = post(server, "/api/performance/relationships", {
        "numerator": "front_squat",
        "denominator": "bench_press",
        "relationship_type": "variant_to_main",
        "max_gap_days": 14,
        "max_age_days": 42,
        "min_observations": 2,
    })
    assert payload["ok"] is True
    assert captured[0].numerator == "front_squat"
    assert captured[0].denominator == "bench_press"


def test_monitoring_config_inventory_is_read_only_and_path_safe(server):
    payload = json.loads(get(server, "/api/settings/monitoring")[1])
    assert payload["read_only"] is True
    assert payload["phase"]["locked"] is True
    assert payload["phase"]["period"] == "active"
    assert payload["phase"]["review_due"] == "2027-01-22"
    assert payload["groups"]
    groups = {group["key"]: group for group in payload["groups"]}
    assert "monitoring" in groups and "relationships" in groups
    assert all(row["editable"] is False for group in payload["groups"] for row in group["parameters"])
    assert "/home/" not in json.dumps(payload)
    assert "data/coach.db" not in json.dumps(payload)


def test_monitoring_config_inventory_has_no_write_route(server):
    before = json.loads(get(server, "/api/settings/monitoring")[1])
    status, _ = post_status(server, "/api/settings/monitoring", {})
    after = json.loads(get(server, "/api/settings/monitoring")[1])
    assert status == 404
    assert before["revision"] == after["revision"]
