"""The weekly review: composition, golden fixture, boundaries, empty week and REST route."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from conftest import make_readiness, make_training
from intelligence_support import enabled_config, service

from strength_coach import workout
from strength_coach.intelligence import INTERNAL_PRINCIPAL
from strength_coach.intelligence import api as intelligence_api
from strength_coach.intelligence.reports import weekly_review
from strength_coach.store import db, importer, ios_devices, repositories
from strength_coach.web.server import create_server

FIXTURE = Path(__file__).parent / "fixtures" / "intelligence" / "weekly_review.ok.json"
WEEK_END = "2026-11-08"
FIXTURE_DAYS = (
    "2026-09-28", "2026-10-05", "2026-10-12",
    "2026-10-19", "2026-10-26", "2026-11-02",
)

PLAN = {
    "for_date": "2026-11-04",
    "session_type": "hinge",
    "items": [{"exercise_id": "trap_bar_deadlift", "sets": 2, "reps_low": 3,
               "reps_high": 5, "load_kg": 100, "rir_target": 2}],
}
READINESS_TODAY = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}


def seed(conn, *, workout_day: str | None = "2026-11-04") -> None:
    rows = []
    for index, day in enumerate(FIXTURE_DAYS):
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
    importer.import_export(
        conn, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_athlete_profile(
        conn, effective_from="2026-01-01", sessions_per_week_target=3
    )
    if workout_day is not None:
        plan = dict(PLAN)
        plan["for_date"] = workout_day
        started = workout.start(conn, for_date=workout_day, plan=plan,
                                readiness=READINESS_TODAY)
        workout.add_set(conn, started["workout_id"],
                        exercise_id="trap_bar_deadlift", load_kg=100, reps=5, rir=2)
        workout.end(conn, started["workout_id"], session_rpe=7, duration_min=50)


@pytest.fixture()
def conn():
    store = db.Store(":memory:")
    seed(store.connection)
    try:
        yield store.connection
    finally:
        store.close()


def _normalise(facts: dict) -> dict:
    """Drop the one volatile value: a workout's generated session id."""
    cleaned = json.loads(json.dumps(facts))
    for row in cleaned.get("sessions", {}).get("value") or []:
        row.pop("session_id", None)
    return cleaned


def _run(conn, **arguments):
    return service(conn).execute(INTERNAL_PRINCIPAL, "get_weekly_review", arguments)


def test_weekly_review_matches_the_golden_fixture(conn):
    result = _run(conn, week_end=WEEK_END)
    assert result.ok, result.error
    env = result.envelope
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert env.status == expected["status"]
    assert env.period.start == expected["period"]["start"]
    assert env.period.end == expected["period"]["end"]
    facts = _normalise(env.as_dict()["facts"])
    assert facts == _normalise(expected["facts"])
    assert env.coverage == expected["coverage"]
    assert list(env.missing) == expected["missing"]
    assert list(env.quality_flags) == expected["quality_flags"]

    assert env.facts["activity"].value["completed_sessions"] == 2
    assert env.facts["activity"].value["target_sessions"] == 3
    assert env.facts["readiness"].value["observed_days"] == 4
    assert {row["exercise_id"] for row in env.facts["progression"].value} == {
        "trap_bar_deadlift", "bench_press"
    }


def test_week_boundary_is_monday_to_sunday(conn):
    sunday = _run(conn, week_end="2026-11-08")
    wednesday = _run(conn, week_end="2026-11-04")
    monday = _run(conn, week_end="2026-11-02")
    assert sunday.ok and wednesday.ok and monday.ok
    for result in (sunday, wednesday, monday):
        assert result.envelope.period.start == "2026-11-02"
        assert result.envelope.period.end == "2026-11-08"
    assert sunday.envelope.facts == wednesday.envelope.facts == monday.envelope.facts


def test_default_week_is_the_last_completed_week(conn):
    result = service(conn).execute(INTERNAL_PRINCIPAL, "get_weekly_review", {})
    assert result.ok, result.error
    assert result.envelope.period.start == "2026-11-02"
    assert result.envelope.period.end == "2026-11-08"


def test_empty_week_is_no_data_and_never_zeros(conn):
    result = _run(conn, week_end="2025-06-08")
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "no_data"
    assert "no completed session in the week" in env.missing
    assert env.facts["activity"].value["completed_sessions"] == 0
    assert env.facts["sessions"].value == []
    assert env.facts["readiness"].value["direction"] == "unknown"


def test_imported_only_week_reports_quality_flags(tmp_path):
    store = db.Store(tmp_path / "imported.db")
    seed(store.connection, workout_day=None)
    try:
        report = weekly_review.build(store.connection, week_end=dt.date(2026, 11, 8))
        assert report.status == "ok"
        assert "imported_sessions_only" in report.quality_flags
        assert "adherence_unavailable" in report.quality_flags
        assert report.sections["adherence"].value["available"] is False
    finally:
        store.close()


def test_observations_can_be_omitted(conn):
    with_observations = _run(conn, week_end=WEEK_END)
    without = _run(conn, week_end=WEEK_END, include_observations=False)
    assert without.ok
    assert without.envelope.observations == ()
    assert "no observation passed its evidence gate" not in without.envelope.missing
    assert with_observations.envelope.facts == without.envelope.facts


