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
    names = (
        "core.js", "adherence.js", "vbt.js", "settings.js", "app.js", "exercises.js",
        "history.js", "workout.js", "summary.js", "performance.js",
    )
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
    assert 'id="prescribe-top-set"' in page
    assert "Only used when minimum session is ticked" in page
    assert "A/B/C remains" not in page
    assert "Language model" in page
    assert "Regime change" in page
    assert "rejected as predictor" in page
    assert 'id="toast"' in page
    assert 'id="settings-theme"' in page
    assert 'id="settings-resolver-panel"' in page
    assert 'id="settings-resolver-preview-form"' in page
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


def test_review_sheet_is_read_only_history(server):
    status, body = get(server, "/api/review/2024-01-01")
    assert status == 200
    sheet = json.loads(body)
    # The rubric is retired (DEC-EVAL-09): stored rows only, never a fresh score.
    assert sheet["read_only"] is True
    assert isinstance(sheet["items"], list)

    # The write path is gone; recording marks is refused.
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        post(server, "/api/review/2024-01-01", {
            "scores": {"RIR_ADHERENCE": 1.0}, "confidence": "high",
        })
    assert excinfo.value.code == 404


def test_docs_are_rendered_local(server):
    status, body = get(server, "/api/docs")
    assert status == 200
    names = {entry["name"] for entry in json.loads(body)}
    assert "USER-GUIDE.md" in names
    assert "docs/UI-MAP.md" in names

    status, body = get(server, "/api/docs/USER-GUIDE.md")
    assert status == 200
    assert "<h1 id=" in json.loads(body)["html"]


def test_docs_api_exposes_only_the_public_manifest(server):
    status, body = get(server, "/api/docs")
    assert status == 200
    entries = json.loads(body)
    names = {entry["name"] for entry in entries}
    assert "docs/README.md" in names
    assert "docs/archive/audits/W9-SPINAL-CAP.md" in names
    assert "docs/design/TRAINING-MONITORING-SPEC.md" not in names
    assert not any(name.startswith("private/") for name in names)
    assert all(entry["category"] and entry["category_label"] for entry in entries)
    for name in ("private/docs/EVIDENCE.md", "docs/design/TRAINING-MONITORING-SPEC.md"):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            get(server, "/api/docs/" + quote(name, safe=""))
        assert excinfo.value.code == 400, name


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

def test_rubric_calibration_endpoint_is_gone(server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(server, "/api/calibrate")
    assert excinfo.value.code == 404

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


@pytest.mark.slow
def test_programme_endpoint(server):
    data = post(server, "/api/programme", {
        "weeks": 1, "start": "2024-01-02", "start_session_type": "squat",
    })
    assert len(data["entries"]) == 3
    assert data["entries"][0]["date"] == "2024-01-03"
    assert data["entries"][0]["session_type"] == "squat"
    assert data["entries"][0]["prescription"]["items"]




def test_programme_supports_four_and_five_days(server, monkeypatch):
    # This route contract only needs the request/response shape; the weekday schedule is
    # covered cheaply in test_programme.py. Building nine prescriptions here was over-testing.
    def fake_payload(conn, body):
        count = int(body["sessions_per_week"])
        return {"entries": [{"date": "2024-01-02", "session_type": "squat"}] * count}

    monkeypatch.setattr(web_server, "programme_payload", fake_payload)
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


@pytest.mark.slow
def test_programme_job_endpoint_returns_a_pollable_result(server):
    payload = {
        "weeks": 1, "start": "2024-01-02", "start_session_type": "squat",
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
            assert len(current["result"]["entries"]) == 3
            return
        assert current["status"] == "running"
        time.sleep(0.2)
    raise AssertionError("programme job did not finish")


@pytest.mark.slow
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


def test_measurements_support_date_bounds_and_pagination(server):
    for day, value in (("2024-01-01", 40.0), ("2024-01-08", 41.0), ("2024-01-15", 42.0)):
        post(server, "/api/measurements", {
            "metric": "vo2max", "value": value, "date": day, "method": "step test",
        })

    status, body = get(server, "/api/measurements?metric_key=vo2max&limit=1&offset=0")
    assert status == 200
    latest = json.loads(body)
    assert latest["entries"][0]["value"] == 42.0
    assert latest["page"]["total"] == 3
    assert latest["page"]["next_offset"] == 1

    status, body = get(server, "/api/measurements?metric_key=vo2max&limit=1&offset=1")
    older = json.loads(body)
    assert older["entries"][0]["value"] == 41.0

    status, body = get(server, "/api/measurements?from=2024-01-02&to=2024-01-09")
    bounded = json.loads(body)
    assert [row["value"] for row in bounded["entries"]] == [41.0]

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(server, "/api/measurements?from=2024-01-20&to=2024-01-01")
    assert excinfo.value.code == 400


def test_readiness_history_returns_observed_bodyweight_only(server):
    post(server, "/api/readiness", {
        "date": "2024-01-01", "values": {"sleep": 3, "bodyweight_kg": 80.5},
    })
    post(server, "/api/readiness", {
        "date": "2024-01-03", "values": {"sleep": 4, "bodyweight_kg": 80.1},
    })
    status, body = get(
        server,
        "/api/readiness/history?from=2024-01-01&to=2024-01-05&fields=bodyweight_kg",
    )
    assert status == 200
    data = json.loads(body)
    assert [point["date"] for point in data["points"]] == ["2024-01-01", "2024-01-03"]
    assert [point["bodyweight_kg"] for point in data["points"]] == [80.5, 80.1]
    assert data["points"][0]["sources"]["bodyweight_kg"] == "manual"
    assert data["coverage"]["observed_days"] == 2

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(server, "/api/readiness/history?from=2024-01-01&to=2024-01-05&fields=unknown")
    assert excinfo.value.code == 400


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
    assert all("demands" in row for row in data["entities"])
    assert any(row["demands"]["dimensions"] for row in data["entities"])
    evidence = data["demand_catalogue"]["evidence"]
    assert any(entry["id"] == "EV-CHOLEWICKI-1991" for entry in evidence)
    assert all(entry["citation"] for entry in evidence)


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


def test_a_supported_demand_rating_can_cite_an_existing_evidence_id(server, tmp_path,
                                                                     monkeypatch):
    base = tmp_path / "demands.v1.yaml"
    base.write_text(json.dumps({
        "schema_version": "1.0.0",
        "reviewed_on": "2026-10-28",
        "evidence": {"EV-TEST-1": {
            "citation": "Author. Title. Journal, 2020.",
            "doi": "10.1000/test",
            "study_type": "controlled",
            "confidence": "supported",
        }},
        "exercises": {},
    }), encoding="utf-8")
    monkeypatch.setattr(demands_feature.paths, "exercise_demands_yaml", lambda: base)

    data = post(server, "/api/exercises/demands", {
        "exercise_id": "seal_row", "dimension": "axial_spinal",
        "level": "low", "confidence": "supported", "reason": "measured, not inferred",
        "evidence": ["EV-TEST-1"],
    })
    claim = data["demands"]["dimensions"]["axial_spinal"]
    assert claim["confidence"] == "supported"
    assert claim["evidence"] == ["EV-TEST-1"]

    # An id the reviewed file does not define is refused, and no overlay is written.
    status, _ = post_status(server, "/api/exercises/demands", {
        "exercise_id": "seal_row", "dimension": "trunk_stability",
        "level": "low", "confidence": "supported", "reason": "invented source",
        "evidence": ["EV-INVENTED-1"],
    })
    assert status == 400
    assert "EV-TEST-1" in (tmp_path / "demands.local.yaml").read_text(encoding="utf-8")
    assert "EV-INVENTED-1" not in (tmp_path / "demands.local.yaml").read_text(encoding="utf-8")


def test_exercise_post_rejects_an_invalid_id_without_writing(server):
    status, _ = post_status(server, "/api/exercises", {
        "id": "Bad Id",
        "props": {"display": "Bad", "log_names": ["Bad"], "pattern": "squat"},
    })
    assert status == 400


@pytest.mark.slow
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


def test_prescribe_can_add_the_opt_in_top_set(server):
    data = post(server, "/api/prescribe", {
        "date": "2024-01-08", "session_type": "squat", "top_set": True,
    })
    item = next(row for row in data["items"] if row["exercise_id"] == "ssb_squat")
    assert [group["role"] for group in item["set_groups"]] == ["top_set", "back_off"]
    assert data["notes"]["top_set"]["applied"] is True


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
    assert "groups" in data
    assert all("effective_counts" in row for row in data["groups"])
    assert data["coverage"]["accounting"] == "hard"
    assert "heavy_spinal" in data
    assert data["heavy_spinal"]["rir_max"] == 1

    status, body = get(server, "/api/volume?date=2024-01-15&weeks=4&accounting=effective")
    assert status == 200
    effective = json.loads(body)
    assert effective["coverage"]["accounting"] == "effective"
    assert any(row["effective_counts"] != row["counts"] for row in effective["groups"])

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(server, "/api/volume?date=2024-01-15&weeks=4&accounting=invalid")
    assert excinfo.value.code == 400


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


@pytest.mark.slow
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
        "budget": {"weekly_target": {"squat": 11}, "weekly_total": 70},
        "reason": "increase squat target",
    })
    assert status == 400
    assert "VOLUME" in body

    saved = post(server, "/api/settings/volume", {
        "budget": {"weekly_target": {"squat": 11}, "weekly_total": 70},
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


def test_resolver_panel_uses_every_registry_setting(server):
    status, body = get(server, "/api/settings")
    assert status == 200
    registry = json.loads(body)["registry"]
    resolver = [setting for setting in registry if setting["group"] == "Resolver"]
    assert len(resolver) == 29
    assert all(setting["key"].startswith("resolver.") for setting in resolver)
    assert all(
        setting["key"] != "resolver.top_set.preserve_total_sets"
        for setting in resolver
    )
    _status, js = get(server, "/static/settings.js")
    assert 'setting.group === "Resolver"' in js
    assert 'data-resolver-key' in js


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


def test_resolver_policy_and_preview_endpoints(server):
    status, body = get(server, "/api/resolver/policy")
    assert status == 200
    policy = json.loads(body)
    assert policy["digest"]
    assert "required_patterns" in policy["yaml"]

    # An invalid edit is rejected before any file write or backup.
    status, body = post_status(server, "/api/resolver/policy", {
        "yaml": "schema_version: '9.9.9'\n",
    })
    assert status == 400
    assert "schema" in body

    # Resolver disabled: explicit preview returns a structured dispatch failure.
    data = post(server, "/api/resolver/preview", {
        "date": "2024-01-31", "session_type": "squat",
    })
    assert data["ok"] is False
    assert data["stage"] == "dispatch"

    status, body = post_status(server, "/api/settings/profile", {
        "set": {"resolver.enabled": True},
        "effective_from": "2024-01-01",
    })
    assert status == 400
    assert "resolver.enabled" in body

    post(server, "/api/settings/profile", {
        "set": {
            "resolver.enabled": True,
            "resolver.eligibility.auto_requires_can_do": False,
        },
        "resolver_enable_confirmed": True,
        "effective_from": "2024-01-01",
    })
    data = post(server, "/api/resolver/preview", {
        "date": "2024-01-31", "session_type": "squat",
    })
    assert data["ok"] is False
    assert data["stage"] in {"pool_generation", "assignment_search"}
    assert data["message"]


def test_resolver_preview_job_returns_a_pollable_result(server):
    started = post(server, "/api/resolver/preview/jobs", {
        "date": "2024-01-31", "session_type": "squat",
    })
    assert started["status"] == "running"
    job = started
    for _ in range(100):
        status, body = get(server, "/api/resolver/preview/jobs/" + started["job_id"])
        assert status == 200
        job = json.loads(body)
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert job["result"]["ok"] is False
    assert job["result"]["stage"] == "dispatch"


def test_prescribe_job_returns_a_pollable_result(server):
    started = post(server, "/api/prescribe/jobs", {
        "date": "2024-01-01", "session_type": "squat",
    })
    assert started["status"] == "running"
    job = started
    for _ in range(100):
        status, body = get(server, "/api/prescribe/jobs/" + started["job_id"])
        assert status == 200
        job = json.loads(body)
        if job["status"] != "running":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert job["result"]["items"]


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
    assert "weekly" in data
    assert isinstance(data["weekly"]["weeks"], list)
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

    item_index = next(
        index for index, item in enumerate(plan["items"])
        if item["exercise_id"] == "trap_bar_deadlift"
    )
    added = post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
        "plan_item_index": item_index,
    })
    assert len(added["workout"]["sets"]) == 1
    assert added["workout"]["sets"][0]["prescription_item_index"] == item_index
    assert added["workout"]["sets"][0]["plan_item_index"] == item_index

    ended = post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 50,
    })
    assert ended["workout"]["status"] == "completed"
    assert ended["workout"]["duration_min"] == 50
    comparison = {
        item["exercise_id"]: item for item in ended["workout"]["comparison"]["items"]
    }
    assert comparison["trap_bar_deadlift"]["status"] == "under"
    assert comparison["trap_bar_deadlift"]["actual_sets"] == 1
    assert json.loads(get(server, "/api/workout/active")[1])["workout"] is None


