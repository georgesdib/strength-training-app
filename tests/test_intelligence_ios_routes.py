"""iOS intelligence routes: overview, progression, readiness and session details."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from conftest import make_readiness, make_training
from intelligence_support import enabled_config

from strength_coach import workout
from strength_coach.intelligence import api as intelligence_api
from strength_coach.store import db, importer, ios_devices, repositories
from strength_coach.web.server import create_server

DAYS = ("2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02")
PLAN = {
    "for_date": "2026-11-04",
    "session_type": "hinge",
    "items": [{"exercise_id": "trap_bar_deadlift", "sets": 2, "reps_low": 3,
               "reps_high": 5, "load_kg": 100, "rir_target": 2}],
}
READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}


def _seed(path: Path) -> str:
    store = db.Store(path)
    conn = store.connection
    rows = []
    for index, day in enumerate(DAYS):
        rows.append({"Date": day, "Exercise": "Trap Bar Deadlift",
                     "Weight_Used": str(150 + index * 2), "RIR": "2", "Reps_Done": "5"})
        rows.append({"Date": day, "Exercise": "Competition Bench Press",
                     "Weight_Used": str(95 + index), "RIR": "2", "Reps_Done": "5"})
    training = make_training(rows)
    readiness = make_readiness([
        {"Date": day, "Sleep": "4", "Soreness": "2", "Stress": "2",
         "HRV": "60", "RHR": "50"}
        for day in ("2026-11-02", "2026-11-04", "2026-11-06", "2026-11-08")
    ])
    try:
        importer.import_export(
            conn, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        repositories.append_athlete_profile(
            conn, effective_from="2026-01-01", sessions_per_week_target=3
        )
        started = workout.start(conn, for_date="2026-11-04", plan=PLAN, readiness=READINESS)
        workout.add_set(conn, started["workout_id"],
                        exercise_id="trap_bar_deadlift", load_kg=100, reps=5, rir=2)
        workout.end(conn, started["workout_id"], session_rpe=7, duration_min=50)
        return started["workout_id"]
    finally:
        store.close()


@pytest.fixture()
def ios(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        intelligence_api, "load_config", lambda path=None: enabled_config()
    )
    path = tmp_path / "coach.db"
    workout_id = _seed(path)
    httpd = create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        store = db.Store(path)
        minted = ios_devices.mint_pairing_code(store.connection)
        store.close()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        payload = json.dumps({"code": minted["code"], "label": "route probe"}).encode()
        request = urllib.request.Request(
            base + "/api/ios/v1/pair", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            token = json.loads(response.read().decode())["token"]
        yield {"base": base, "token": token, "path": path, "workout_id": workout_id}
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _get(ios, path: str, *, authenticated: bool = True):
    headers = {"Authorization": f"Bearer {ios['token']}"} if authenticated else {}
    request = urllib.request.Request(ios["base"] + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def test_overview_route(ios):
    status, body = _get(ios, "/api/ios/v1/intelligence/overview?window_weeks=4")
    assert status == 200, body
    assert body["capability"] == "get_training_overview"
    assert body["status"] in ("ok", "no_data")


def test_progression_route(ios):
    status, body = _get(
        ios,
        "/api/ios/v1/intelligence/exercises/trap_bar_deadlift/progression"
        "?window_days=120&include_sessions=true",
    )
    assert status == 200, body
    assert body["capability"] == "get_exercise_progression"
    assert "series" in body["facts"]
    assert body["facts"]["sessions"]["value"]


def test_readiness_route_allows_named_fields_for_the_app(ios):
    status, body = _get(
        ios,
        "/api/ios/v1/intelligence/readiness"
        "?from=2026-09-01&to=2026-11-14&fields=sleep,hrv_ms",
    )
    assert status == 200, body
    assert body["capability"] == "get_readiness_history"
    assert "readiness" in body["facts"]
    point = body["facts"]["readiness"]["value"][0]
    assert "sleep" in point and "hrv_ms" in point


def test_readiness_route_defaults_to_score(ios):
    status, body = _get(
        ios, "/api/ios/v1/intelligence/readiness?from=2026-09-01&to=2026-11-14"
    )
    assert status == 200, body
    assert set(body["facts"]) == {"score_series"}


def test_session_details_route(ios):
    status, body = _get(
        ios,
        f"/api/ios/v1/intelligence/session-details?workout_id={ios['workout_id']}",
    )
    assert status == 200, body
    assert body["capability"] == "get_session_details"


def test_routes_require_authentication(ios):
    status, body = _get(ios, "/api/ios/v1/intelligence/overview", authenticated=False)
    assert status == 401


def test_route_validation(ios):
    assert _get(ios, "/api/ios/v1/intelligence/overview?bogus=1")[0] == 400
    assert _get(ios, "/api/ios/v1/intelligence/overview?window_weeks=abc")[0] == 400
    assert _get(
        ios, "/api/ios/v1/intelligence/exercises/not_a_lift/progression"
    )[0] == 404
    assert _get(ios, "/api/ios/v1/intelligence/session-details")[0] == 400


def test_routes_are_read_only(ios):
    store = db.Store(ios["path"])
    try:
        before = store.connection.execute("SELECT COUNT(*) FROM session").fetchone()[0]
    finally:
        store.close()
    assert _get(ios, "/api/ios/v1/intelligence/overview")[0] == 200
    store = db.Store(ios["path"])
    try:
        after = store.connection.execute("SELECT COUNT(*) FROM session").fetchone()[0]
    finally:
        store.close()
    assert after == before


def test_prescription_route(ios):
    status, body = _get(
        ios, "/api/ios/v1/intelligence/prescription?for_date=2026-11-04"
    )
    assert status == 200, body
    assert body["capability"] == "get_prescription"
    assert body["status"] in ("ok", "no_data")


def test_programme_summary_route(ios):
    status, body = _get(
        ios, "/api/ios/v1/intelligence/programme-summary?as_of=2026-11-08&block_weeks=4"
    )
    assert status == 200, body
    assert body["capability"] == "get_programme_block_summary"


def test_adherence_route(ios):
    status, body = _get(ios, "/api/ios/v1/intelligence/adherence?weeks=4&group_by=week")
    assert status == 200, body
    assert body["capability"] == "get_adherence_analysis"


def test_prescription_route_rejects_unknown_query(ios):
    status, body = _get(
        ios, "/api/ios/v1/intelligence/prescription?for_date=2026-11-04&window=1"
    )
    assert status == 400, body