def test_weekly_review_is_read_only(conn):
    tables = ("session", "clean_set", "workout_session", "readiness_day", "observation")
    before = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    changes = conn.total_changes
    assert _run(conn, week_end=WEEK_END).ok
    assert conn.total_changes == changes
    assert {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables} == before


# --- REST route -------------------------------------------------------------


def _request(base, path, *, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture()
def weekly_server(tmp_path, monkeypatch):
    monkeypatch.setattr(
        intelligence_api, "load_config", lambda path=None: enabled_config()
    )
    path = tmp_path / "coach.db"
    store = db.Store(path)
    seed(store.connection)
    store.close()
    httpd = create_server(path, "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        store = db.Store(path)
        minted = ios_devices.mint_pairing_code(store.connection)
        store.close()
        # Pairing needs a POST; use urllib directly.
        payload = json.dumps({"code": minted["code"]}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/ios/v1/pair",
            data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            token = json.loads(response.read().decode("utf-8"))["token"]
        yield {"base": f"http://127.0.0.1:{httpd.server_address[1]}", "token": token}
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_rest_route_returns_the_envelope(weekly_server):
    status, body = _request(
        weekly_server["base"],
        "/api/ios/v1/intelligence/weekly-review?week_end=2026-11-08",
        token=weekly_server["token"],
    )
    assert status == 200, body
    assert body["schema_version"] == "intelligence.envelope.v1"
    assert body["capability"] == "get_weekly_review"
    assert body["status"] == "ok"
    assert body["period"]["start"] == "2026-11-02"
    assert body["period"]["end"] == "2026-11-08"
    assert body["period"]["days"] == 7
    assert body["period"]["weeks"] == 1
    assert body["period"]["timezone"]


def test_rest_route_requires_authentication(weekly_server):
    status, body = _request(
        weekly_server["base"], "/api/ios/v1/intelligence/weekly-review"
    )
    assert status == 401
    assert "error" in body


def test_rest_route_maps_validation_errors(weekly_server):
    status, body = _request(
        weekly_server["base"],
        "/api/ios/v1/intelligence/weekly-review?week_end=2026-11-08&bogus=1",
        token=weekly_server["token"],
    )
    assert status == 400
    assert "unknown query parameter" in body["error"]


def test_bootstrap_advertises_the_read_route(weekly_server):
    status, body = _request(
        weekly_server["base"], "/api/ios/v1/bootstrap", token=weekly_server["token"]
    )
    assert status == 200
    assert body["capabilities"]["intelligence_read"] is True


def test_weekly_review_via_mcp_matches_the_service(tmp_path):
    pytest.importorskip("mcp", reason="optional intelligence MCP extra")
    from mcp import Client

    from strength_coach.intelligence.mcp.app import build_server
    from strength_coach.intelligence.mcp.security import authenticated

    path = tmp_path / "coach.db"
    store = db.Store(path)
    seed(store.connection)
    store.close()

    async def call():
        async with Client(build_server(db_path=path, config=enabled_config())) as client:
            with authenticated(INTERNAL_PRINCIPAL):
                return await client.call_tool("get_weekly_review", {"week_end": WEEK_END})

    result = asyncio.run(call())
    assert result.is_error is False
    store = db.Store(path)
    try:
        direct = service(store.connection).execute(
            INTERNAL_PRINCIPAL, "get_weekly_review", {"week_end": WEEK_END}
        )
    finally:
        store.close()
    assert _normalise(result.structured_content["facts"]) == _normalise(
        direct.envelope.as_dict()["facts"]
    )


class _FakeAssessment:
    def __init__(self, score, category_scores):
        self._payload = {
            "score": score,
            "category_scores": category_scores,
            "status": "ready",
            "basis": "test",
        }

    def as_dict(self):
        return self._payload


def _direction_with(conn, monkeypatch, scores):
    from strength_coach.features import readiness_score

    mapping = {
        day: _FakeAssessment(score, {"a": mirror, "b": mirror})
        for day, (score, mirror) in scores.items()
    }
    monkeypatch.setattr(
        readiness_score, "compute", lambda _conn, day: mapping[day]
    )
    result = _run(conn, week_end=WEEK_END)
    assert result.ok, result.error
    return result.envelope.facts["readiness"]


def test_readiness_direction_uses_the_canonical_score(conn, monkeypatch):
    # The category mean rises (0.4 -> 0.7) while the canonical score falls (0.8 -> 0.6).
    fact = _direction_with(conn, monkeypatch, {
        "2026-11-02": (0.80, 0.4),
        "2026-11-04": (0.75, 0.5),
        "2026-11-06": (0.70, 0.6),
        "2026-11-08": (0.60, 0.7),
    })
    assert fact.value["direction"] == "down"
    assert fact.value["observed_days"] == 4
    assert set(fact.value) == {"observed_days", "direction", "first_date", "last_date"}


def test_readiness_direction_has_no_invented_threshold(conn, monkeypatch):
    # A small canonical change still has a direction; the old 0.05 rule would say "flat".
    fact = _direction_with(conn, monkeypatch, {
        "2026-11-02": (0.700, 0.70),
        "2026-11-04": (0.700, 0.70),
        "2026-11-06": (0.700, 0.70),
        "2026-11-08": (0.705, 0.70),
    })
    assert fact.value["direction"] == "up"