def test_workout_set_endpoint_accepts_per_rep_velocities(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    started = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan,
        "readiness": {
            "sleep": 4, "energy": 4, "mood": 4, "soreness": 2,
            "stress": 3, "nutrition": 4, "hydration": 4,
        },
    })["workout"]
    added = post(server, f"/api/workout/{started['workout_id']}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 3, "rir": 2,
        "rep_velocities": [
            {"rep_index": 1, "velocity_mps": 0.62},
            {"rep_index": 2, "velocity_mps": 0.58},
            {"rep_index": 3, "velocity_mps": 0.55},
        ],
    })
    row = next(item for item in added["workout"]["sets"]
               if item["exercise_id"] == "trap_bar_deadlift")
    assert row["velocity"] == 0.583
    assert row["rep_summary"]["count"] == 3


def test_workout_set_api_rejects_bad_per_rep_values_and_accepts_sparse(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    started = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan,
        "readiness": {
            "sleep": 4, "energy": 4, "mood": 4, "soreness": 2,
            "stress": 3, "nutrition": 4, "hydration": 4,
        },
    })["workout"]
    url = f"/api/workout/{started['workout_id']}/sets"
    cases = [
        ([{"rep_index": 4, "velocity_mps": 0.6}], "exceeds reps"),
        ([{"rep_index": 1.5, "velocity_mps": 0.6}], "positive integer"),
        ([{"rep_index": 1, "velocity_mps": float("nan")}], "finite and positive"),
        ([{"rep_index": 1, "velocity_mps": float("inf")}], "finite and positive"),
        ([{"rep_index": 1, "velocity_mps": 0.6},
          {"rep_index": 1, "velocity_mps": 0.5}], "duplicate"),
    ]
    for values, message in cases:
        status, body = post_status(server, url, {
            "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 3,
            "rir": 2, "rep_velocities": values,
        })
        assert status == 400, body
        assert message in body

    added = post(server, url, {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 3,
        "rir": 2, "rep_velocities": [
            {"rep_index": 1, "velocity_mps": 0.62},
            {"rep_index": 3, "velocity_mps": 0.55},
        ],
    })
    row = next(item for item in added["workout"]["sets"]
               if item["exercise_id"] == "trap_bar_deadlift")
    assert row["rep_summary"]["count"] == 2
    assert row["velocity"] == 0.585


def test_second_fragment_reuses_day_plan_and_readiness(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-02", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    first = post(server, "/api/workout/start", {
        "date": "2024-01-02", "plan": plan, "readiness": readiness,
    })["workout"]
    post(server, f"/api/workout/{first['workout_id']}/end", {
        "session_rpe": 7, "duration_min": 30,
    })
    second = post(server, "/api/workout/start", {
        "date": "2024-01-02",
        "plan": first["original_plan"],
        "readiness": first["readiness"],
        "reuse_readiness": True,
        "prescription_id": first["prescription_id"],
    })["workout"]
    assert second["prescription_id"] == first["prescription_id"]
    assert second["readiness"] == first["readiness"]
    assert second["status"] == "in_progress"


def test_imported_and_live_fragment_share_a_training_day(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan, "readiness": readiness,
    })["workout"]
    post(server, f"/api/workout/{started['workout_id']}/end", {
        "session_rpe": 7, "duration_min": 30,
    })
    data = json.loads(get(server, "/api/history/days?limit=5")[1])
    day = next(row for row in data["days"] if row["occurred_on"] == "2024-01-01")
    assert day["fragment_count"] >= 2
    assert day["active_fragment_count"] >= 2
    assert sum(1 for item in day["fragments"] if item.get("workout_id")) >= 1
    assert set(day["sources"]) >= {"import", "workout"}


def test_history_api_is_strict_json_with_missing_values(server):
    status, body = get(server, "/api/history/days?limit=5")
    assert status == 200
    assert "NaN" not in body
    # Python's json module accepts NaN; browsers do not. Make that contract explicit.
    data = json.loads(
        body,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-strict JSON constant: {token}")
        ),
    )
    assert data["days"]
    assert data["days"][0]["fragments"][0]["prescription_id"] is None


def test_workout_start_rejects_invalid_groups_and_snapshot_without_active_workout(server):
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    bad_groups = json.loads(json.dumps(plan))
    bad_groups["items"][0]["set_groups"] = [
        {"role": "top_set", "sets": 1, "load_kg": 110, "reps_low": 3,
         "reps_high": 5, "rir_target": 1},
        {"role": "back_off", "sets": 1, "load_kg": 90, "reps_low": 3,
         "reps_high": 5, "rir_target": 2},
    ]
    status, body = post_status(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": bad_groups, "readiness": readiness,
    })
    assert status == 400
    assert "must equal item.sets" in body

    bad_snapshot = json.loads(json.dumps(plan))
    bad_snapshot["generated_session"] = {"slots": [{"id": "hinge_main"}]}
    status, body = post_status(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": bad_snapshot, "readiness": readiness,
    })
    assert status == 400
    assert "exercise_id" in body

    active = json.loads(get(server, "/api/workout/active")[1])
    assert active["workout"] is None


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


def test_history_days_endpoint_groups_fragments(server):
    status, body = get(server, "/api/history/days?limit=10")
    assert status == 200
    data = json.loads(body)
    assert data["total"] == 1
    day = data["days"][0]
    assert day["occurred_on"] == "2024-01-01"
    assert day["fragment_count"] == 1
    assert day["fragments"][0]["session_id"] == "2024-01-01"
    assert day["session_type"]


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


def test_exercise_history_api_returns_completed_sets_and_pages(server):
    status, body = get(
        server,
        "/api/exercise-history?exercise_id=ssb_squat&limit=5&on_or_before=2024-01-01",
    )
    assert status == 200
    data = json.loads(body)
    assert data["total"] == 1
    assert data["has_more"] is False
    assert data["included_exercises"] == [{"id": "ssb_squat", "display": "SSB Squat"}]
    assert data["sessions"][0]["occurred_on"] == "2024-01-01"
    assert data["sessions"][0]["sets"][0]["load_kg"] == 100.0

    status, body = get(
        server,
        "/api/exercise-history?exercise_id=ssb_squat&on_or_before=2023-12-31",
    )
    assert status == 200
    assert json.loads(body)["total"] == 0

    status, body = get(
        server,
        "/api/exercise-history?exercise_id=ssb_squat&limit=1&start=2024-01-01&"
        "end=2024-01-01&include_analytics=true",
    )
    assert status == 200
    bounded = json.loads(body)
    assert bounded["start"] == "2024-01-01" and bounded["end"] == "2024-01-01"
    assert bounded["analytics"]["session_count"] == 1
    assert bounded["analytics"]["working_sets"] == 1
    assert bounded["analytics"]["daily"][0]["date"] == "2024-01-01"

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(server, "/api/exercise-history?exercise_id=not_a_lift")
    assert excinfo.value.code == 400


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
    status, body = get(server, f"/api/review/{workout_id}")
    assert status == 200
    sheet = json.loads(body)
    assert sheet["read_only"] is True
    assert sheet["items"] == []

    # No review step closes the workout any more; the write route is gone.
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        post(server, f"/api/review/{workout_id}", {"scores": {}})
    assert excinfo.value.code == 404
    comparison = {
        item["exercise_id"]: item for item in sheet["workout"]["comparison"]["items"]
    }
    assert comparison["trap_bar_deadlift"]["actual_sets"] == 1


def test_web_plan_edit_targets_the_correct_item_after_removal(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    data = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan, "readiness": readiness,
    })
    workout_id = data["workout"]["workout_id"]
    first, second = plan["items"][0], plan["items"][1]
    removed = post(server, f"/api/workout/{workout_id}/plan/remove-exercise", {
        "item_index": 0,
    })["workout"]
    assert all(item["exercise_id"] != first["exercise_id"] for item in removed["plan"]["items"])
    index = next(
        index for index, item in enumerate(removed["plan"]["items"])
        if item["exercise_id"] == second["exercise_id"]
    )
    before = removed["plan"]["items"][index]["sets"]
    changed = post(server, f"/api/workout/{workout_id}/plan/set-count", {
        "item_index": index, "delta": 1,
    })["workout"]
    assert changed["plan"]["items"][index]["exercise_id"] == second["exercise_id"]
    assert changed["plan"]["items"][index]["sets"] == before + 1


def test_web_plan_edits_reject_actions_that_would_rewrite_logged_sets(server):
    plan = post(server, "/api/prescribe", {"date": "2024-01-01", "session_type": "hinge"})
    readiness = {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }
    data = post(server, "/api/workout/start", {
        "date": "2024-01-01", "plan": plan, "readiness": readiness,
    })
    workout_id = data["workout"]["workout_id"]
    index, item = next(
        (index, item) for index, item in enumerate(plan["items"])
        if item["exercise_id"] == "trap_bar_deadlift"
    )
    for set_index in (1, 2):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": item["exercise_id"], "load_kg": 100, "reps": 5, "rir": 2,
            "set_index": set_index, "plan_item_index": index,
        })
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        post(server, f"/api/workout/{workout_id}/plan/swap", {
            "item_index": index, "exercise_id": "conventional_deadlift",
        })
    assert excinfo.value.code == 409
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        post(server, f"/api/workout/{workout_id}/plan/set-count", {
            "item_index": index, "delta": -int(item["sets"]) + 1,
        })
    assert excinfo.value.code == 409


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
    deadlift_index = next(
        index for index, item in enumerate(plan["items"])
        if item["exercise_id"] == "trap_bar_deadlift"
    )
    swapped = post(server, f"/api/workout/{workout_id}/plan/swap", {
        "item_index": deadlift_index, "exercise_id": "conventional_deadlift",
    })
    assert swapped["workout"]["plan"]["items"][deadlift_index]["exercise_id"] == "conventional_deadlift"
    assert swapped["workout"]["original_plan"]["items"][deadlift_index]["exercise_id"] == "trap_bar_deadlift"

    added = post(server, f"/api/workout/{workout_id}/plan/add-exercise", {
        "exercise_id": "lat_pulldown", "sets": 2, "reps_low": 10, "reps_high": 12,
    })
    assert any(item["exercise_id"] == "lat_pulldown" for item in added["workout"]["plan"]["items"])

    changed = post(server, f"/api/workout/{workout_id}/plan/set-count", {
        "item_index": deadlift_index, "delta": 1,
    })
    assert changed["workout"]["plan"]["items"][deadlift_index]["sets"] == 6

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

    status, body = get(server, f"/api/history/{session_id}")
    current = json.loads(body)
    overridden = post(server, f"/api/history/{session_id}/edit", {
        "sets": current["sets"],
        "forms": [{"exercise_id": first["exercise_id"], "rating": 2,
                   "note": "coach override"}],
        "reason": "form override",
    })
    form = next(row for row in overridden["session"]["forms"]
                if row["exercise_id"] == first["exercise_id"])
    assert form["rating"] == 2
    assert form["note"] == "coach override"

    # Blank means leave unchanged, not clear: the omitted rating must preserve both fields.
    unchanged = post(server, f"/api/history/{session_id}/edit", {
        "sets": current["sets"],
        "forms": [{"exercise_id": first["exercise_id"], "rating": None,
                   "note": "must not replace"}],
        "reason": "blank form",
    })
    form = next(row for row in unchanged["session"]["forms"]
                if row["exercise_id"] == first["exercise_id"])
    assert form["rating"] == 2
    assert form["note"] == "coach override"


def test_form_ratings_do_not_change_the_prescription(server):
    body = {"date": "2024-02-01", "session_type": "squat"}
    baseline = post(server, "/api/prescribe", body)
    _, payload = get(server, "/api/history?limit=1")
    session_id = json.loads(payload)["sessions"][0]["session_id"]
    _, payload = get(server, f"/api/history/{session_id}")
    detail = json.loads(payload)
    exercise_id = detail["sets"][0]["exercise_id"]
    post(server, f"/api/history/{session_id}/edit", {
        "sets": detail["sets"],
        "forms": [{"exercise_id": exercise_id, "rating": 1, "note": "form only"}],
        "reason": "form-only correction",
    })
    after = post(server, "/api/prescribe", body)
    assert after == baseline


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


def test_resolver_preview_uses_the_direct_prescription_response(server):
    _status, js = get(server, "/static/settings.js")
    assert "previous.prescription" not in js
    assert "current.prescription" not in js
    assert "data.prescription" not in js
    assert "const before = previous;" in js
    assert "const after = current;" in js
    assert "window.__lastPrescription = plan;" in js
    assert "/api/resolver/preview/jobs" in js
    assert "job.status === \"running\"" in js
    assert "pending_ratings" in js
    assert "Rate suggestions to start" in js
    assert "Suitability ratings needed" in js
    _status, app_js = get(server, "/static/app.js")
    assert "Suitability ratings needed" in app_js
    assert "pending_ratings" in app_js


def test_prescribe_renders_a_top_set_rejection_reason(server):
    _status, js = get(server, "/static/app.js")
    assert "Top set not applied" in js
    assert "topSet?.reason" in js


def test_prescribe_exposes_accessories_only_minimum_mode(server):
    _status, page = get(server, "/")
    assert 'id="prescribe-accessories-only"' in page
    assert 'value="accessory"' in page
    assert 'value="auto" selected' in page
    _status, js = get(server, "/static/app.js")
    assert "minimum_accessories_only" in js
    assert "Accessories only" in page
    _status, performance_js = get(server, "/static/performance.js")
    assert "chart-title" in performance_js
    assert "chartAxes" in performance_js
    assert "chart-dialog" in page
    assert "hard sets vs next e1RM" in performance_js


def test_prescribe_top_set_control_is_gated_by_the_setting(server):
    _status, page = get(server, "/")
    assert 'id="prescribe-top-set-note"' in page
    _status, js = get(server, "/static/app.js")
    assert "syncPrescribeTopSet" in js
    assert 'resolver.top_set.mode' in js
    assert "Top set is off in Settings" in js
    assert "independent of dynamic exercise selection" in js


def test_workout_ui_renders_and_prefills_planned_set_groups(server):
    _status, js = get(server, "/static/workout.js")
    assert "workoutSetGroupsHtml(item)" in js
    assert "workoutNextGroup" in js
    assert "workoutGroupForRole" in js
    assert "applyWorkoutGroup" in js
    assert "set_role: $("#workout-set-role").value || null" in js


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


def test_the_workout_logger_accepts_per_rep_velocity(server):
    status, page = get(server, "/")
    assert status == 200
    assert 'id="workout-set-rep-velocities"' in page
    status, js = get(server, "/static/workout.js")
    assert status == 200
    assert "parseRepVelocities" in js
    assert "rep_velocities" in js


def test_the_history_edit_sheet_can_override_form_ratings(server):
    status, page = get(server, "/")
    assert status == 200
    assert 'id="history-edit-forms"' in page
    status, js = get(server, "/static/history.js")
    assert status == 200
    assert "historyFormRows" in js
    assert "collectHistoryForms" in js
    assert "data-h-form-rating" in js
    assert "data-h-form-note" in js
    assert "Leave a rating blank" in page
    assert "leave any existing rating and note unchanged" in page
    assert "ratings cannot be removed" in page
    assert "— leave unchanged" in js


def test_exercise_search_filter_rebuilds_the_select_options(server):
    status, js = get(server, "/static/core.js")
    assert status == 200
    assert "optionSignature" in js
    assert "select.innerHTML = entries.map" in js
    assert "option.hidden" not in js
    assert "select._filterAll" in js


def test_a_prescribed_plan_is_cached_across_reloads(server):
    status, page = get(server, "/")
    assert status == 200
    assert '/static/prescription-cache.js' in page
    status, cache = get(server, "/static/prescription-cache.js")
    assert status == 200
    assert "strength-coach.prescription.v1" in cache
    assert "MAX_AGE_MS" in cache and "savedAt > current" in cache
    assert "selectionDiffers" in cache
    status, js = get(server, "/static/app.js")
    assert status == 200
    assert "restoreCachedPrescription" in js
    assert "Cached prescription restored" in js
    assert "Cached plan:" in js and "Current form:" in js
    assert "Start cached plan" in js
    assert "invalidateStalePrescriptionCache" in js
    assert "selectionDiffers(cached.plan, currentPrescribeSelection" in js
    assert "discard-cached-prescription" in js
    assert "updateWorkflowStep();\n    restoreCachedPrescription();" in js
    assert "const show = allowed || cached;" in js
    assert "requestPrescription" in js
    assert "/api/prescribe/jobs" in js
    status, workout = get(server, "/static/workout.js")
    assert status == 200
    assert "clearCachedPrescription" in workout
    assert "__prescriptionFromCache" in workout
    assert "Start the cached plan" in workout
    status, settings = get(server, "/static/settings.js")
    assert status == 200
    assert "cachePrescription(plan)" in settings


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
    revision = json.loads(get(server, "/api/performance/relationships")[1])["revision"]
    payload = post(server, "/api/performance/relationships", {
        "numerator": "front_squat",
        "denominator": "bench_press",
        "relationship_type": "variant_to_main",
        "max_gap_days": 14,
        "max_age_days": 42,
        "min_observations": 2,
        "revision": revision,
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


def test_relationship_crud_api_enforces_revision_and_reset(server, tmp_path, monkeypatch):
    import shutil

    from strength_coach.web import server as web_server

    shutil.copyfile(
        web_server.relative_strength_feature.paths.config_dir(
            "strength-relationships.v1.yaml"
        ),
        tmp_path / "strength-relationships.v1.yaml",
    )
    monkeypatch.setattr(
        web_server.relative_strength_feature.paths,
        "config_dir",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    monkeypatch.setattr(
        web_server.relative_strength_feature.paths,
        "data_dir",
        lambda *parts: tmp_path.joinpath("data", *parts),
    )

    listed = json.loads(get(server, "/api/performance/relationships")[1])
    revision = listed["revision"]
    assert listed["relationships"]
    assert listed["relationships"][0]["origin"] == "canonical"
    canonical_before = (tmp_path / "strength-relationships.v1.yaml").read_bytes()

    addition = {
        "numerator": "front_squat",
        "denominator": "bench_press",
        "relationship_type": "variant_to_main",
        "max_gap_days": 14,
        "max_age_days": 42,
        "min_observations": 2,
    }
    status, _ = post_status(server, "/api/performance/relationships", addition)
    assert status == 400
    status, _ = post_status(
        server, "/api/performance/relationships",
        {**addition, "revision": "stale-revision"},
    )
    assert status == 409
    assert not (tmp_path / "strength-relationships.local.yaml").exists()
    assert (tmp_path / "strength-relationships.v1.yaml").read_bytes() == canonical_before

    added_payload = post(server, "/api/performance/relationships", {
        **addition, "revision": revision,
    })
    assert added_payload["ok"] is True
    added = next(
        item for item in added_payload["relationships"]
        if item["id"] == "front_squat_to_bench_press"
    )
    current = added_payload["revision"]
    assert current != revision
    assert added["origin"] == "local"

    first = listed["relationships"][0]
    update_body = {
        "numerator": first["numerator"],
        "denominator": first["denominator"],
        "relationship_type": first["relationship_type"],
        "max_gap_days": 9,
        "max_age_days": 42,
        "min_observations": 2,
        "label": "Edited via API",
        "notes": "API test",
    }
    status, _ = post_status(
        server, f"/api/performance/relationships/{first['id']}/update", update_body
    )
    assert status == 400
    updated = post(
        server,
        f"/api/performance/relationships/{first['id']}/update",
        {**update_body, "revision": current},
    )
    edited = next(item for item in updated["relationships"] if item["id"] == first["id"])
    assert edited["label"] == "Edited via API"
    assert edited["origin"] == "canonical"
    current = updated["revision"]

    status, _ = post_status(
        server,
        f"/api/performance/relationships/{first['id']}/delete",
        {"revision": revision},
    )
    assert status == 409
    deleted = post(
        server,
        f"/api/performance/relationships/{first['id']}/delete",
        {"revision": current},
    )
    assert all(item["id"] != first["id"] for item in deleted["relationships"])
    assert any(item["id"] == first["id"] for item in deleted["hidden"])
    assert any(item["id"] == first["id"] and item["origin"] == "canonical"
               for item in deleted["hidden"])
    current = deleted["revision"]

    reset = post(
        server,
        f"/api/performance/relationships/{first['id']}/reset",
        {"revision": current},
    )
    restored = next(item for item in reset["relationships"] if item["id"] == first["id"])
    assert restored["label"] == first["label"]
    assert all(item["id"] != first["id"] for item in reset["hidden"])
    assert (tmp_path / "strength-relationships.local.yaml").is_file()
    assert added["id"] == "front_squat_to_bench_press"

    removed_local = post(
        server,
        f"/api/performance/relationships/{added['id']}/delete",
        {"revision": reset["revision"]},
    )
    assert all(item["id"] != added["id"] for item in removed_local["relationships"])
    assert all(item["id"] != added["id"] for item in removed_local["hidden"])


def test_step5_report_window_endpoints(server):
    calibration = json.loads(get(
        server, "/api/e1rm/calibration?window_days=30"
    )[1])
    assert calibration["window_days"] == 30
    assert calibration["preview"] is True
    assert calibration["active_window_days"] == 84
    assert "calibration" in calibration and "active_calibration" in calibration

    coverage = json.loads(get(
        server, "/api/e1rm/tests-needed?window_days=30"
    )[1])
    assert coverage["window_days"] == 30
    assert coverage["preview"] is True
    assert isinstance(coverage["tests_needed"], list)

    for path in (
        "/api/e1rm/calibration?window_days=3",
        "/api/e1rm/tests-needed?window_days=400",
    ):
        try:
            get(server, path)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError(path + " should be rejected")

    cadence = json.loads(get(server, "/api/test-cadence")[1])
    assert "due" in cadence and "next_due" in cadence


def test_e1rm_coverage_preview_propagates_window(monkeypatch):
    captured = {}

    def fake_build(conn, *, window_days):
        captured["build"] = window_days
        return []

    def fake_coverage(conn, *, report, window_days):
        captured["coverage"] = window_days
        return []

    monkeypatch.setattr(web_server.e1rm_calibration_feature, "build", fake_build)
    monkeypatch.setattr(web_server.e1rm_calibration_feature, "coverage", fake_coverage)
    monkeypatch.setattr(
        web_server.e1rm_calibration_feature, "coverage_as_dict",
        lambda rows: [{"note": "window " + str(captured["coverage"]) + " days"}],
    )
    result = web_server.Handler._e1rm_tests_needed_response(None, object(), 30)
    assert captured == {"build": 30, "coverage": 30}
    assert "30 days" in result["tests_needed"][0]["note"]


def test_volume_week_bounds_are_enforced(server):
    for weeks in ("1", "52"):
        status, body = get(server, "/api/volume?weeks=" + weeks)
        assert status == 200, body
    for weeks in ("0", "53", "-1", "4.5", "abc", ""):
        try:
            get(server, "/api/volume?weeks=" + weeks)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400, weeks
        else:
            raise AssertionError("weeks=" + weeks + " should be rejected")


def test_symptom_attribution_round_trips_and_exposes_options(server):
    state = post(server, "/api/state/symptom", {
        "date": "2024-01-01", "timing": "post_session", "region": "low_back",
        "level": 0, "settled": "yes", "session": "2024-01-01",
        "onset": "2024-01-01", "confidence": "likely",
    })
    entry = state["symptoms"][-1]
    assert entry["attributed_session_id"] == "2024-01-01"
    assert entry["attribution_confidence"] == "likely"

    history = json.loads(get(server, "/api/symptoms/history?limit=10")[1])
    assert history["entries"][0]["attributed_session_id"] == "2024-01-01"
    assert history["entries"][0]["attributed_session_on"] == "2024-01-01"

    detail = json.loads(get(server, "/api/history/2024-01-01")[1])
    assert detail["attributed_symptoms"][0]["attribution_confidence"] == "likely"

    days = json.loads(get(server, "/api/history/days?limit=10")[1])
    day = next(row for row in days["days"] if row["occurred_on"] == "2024-01-01")
    assert day["attributed_symptom_count"] == 1

    options = json.loads(get(
        server, "/api/symptoms/attribution-options?onset=2024-01-02&timing=pre_session"
    )[1])
    assert options["sessions"][0]["session_id"] == "2024-01-01"

    code, body = post_status(server, "/api/state/symptom", {
        "date": "2024-01-01", "timing": "post_session", "region": "low_back",
        "level": 0, "session": "2024-01-01", "onset": "2024-01-01",
        "confidence": "certain",
    })
    assert code == 400
    assert "attribution_confidence" in json.loads(body).get("fields", {})



IOS_CONFIG = """# header
mutations_enabled: true
issued_plan_ttl_seconds: 3600
plan_request_ttl_seconds: 900
receipt_retention_days: 30
"""


def test_ios_settings_api_round_trip_and_validation(server, tmp_path, monkeypatch):
    config = tmp_path / "ios.v1.yaml"
    config.write_text(IOS_CONFIG, encoding="utf-8")
    monkeypatch.setattr(
        web_server.ios_config, "config_path", lambda path=None: config
    )

    status, body = get(server, "/api/settings/ios")
    assert status == 200
    data = json.loads(body)
    assert data["effective"]["issued_plan_ttl_seconds"] == 3600
    assert data["source"] == str(config)
    assert data["restart_required"] is False

    saved = post(server, "/api/settings/ios", {
        "values": {
            "mutations_enabled": False,
            "issued_plan_ttl_seconds": 7200,
            "plan_request_ttl_seconds": 1200,
            "receipt_retention_days": 14,
        },
    })
    assert saved["effective"] == {
        "mutations_enabled": False,
        "issued_plan_ttl_seconds": 7200,
        "plan_request_ttl_seconds": 1200,
        "receipt_retention_days": 14,
        "watch_enabled": False,
        "idle_warn_seconds": 10800,
        "idle_abandon_seconds": 86400,
    }
    assert "issued_plan_ttl_seconds: 7200" in config.read_text(encoding="utf-8")

    before = config.read_text(encoding="utf-8")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        post(server, "/api/settings/ios", {
            "values": {"receipt_retention_days": 0},
        })
    assert excinfo.value.code == 400
    fields = json.loads(excinfo.value.read().decode()).get("fields", {})
    assert "receipt_retention_days" in fields
    assert config.read_text(encoding="utf-8") == before


def test_symptom_history_limit_order_and_all(server):
    empty = json.loads(get(server, "/api/symptoms/history?limit=5")[1])
    assert empty == {
        "entries": [], "total": 0, "shown": 0, "has_more": False, "limit": 5,
    }
    days = [f"2025-01-{day:02d}" for day in range(1, 13)]
    for index, day in enumerate(days, start=1):
        post(server, "/api/state/symptom", {
            "date": day, "region": "low_back", "level": index % 4,
            "settled": index % 2 == 0, "note": "entry " + str(index),
        })
    limited = json.loads(get(server, "/api/symptoms/history?limit=5")[1])
    assert limited["total"] == 12
    assert limited["shown"] == 5
    assert limited["has_more"] is True
    assert [row["logged_on"] for row in limited["entries"]] == list(reversed(days))[:5]
    assert [row["note"] for row in limited["entries"]] == [
        "entry 12", "entry 11", "entry 10", "entry 9", "entry 8",
    ]
    all_history = json.loads(get(server, "/api/symptoms/history?limit=5&all=1")[1])
    assert all_history["total"] == 12
    assert all_history["shown"] == 12
    assert all_history["has_more"] is False
    assert [row["logged_on"] for row in all_history["entries"]] == list(reversed(days))


def _strict_json(body: str):
    """Browsers reject NaN/Infinity; make that contract explicit for the adherence payload."""
    return json.loads(
        body,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-strict JSON constant: {token}")
        ),
    )


def _adherence_readiness():
    return {
        "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
        "nutrition": 4, "hydration": 4,
    }


def test_completed_summary_and_history_expose_adherence(server):
    plan = {
        "for_date": "2024-01-02",
        "session_type": "hinge",
        "items": [
            {"exercise_id": "trap_bar_deadlift", "sets": 3, "reps_low": 3,
             "reps_high": 5, "load_kg": 100, "rir_target": 2},
            {"exercise_id": "competition_bench_press", "sets": 2, "reps_low": 5,
             "reps_high": 5, "load_kg": 80, "rir_target": 2},
        ],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-02", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    for reps in (5, 4, 6, 5):          # four trap-bar sets: three slots + one extra
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": reps, "rir": 2,
        })
    post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "competition_bench_press", "load_kg": 80, "reps": 5, "rir": 3,
    })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 45, "productivity": 4,
    })

    status, body = get(server, f"/api/workout/{workout_id}/summary")
    assert status == 200
    summary = _strict_json(body)["summary"]
    adherence = summary["adherence"]
    assert adherence["version"] == 1
    assert adherence["status"] == "available"
    original = adherence["original"]
    final = adherence["final_plan"]
    for view in (original, final):
        assert view["prescribed_sets"] == 5
        assert view["performed_sets"] == 5
        assert view["matched_sets"] == 4
        assert view["missing_sets"] == 1
        assert view["extra_sets"] == 1
        assert view["set_completion"] == {
            "numerator": 4, "denominator": 5, "ratio": 0.8,
        }
        for metric in (
            view["set_completion"], view["reps"]["attainment"],
            view["load"]["attainment"], view["rir"]["attainment"],
        ):
            assert set(metric) == {"numerator", "denominator", "ratio"}
        assert len(view["exercises"]) == 2
        assert view["exercises"][0]["sets"]
        assert "reps_status" in view["exercises"][0]["sets"][0]
        assert "load_deviation_kg" in view["exercises"][0]["sets"][0]
        assert "rir_deviation" in view["exercises"][0]["sets"][0]
    assert original["exercises"][0]["extra_sets"] == 1
    assert "completion" not in summary
    assert summary["feedback"]["duration_min"] == 45.0
    assert summary["comparison"]["status"] == "unavailable"
    assert summary["dose"]["per_exercise"]

    status, body = get(server, f"/api/history/{workout_id}")
    assert status == 200
    detail = _strict_json(body)
    assert detail["adherence"]["original"]["matched_sets"] == 4
    assert detail["adherence"]["final_plan"]["matched_sets"] == 4
    assert detail["adherence"]["original"]["exercises"][0]["sets"]
    # Existing history fields remain present and unchanged.
    assert detail["sets"]
    assert "feedback" in detail and "forms" in detail
    assert "workout_note" in detail


def test_summary_adherence_keeps_original_and_modified_prescriptions_apart(server):
    plan = {
        "for_date": "2024-01-03",
        "session_type": "hinge",
        "items": [{
            "exercise_id": "trap_bar_deadlift", "sets": 5, "reps_low": 3,
            "reps_high": 5, "load_kg": 100, "rir_target": 2,
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-03", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    post(server, f"/api/workout/{workout_id}/plan/set-count", {
        "item_index": 0, "delta": -2,
    })
    for _ in range(3):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
        })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 40,
    })

    _, body = get(server, f"/api/workout/{workout_id}/summary")
    adherence = _strict_json(body)["summary"]["adherence"]
    assert adherence["original"]["prescribed_sets"] == 5
    assert adherence["original"]["matched_sets"] == 3
    assert adherence["original"]["missing_sets"] == 2
    assert adherence["original"]["set_completion"]["ratio"] == 0.6
    assert adherence["final_plan"]["prescribed_sets"] == 3
    assert adherence["final_plan"]["matched_sets"] == 3
    assert adherence["final_plan"]["missing_sets"] == 0
    assert adherence["final_plan"]["set_completion"]["ratio"] == 1.0
    assert adherence["changes"]["set_count_changed"] == [{
        "plan_item_index": 0,
        "exercise_id": "trap_bar_deadlift",
        "from_sets": 5,
        "to_sets": 3,
    }]

    _, body = get(server, f"/api/history/{workout_id}")
    history_adherence = _strict_json(body)["adherence"]
    assert history_adherence["original"]["prescribed_sets"] == 5
    assert history_adherence["final_plan"]["prescribed_sets"] == 3


def test_imported_history_session_reports_adherence_unavailable(server):
    status, body = get(server, "/api/history/2024-01-01")
    assert status == 200
    detail = _strict_json(body)
    adherence = detail["adherence"]
    assert adherence["status"] == "unavailable"
    assert adherence["reason"] == "no_prescription_snapshot"
    assert detail["vbt"]["status"] == "unavailable"
    assert detail["vbt"]["reason"] == "no_prescription_snapshot"
    for view in (adherence["original"], adherence["final_plan"]):
        assert view["status"] == "unavailable"
        assert view["reason"] == "no_prescription_snapshot"
        assert view["set_completion"] == {
            "numerator": 0, "denominator": 0, "ratio": None,
        }
        assert "no_prescription_snapshot" in view["quality"]["unavailable_metrics"]
    assert detail["sets"]          # the imported actual sets still render


def test_history_edit_updates_adherence_from_current_sets(server):
    plan = {
        "for_date": "2024-01-04",
        "session_type": "hinge",
        "items": [{
            "exercise_id": "trap_bar_deadlift", "sets": 3, "reps_low": 3,
            "reps_high": 5, "load_kg": 100, "rir_target": 2,
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-04", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    for reps in (5, 4):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": reps, "rir": 2,
        })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 40,
    })

    _, body = get(server, f"/api/history/{workout_id}")
    detail = _strict_json(body)
    assert detail["adherence"]["original"]["performed_sets"] == 2
    assert detail["adherence"]["original"]["missing_sets"] == 1

    first = detail["sets"][0]
    edited = post(server, f"/api/history/{workout_id}/edit", {
        "sets": [first], "reason": "keep one set",
    })
    assert edited["session"]["adherence"]["original"]["performed_sets"] == 1
    assert edited["session"]["adherence"]["original"]["missing_sets"] == 2

    _, body = get(server, f"/api/history/{workout_id}")
    reread = _strict_json(body)
    assert reread["adherence"]["original"]["matched_sets"] == 1
    assert reread["adherence"]["original"]["missing_sets"] == 2

    # The completed summary reads the same corrected leaf rows, not the live workout draft.
    _, body = get(server, f"/api/workout/{workout_id}/summary")
    summary = _strict_json(body)["summary"]
    assert summary["adherence"]["original"]["matched_sets"] == 1
    assert summary["adherence"]["original"]["missing_sets"] == 2


def test_active_workout_does_not_expose_completed_adherence(server):
    plan = {
        "for_date": "2024-01-05",
        "session_type": "hinge",
        "items": [{
            "exercise_id": "trap_bar_deadlift", "sets": 2, "reps_low": 3,
            "reps_high": 5, "load_kg": 100, "rir_target": 2,
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-05", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]

    _, body = get(server, f"/api/workout/{workout_id}")
    detail = _strict_json(body)["workout"]
    assert detail["status"] == "in_progress"
    assert "adherence" not in detail

    try:
        get(server, f"/api/workout/{workout_id}/summary")
    except urllib.error.HTTPError as exc:
        assert exc.code == 409
    else:
        raise AssertionError("in-progress summary should be 409")


def test_voided_session_adherence_is_explicitly_unavailable(server):
    plan = {
        "for_date": "2024-01-06",
        "session_type": "hinge",
        "items": [{
            "exercise_id": "trap_bar_deadlift", "sets": 2, "reps_low": 3,
            "reps_high": 5, "load_kg": 100, "rir_target": 2,
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-06", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
    })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 30,
    })

    voided = post(server, f"/api/history/{workout_id}/void", {"reason": "duplicate"})
    assert voided["adherence"]["status"] == "unavailable"
    assert voided["adherence"]["reason"] == "session_voided"
    assert voided["vbt"]["status"] == "unavailable"
    assert voided["vbt"]["reason"] == "session_voided"

    _, body = get(server, f"/api/workout/{workout_id}/summary")
    summary = _strict_json(body)["summary"]
    assert summary["adherence"]["status"] == "unavailable"
    assert summary["adherence"]["reason"] == "session_voided"
    assert summary["vbt"]["status"] == "unavailable"
    assert summary["vbt"]["reason"] == "session_voided"


def test_summary_adherence_handles_missing_targets_explicitly(server):
    plan = {
        "for_date": "2024-01-07",
        "session_type": "hinge",
        "items": [{"exercise_id": "trap_bar_deadlift", "sets": 2}],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-07", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
    })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 30,
    })

    _, body = get(server, f"/api/workout/{workout_id}/summary")
    adherence = _strict_json(body)["summary"]["adherence"]
    assert adherence["status"] == "available"
    original = adherence["original"]
    assert original["prescribed_sets"] == 2
    assert original["matched_sets"] == 1
    assert original["missing_sets"] == 1
    for metric in (original["reps"], original["load"], original["rir"]):
        assert metric["evaluated_sets"] == 0
        assert metric["attainment"] == {
            "numerator": 0, "denominator": 0, "ratio": None,
        }
    unavailable = set(original["quality"]["unavailable_metrics"])
    assert {"missing_prescribed_reps", "missing_prescribed_load",
            "missing_prescribed_rir"} <= unavailable


def test_history_detail_renders_prescription_adherence(server):
    status, page = get(server, "/")
    assert status == 200
    assert "/static/adherence.js" in page
    assert page.index("/static/adherence.js") < page.index("/static/history.js")
    assert "Prescription adherence compares performed working sets" in page

    status, js = get(server, "/static/adherence.js")
    assert status == 200
    for text in (
        "renderHistoryAdherence",
        "Original prescription",
        "Final modified prescription",
        "Set completion",
        "Target attainment",
        "Extra work",
        "Missing prescribed sets",
        "Unmatched work and data quality",
        "Prescription changes during the workout",
        "Exercise breakdown",
        "adherenceReason",
    ):
        assert text in js, text

    status, history = get(server, "/static/history.js")
    assert status == 200
    assert "renderHistoryAdherence(data.adherence)" in history
    assert history.index("renderHistoryAdherence(data.adherence)") < history.index(
        "<h3>Execution</h3>"
    )


def test_history_adherence_ui_has_accessible_status_and_table_labels(server):
    _, js = get(server, "/static/adherence.js")
    # Status is always text, so colour is not the only signal.
    for text in (
        "within target", "below target", "above target", "at target", "unavailable",
        "missing", "complete", "over prescription",
    ):
        assert text in js, text
    # Native disclosure elements and table headers keep the dense view navigable.
    assert "<details" in js and "<summary>" in js
    assert "aria-labelledby='history-adherence-title'" in js
    assert "scope='col'" in js and "scope='row'" in js
    assert "aria-label='Target attainment " in js
    assert "aria-label='Per-set targets for " in js
    assert "aria-label='Unmatched actual sets'" in js
    css = Path(__file__).resolve().parents[1] / "strength_coach" / "web" / "static" / "style.css"
    assert "focus-visible" in css.read_text(encoding="utf-8")


def test_history_adherence_ui_covers_empty_error_and_unavailable_states(server):
    _, js = get(server, "/static/adherence.js")
    for text in (
        "Adherence data is unavailable for this session.",
        "Prescription adherence is unavailable:",
        "No prescribed exercises.",
        "No attributed sets.",
        "No unmatched working sets.",
        "No known data-quality limitations.",
        "Final plan was not modified during the workout.",
        "Plan marked modified; no item-level differences remain.",
    ):
        assert text in js, text

    _, history = get(server, "/static/history.js")
    assert "Loading details…" in history
    assert "warnbox" in history and "error.message" in history


def test_history_adherence_payload_has_the_fields_the_ui_renders(server):
    plan = {
        "for_date": "2024-01-08",
        "session_type": "hinge",
        "items": [{
            "exercise_id": "trap_bar_deadlift", "sets": 2, "reps_low": 3,
            "reps_high": 5, "load_kg": 100, "rir_target": 2,
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-01-08", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    post(server, f"/api/workout/{workout_id}/plan/set-count", {
        "item_index": 0, "delta": -1,
    })
    for reps, load, rir in ((5, 100, 2), (4, 95, 3)):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": "trap_bar_deadlift", "load_kg": load,
            "reps": reps, "rir": rir,
        })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 30,
    })

    _, body = get(server, f"/api/history/{workout_id}")
    adherence = _strict_json(body)["adherence"]
    assert adherence["status"] == "available"
    for view_name in ("original", "final_plan"):
        view = adherence[view_name]
        for key in ("prescribed_sets", "performed_sets", "matched_sets", "missing_sets",
                    "extra_sets", "set_completion", "reps", "load", "rir",
                    "exercises", "quality"):
            assert key in view, (view_name, key)
        assert set(view["set_completion"]) == {"numerator", "denominator", "ratio"}
        exercise = view["exercises"][0]
        for key in ("exercise_name", "status", "prescribed_sets", "matched_sets", "sets",
                    "limitations"):
            assert key in exercise, (view_name, key)
        first = exercise["sets"][0]
        for key in ("reps_actual", "reps_target_low", "reps_target_high", "reps_status",
                    "load_target_kg", "load_actual_external_kg", "load_deviation_kg",
                    "load_status", "rir_target", "rir_actual", "rir_deviation", "rir_status",
                    "limitations", "extra", "included_in_attainment"):
            assert key in first, (view_name, key)
    assert "set_count_changed" in adherence["changes"]
    assert "unavailable_metrics" in adherence["quality"]


def _create_adherence_workout(server, day, *, sets=3, done=3,
                              exercise_id="trap_bar_deadlift", session_type="hinge"):
    plan = {
        "for_date": day,
        "session_type": session_type,
        "items": [{
            "exercise_id": exercise_id, "sets": sets, "reps_low": 3,
            "reps_high": 5, "load_kg": 100, "rir_target": 2,
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": day, "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    for _ in range(done):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": exercise_id, "load_kg": 100, "reps": 5, "rir": 2,
        })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 30,
    })
    return workout_id


def test_adherence_analytics_api_sums_numerators_and_keeps_empty_periods(server):
    _create_adherence_workout(server, "2024-02-01", sets=10, done=10)
    _create_adherence_workout(server, "2024-02-15", sets=2, done=1)

    status, body = get(
        server,
        "/api/adherence/analytics?from=2024-02-01&to=2024-02-29&group_by=week",
    )
    assert status == 200
    result = _strict_json(body)
    original = result["original"]
    assert result["status"] == "available"
    assert result["coverage"]["workouts_analysed"] == 2
    assert original["set_completion"] == {
        "numerator": 11, "denominator": 12, "ratio": 0.9167,
    }
    periods = {row["key"]: row for row in original["periods"]}
    assert periods["2024-W05"]["set_completion"]["ratio"] == 1.0
    assert periods["2024-W06"]["has_data"] is False
    assert periods["2024-W06"]["set_completion"] == {
        "numerator": 0, "denominator": 0, "ratio": None,
    }
    assert periods["2024-W07"]["set_completion"]["ratio"] == 0.5
    assert len(result["workouts"]) == 2
    assert result["workouts"][0]["for_date"] == "2024-02-15"
    assert result["workouts"][0]["original"]["set_completion"]["numerator"] == 1
    assert result["filters"]["exercises"][0]["id"] == "trap_bar_deadlift"
    assert result["filters"]["session_types"] == ["hinge"]
    assert "aggregation" in result["definitions"]


def test_adherence_analytics_api_keeps_original_and_final_distinct(server):
    plan = {
        "for_date": "2024-02-20",
        "session_type": "hinge",
        "items": [{
            "exercise_id": "trap_bar_deadlift", "sets": 5, "reps_low": 3,
            "reps_high": 5, "load_kg": 100, "rir_target": 2,
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-02-20", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    post(server, f"/api/workout/{workout_id}/plan/set-count", {
        "item_index": 0, "delta": -2,
    })
    for _ in range(3):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5, "rir": 2,
        })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 30,
    })

    _, body = get(server, "/api/adherence/analytics?from=2024-02-20&to=2024-02-20")
    result = _strict_json(body)
    assert result["original"]["set_completion"]["ratio"] == 0.6
    assert result["final_plan"]["set_completion"]["ratio"] == 1.0
    assert result["original"]["prescribed_sets"] == 5
    assert result["final_plan"]["prescribed_sets"] == 3


def test_adherence_analytics_api_filters_exercise_and_session_type(server):
    _create_adherence_workout(server, "2024-02-21", sets=2, done=2)
    _create_adherence_workout(
        server, "2024-02-22", sets=2, done=2,
        exercise_id="competition_squat", session_type="squat",
    )

    _, body = get(
        server,
        "/api/adherence/analytics?from=2024-02-01&to=2024-02-29"
        "&exercise_id=competition_squat",
    )
    squat = _strict_json(body)
    assert squat["coverage"]["workouts_analysed"] == 1
    assert squat["original"]["prescribed_sets"] == 2
    assert [row["exercise_id"] for row in squat["original"]["exercises"]] == [
        "competition_squat"
    ]

    _, body = get(
        server,
        "/api/adherence/analytics?from=2024-02-01&to=2024-02-29&session_type=squat",
    )
    filtered = _strict_json(body)
    assert filtered["coverage"]["workouts_in_range"] == 1
    assert filtered["original"]["set_completion"]["numerator"] == 2
    assert filtered["filters"]["session_types"] == ["hinge", "squat"]


def test_adherence_analytics_api_empty_range_legacy_and_validation(server):
    # The fixture's 2024-01-01 session is imported; it has no workout prescription and must not
    # be fabricated into the adherence denominator.
    _, body = get(server, "/api/adherence/analytics?from=2024-01-01&to=2024-01-01")
    legacy = _strict_json(body)
    assert legacy["coverage"]["workouts_in_range"] == 0
    assert legacy["original"]["set_completion"]["denominator"] == 0
    assert legacy["original"]["periods"][0]["set_completion"]["ratio"] is None
    assert legacy["workouts"] == []

    for query in (
        "weeks=0",
        "weeks=53",
        "group_by=day",
        "exercise_id=not_a_lift",
        "to=not-a-date",
    ):
        try:
            get(server, "/api/adherence/analytics?" + query)
        except urllib.error.HTTPError as exc:
            assert exc.code == 400, query
        else:
            raise AssertionError(f"{query} should be 400")


def test_progress_adherence_panel_is_wired_and_keeps_metrics_separate(server):
    status, page = get(server, "/")
    assert status == 200
    assert 'id="progress-adherence-panel"' in page
    assert 'id="progress-adherence-form"' in page
    assert 'id="progress-adherence-exercise"' in page
    assert 'id="progress-adherence-session-type"' in page
    assert 'id="progress-adherence-group"' in page
    assert "no composite score" in page
    assert "each with its own summed numerator and denominator" in page

    status, js = get(server, "/static/progress.js")
    assert status == 200
    for text in (
        "loadProgressAdherence",
        "/api/adherence/analytics",
        "progressAdherenceRender",
        "progressAdherenceChart",
        "dateSeriesChart",
        "data-progress-adherence-workout",
        "Definitions, coverage and exclusions",
        "Exercise comparison",
        "Workout drill-down",
        "small sample",
        "fewer than 3 workouts",
        "No completed app-tracked workouts",
        "Loading prescription adherence",
        "aria-label='Adherence by period'",
        "aria-label='Adherence comparison by exercise'",
        "aria-label='Adherence by workout'",
    ):
        assert text in js, text


def test_progress_adherence_panel_has_loading_and_error_states(server):
    _, js = get(server, "/static/progress.js")
    assert "Loading prescription adherence…" in js
    assert "Could not load" in js
    assert "warnbox" in js and "error.message" in js
    assert "No periods in this range." in js
    assert "No prescribed exercises in this range." in js
    assert "No workouts in this range." in js


def test_active_workout_exposes_vbt_target_applicability_and_feedback(server):
    plan = {
        "for_date": "2024-03-01",
        "session_type": "hinge",
        "items": [{
            "order_index": 0, "exercise_id": "trap_bar_deadlift", "sets": 2,
            "reps_low": 3, "reps_high": 5, "load_kg": 100, "load_basis": "external",
            "rir_target": 2,
            "vbt": {
                "target_mps": 0.42, "low_mps": 0.39, "high_mps": 0.45,
                "rep_count": 3, "rir_low": 2, "rir_high": 3, "scope": "lift",
                "family": "hinge", "n_sets": 18, "n_sessions": 3,
                "method_version": "1.0.0", "calibration_id": "vbt-active-test",
                "source": "computed",
            },
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-03-01", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    assert started["vbt"]["status"] == "available"
    assert started["vbt"]["quality"]["target_items"] == 1

    detail = post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 3,
        "rir": 2, "velocity": 0.44, "plan_item_index": 0,
    })["workout"]
    comparison = detail["vbt"]["sets"][0]
    assert comparison["comparable"] is True
    assert comparison["actual_velocity_mps"] == 0.44
    assert comparison["delta_mps"] == pytest.approx(0.02)
    assert comparison["delta_pct"] == pytest.approx(4.76)
    assert comparison["within_calibration_band"] is True
    assert comparison["target"]["calibration_id"] == "vbt-active-test"

    detail = post(server, f"/api/workout/{workout_id}/sets", {
        "exercise_id": "trap_bar_deadlift", "load_kg": 100, "reps": 5,
        "rir": 2, "velocity": 0.44, "plan_item_index": 0,
    })["workout"]
    latest = next(row for row in detail["vbt"]["sets"] if row["set_index"] == 2)
    assert latest["comparable"] is False
    assert "rep_mismatch" in latest["reasons"]


def test_vbt_targets_are_wired_into_prescribe_and_active_workout(server):
    status, page = get(server, "/")
    assert status == 200
    assert "/static/vbt.js" in page
    assert page.index("/static/vbt.js") < page.index("/static/app.js")
    assert page.index("/static/vbt.js") < page.index("/static/workout.js")
    assert 'id="workout-set-vbt-feedback"' in page

    _, app_js = get(server, "/static/app.js")
    assert "vbtTargetDetails(item)" in app_js
    assert "vbtPrescriptionNote(p.notes?.vbt)" in app_js

    _, workout_js = get(server, "/static/workout.js")
    assert "vbtApplicabilityHtml(" in workout_js
    assert "renderWorkoutVbtFeedback(w)" in workout_js
    assert "vbtTargetDetails(item)" in workout_js
    assert "vbtSectionHtml(w.vbt)" in workout_js

    _, history_js = get(server, "/static/history.js")
    assert "vbtSectionHtml(data.vbt)" in history_js

    _, vbt_js = get(server, "/static/vbt.js")
    for text in (
        "vbtTargetDetails", "vbtApplicability", "vbtFeedbackHtml",
        "vbtPrescriptionNote", "vbtSectionHtml", "vbt-analysis-table",
        "within calibration band", "not comparable", "VBT target", "calibration id",
    ):
        assert text in vbt_js, text

    _, css = get(server, "/static/style.css")
    assert ".vbt-details" in css
    assert ".vbt-feedback" in css
    assert ".vbt-section" in css
    assert ".vbt-analysis-table" in css


def test_completed_workout_summary_and_history_expose_vbt_target_comparison(server):
    plan = {
        "for_date": "2024-04-02",
        "session_type": "squat",
        "items": [{
            "order_index": 0, "exercise_id": "competition_squat", "sets": 3,
            "reps_low": 3, "reps_high": 5, "load_kg": 100, "load_basis": "external",
            "rir_target": 2,
            "vbt": {
                "target_mps": 0.42, "low_mps": 0.39, "high_mps": 0.45,
                "rep_count": 3, "rir_low": 2, "rir_high": 3, "scope": "lift",
                "family": "squat", "n_sets": 18, "n_sessions": 3,
                "method_version": "1.0.0", "calibration_id": "vbt-completed-test",
                "source": "computed",
            },
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-04-02", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    for reps, velocity in ((3, 0.44), (3, 0.40), (5, 0.44)):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": "competition_squat", "load_kg": 100, "reps": reps,
            "rir": 2, "velocity": velocity, "plan_item_index": 0,
        })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 45, "productivity": 4,
    })

    detail = _strict_json(get(server, f"/api/workout/{workout_id}")[1])["workout"]
    vbt = detail["vbt"]
    assert vbt["status"] == "available"
    assert vbt["quality"]["target_sets"] == 3
    assert vbt["quality"]["comparable_sets"] == 2
    assert vbt["quality"]["excluded_sets"] == 1
    assert vbt["sets"][0]["target_mps"] == 0.42
    assert vbt["sets"][0]["actual_velocity_mps"] == 0.44
    assert vbt["sets"][0]["delta_mps"] == 0.02
    assert vbt["sets"][0]["within_calibration_band"] is True
    assert vbt["sets"][2]["reasons"] == ["rep_mismatch"]
    exercise = vbt["exercises"][0]
    assert exercise["comparable_sets"] == 2
    assert exercise["median_signed_delta_mps"] == 0.0
    assert exercise["mean_absolute_error_mps"] == 0.02
    assert exercise["within_calibration_band"]["ratio"] == 1.0
    assert exercise["target"]["calibration_id"] == "vbt-completed-test"

    summary = _strict_json(get(server, f"/api/workout/{workout_id}/summary")[1])["summary"]
    assert summary["vbt"]["quality"]["comparable_sets"] == 2
    assert summary["vbt"]["exercises"][0]["target"]["calibration_id"] == "vbt-completed-test"

    detail = _strict_json(get(server, f"/api/history/{workout_id}")[1])
    assert detail["vbt"]["status"] == "available"
    assert detail["vbt"]["quality"]["comparable_sets"] == 2
    assert detail["vbt"]["exercises"][0]["sets"] == 3

    set_id = detail["vbt"]["sets"][0]["set_id"]
    post(server, f"/api/history/{workout_id}/vbt", {
        "sets": [{"set_id": set_id, "mean": 0.46}],
    })
    overridden = _strict_json(get(server, f"/api/history/{workout_id}")[1])["vbt"]
    first = next(row for row in overridden["sets"] if row["set_id"] == set_id)
    assert first["actual_velocity_mps"] == 0.46
    assert first["velocity_source"] == "override"
    assert first["delta_mps"] == 0.04


def test_performance_vbt_analysis_exposes_longitudinal_cohorts_and_drift(server):
    plan = {
        "for_date": "2024-04-15",
        "session_type": "squat",
        "items": [{
            "order_index": 0, "exercise_id": "competition_squat", "sets": 5,
            "reps_low": 3, "reps_high": 5, "load_kg": 100, "load_basis": "external",
            "rir_target": 2,
            "vbt": {
                "target_mps": 0.42, "low_mps": 0.39, "high_mps": 0.45,
                "rep_count": 3, "rir_low": 2, "rir_high": 3, "scope": "lift",
                "family": "squat", "n_sets": 18, "n_sessions": 3,
                "method_version": "1.0.0", "calibration_id": "vbt-perf-test",
                "source": "computed",
            },
        }],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-04-15", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    for index in range(5):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": "competition_squat", "load_kg": 100, "reps": 3, "rir": 2,
            "velocity": 0.43 - index * 0.005, "plan_item_index": 0,
            "rep_velocities": [
                {"rep_index": 1, "velocity_mps": 0.50 - index * 0.005},
                {"rep_index": 2, "velocity_mps": 0.47 - index * 0.005},
                {"rep_index": 3, "velocity_mps": 0.44 - index * 0.005},
            ],
        })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 45, "productivity": 4,
    })

    data = _strict_json(get(
        server, "/api/performance/vbt?from=2024-04-01&to=2024-04-30",
    )[1])
    assert data["summary"]["target_sets"] == 5
    assert data["summary"]["comparable_sets"] == 5
    assert data["summary"]["cohorts"] == 1
    assert data["summary"]["scopes"] == {"lift": 1}
    assert data["summary"]["evaluation_ready"] is False
    assert len(data["weekly"]) == 1
    cohort = data["cohorts"][0]
    assert cohort["scope"] == "lift"
    assert cohort["n"] == 5
    assert cohort["gate"] == "signal"
    assert cohort["within_calibration_band"]["numerator"] == 5
    assert cohort["band_evidence"]["within_band"] == 5
    assert cohort["rir"]["sets_with_rir"] == 5
    assert cohort["bootstrap_mean_ci"]["low"] <= cohort["mean_residual_mps"] <= cohort["bootstrap_mean_ci"]["high"]
    assert data["drift"]["n_sets"] == 5
    assert data["drift"]["n_exercises"] == 1
    drift = data["drift"]["exercises"][0]
    assert drift["n_reps"] == 15
    assert drift["gate"] == "insufficient"
    assert drift["consecutive_weeks"] == 1
    assert drift["median_loss_pct"] is not None

    filtered = _strict_json(get(
        server, "/api/performance/vbt?from=2024-04-01&to=2024-04-30&exercise_id=competition_squat",
    )[1])
    assert filtered["summary"]["target_sets"] == 5
    other = _strict_json(get(
        server, "/api/performance/vbt?from=2024-04-01&to=2024-04-30&exercise_id=competition_bench_press",
    )[1])
    assert other["summary"]["target_sets"] == 0


def test_performance_vbt_keeps_lift_and_family_cohorts_separate(server):
    def target(scope, target_mps, calibration_id):
        return {
            "target_mps": target_mps, "low_mps": 0.39, "high_mps": 0.45,
            "rep_count": 3, "rir_low": 2, "rir_high": 3, "scope": scope,
            "family": "squat", "n_sets": 18, "n_sessions": 3,
            "method_version": "1.0.0", "calibration_id": calibration_id,
            "source": "computed",
        }

    plan = {
        "for_date": "2024-05-06", "session_type": "squat",
        "items": [
            {"order_index": 0, "exercise_id": "competition_squat", "sets": 1,
             "reps_low": 3, "reps_high": 5, "load_kg": 100, "load_basis": "external",
             "rir_target": 2, "vbt": target("lift", 0.42, "vbt-lift")},
            {"order_index": 1, "exercise_id": "ssb_squat", "sets": 1,
             "reps_low": 3, "reps_high": 5, "load_kg": 90, "load_basis": "external",
             "rir_target": 2, "vbt": target("family", 0.40, "vbt-family")},
        ],
    }
    started = post(server, "/api/workout/start", {
        "date": "2024-05-06", "plan": plan, "readiness": _adherence_readiness(),
    })["workout"]
    workout_id = started["workout_id"]
    for index, exercise_id in enumerate(("competition_squat", "ssb_squat")):
        post(server, f"/api/workout/{workout_id}/sets", {
            "exercise_id": exercise_id, "load_kg": 100 if index == 0 else 90,
            "reps": 3, "rir": 2, "velocity": 0.43, "plan_item_index": index,
        })
    post(server, f"/api/workout/{workout_id}/end", {
        "session_rpe": 7, "duration_min": 30,
    })

    data = _strict_json(get(
        server, "/api/performance/vbt?from=2024-05-01&to=2024-05-31",
    )[1])
    assert data["summary"]["scopes"] == {"family": 1, "lift": 1}
    assert data["summary"]["cohorts"] == 2
    assert {cohort["scope"] for cohort in data["cohorts"]} == {"family", "lift"}
    assert {cohort["gate"] for cohort in data["cohorts"]} == {"insufficient"}
    assert all(cohort["n"] == 1 for cohort in data["cohorts"])
    # Multiple cohorts must not be averaged into a panel-level weekly series.
    assert data["weekly"] == []
    assert all(len(cohort["weekly"]) == 1 for cohort in data["cohorts"])


def test_performance_vbt_panel_is_wired_to_the_read_only_endpoint(server):
    status, page = get(server, "/")
    assert status == 200
    assert 'id="vbt-performance-panel"' in page
    assert 'id="vbt-performance-form"' in page
    assert 'id="vbt-performance-result"' in page
    assert "/static/performance.js" in page

    _, performance_js = get(server, "/static/performance.js")
    for text in (
        "/api/performance/vbt", "renderVbtPerformance", "loadVbtPerformance",
        "vbtPerformanceDrift", "vbtPerformanceWeekly", "vbtPerformanceSetTable",
        "No cross-exercise score", "No trend is fitted",
    ):
        assert text in performance_js, text

    _, css = get(server, "/static/style.css")
    assert ".vbt-performance-table" in css
    assert ".vbt-performance-summary" in css
