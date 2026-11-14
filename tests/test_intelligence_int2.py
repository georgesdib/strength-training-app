"""INT-2 catalogue: owner composition, validation, privacy and MCP exposure."""

from __future__ import annotations

import datetime as dt

import pytest
from conftest import make_readiness, make_training
from intelligence_support import service

from strength_coach import workout
from strength_coach.features import strength_trend
from strength_coach.intelligence import INTERNAL_PRINCIPAL
from strength_coach.store import db, importer, repositories


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(8):
        day = (dt.date(2026, 9, 7) + dt.timedelta(days=7 * index)).isoformat()
        rows.append({"Date": day, "Exercise": "Trap Bar Deadlift",
                     "Weight_Used": str(140 + index * 5), "RIR": "2", "Reps_Done": "5"})
        rows.append({"Date": day, "Exercise": "Competition Bench Press",
                     "Weight_Used": str(90 + index * 2), "RIR": "2", "Reps_Done": "5"})
    return rows


def _seed(conn) -> None:
    training = make_training(_rows())
    readiness = make_readiness([
        {"Date": (dt.date(2026, 9, 7) + dt.timedelta(days=7 * i)).isoformat(),
         "Sleep": "4", "Soreness": "2", "Stress": "2", "HRV": "60", "RHR": "50"}
        for i in range(8)
    ])
    importer.import_export(
        conn, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    repositories.append_athlete_profile(
        conn, effective_from="2026-01-01", sessions_per_week_target=3
    )


def _store_plan(conn) -> str:
    run = repositories.start_run(
        conn, input_hash="test", code_version="test", window_end="2026-11-02"
    )
    prescription_id = "test-prescription"
    repositories.append_prescription(
        conn,
        prescription_id=prescription_id,
        run_id=run.run_id,
        for_date="2026-11-02",
        session_type="hinge",
        fallback_level="full",
        rule_document_version="test",
        calibration_ids=(),
        approved_by="deterministic",
        items=[{
            "order_index": 0,
            "exercise_id": "trap_bar_deadlift",
            "sets": 2,
            "reps_low": 3,
            "reps_high": 5,
            "load_kg": 100.0,
            "load_basis": "percent_e1rm",
            "rounding_increment": 2.5,
            "rir_target": 2,
            "essential": True,
            "rationale_refs": ["PRG-RIR-001", "DEC-LLM-06"],
        }],
    )
    repositories.append_prescription_modifier(
        conn, prescription_id=prescription_id, modifier_key="deload_split",
        applied_on="2026-11-02", detail={"reason": "scheduled"},
    )
    return prescription_id


@pytest.fixture()
def conn():
    store = db.Store(":memory:")
    _seed(store.connection)
    try:
        yield store.connection
    finally:
        store.close()


def _run(conn, name: str, **arguments):
    return service(conn).execute(INTERNAL_PRINCIPAL, name, arguments)


def test_progression_composes_the_owner_series(conn):
    result = _run(conn, "get_exercise_progression", exercise_id="trap_bar_deadlift",
                  as_of="2026-11-14", window_days=120)
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "ok"
    assert set(env.facts) == {"exercise", "series", "summary"}
    start = (dt.date(2026, 11, 14) - dt.timedelta(days=119)).isoformat()
    direct = strength_trend.summarize(
        strength_trend.observations(conn, "trap_bar_deadlift", start, "2026-11-14")
    )
    assert env.facts["summary"].value == direct
    assert env.facts["series"].n == direct["n"]
    assert env.facts["exercise"].value["display"]


def test_progression_unknown_exercise_and_ranges(conn):
    assert _run(conn, "get_exercise_progression",
                exercise_id="not_a_lift").error.code == "not_found"
    assert _run(conn, "get_exercise_progression", exercise_id="trap_bar_deadlift",
                window_days=27).error.field == "window_days"
    assert _run(conn, "get_exercise_progression", exercise_id="trap_bar_deadlift",
                window_days=366).error.field == "window_days"
    assert _run(conn, "get_exercise_progression", exercise_id="trap_bar_deadlift",
                as_of="2999-01-01").error.field == "as_of"


def test_readiness_defaults_to_score_and_names_raw_fields(conn):
    score = _run(conn, "get_readiness_history", **{"from": "2026-09-01", "to": "2026-11-14"})
    assert score.ok, score.error
    assert set(score.envelope.facts) == {"score_series"}
    assert score.envelope.privacy.classification == "health"
    assert score.envelope.coverage["observed_days"] == 8

    raw = _run(conn, "get_readiness_history", **{
        "from": "2026-09-01", "to": "2026-11-14", "fields": ["sleep", "hrv_ms"],
    })
    assert raw.ok
    assert set(raw.envelope.facts) == {"readiness"}
    assert all("sleep" in point for point in raw.envelope.facts["readiness"].value)


def test_readiness_validation(conn):
    assert _run(conn, "get_readiness_history", **{
        "from": "2026-09-01", "to": "2026-11-14", "fields": ["injuries"],
    }).error.field == "fields"
    assert _run(conn, "get_readiness_history", **{
        "from": "2026-11-14", "to": "2026-09-01",
    }).error.field == "from"
    assert _run(conn, "get_readiness_history", **{
        "from": "2025-01-01", "to": "2026-11-14",
    }).error.field == "from"


PLAN = {
    "for_date": "2026-11-02",
    "session_type": "hinge",
    "items": [{"exercise_id": "trap_bar_deadlift", "sets": 2, "reps_low": 3,
               "reps_high": 5, "load_kg": 100, "rir_target": 2}],
}
READINESS_TODAY = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}


def _completed_workout(conn) -> str:
    started = workout.start(conn, for_date="2026-11-02", plan=PLAN,
                            readiness=READINESS_TODAY)
    workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                    load_kg=100, reps=5, rir=2)
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=50)
    return started["workout_id"]


def test_adherence_reports_totals_periods_and_coverage(conn):
    _completed_workout(conn)
    result = _run(conn, "get_adherence_analysis", weeks=8, as_of="2026-11-14")
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "ok"
    assert {"adherence", "totals", "periods", "exercises", "coverage"} <= set(env.facts)
    assert env.facts["totals"].value["workouts"] >= 0
    ranged = _run(conn, "get_adherence_analysis", **{
        "from": "2026-09-01", "to": "2026-11-14",
    })
    assert ranged.ok
    conflict = _run(conn, "get_adherence_analysis", **{
        "from": "2026-09-01", "to": "2026-11-14", "weeks": 4,
    })
    assert conflict.error.field == "weeks"


def test_prescription_no_data_then_persisted_detail(conn):
    empty = _run(conn, "get_prescription")
    assert empty.ok and empty.envelope.status == "no_data"
    assert empty.envelope.facts == {}

    prescription_id = _store_plan(conn)
    result = _run(conn, "get_prescription", prescription_id=prescription_id)
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "ok"
    assert env.facts["prescription"].value["prescription_id"] == prescription_id
    assert env.facts["items"].value[0]["exercise_id"] == "trap_bar_deadlift"
    assert env.facts["modifiers"].value[0]["modifier_key"] == "deload_split"
    assert "PRG-RIR-001" in env.facts["rule_refs"].value

    no_refs = _run(conn, "get_prescription", prescription_id=prescription_id,
                   include_provenance=False)
    assert "rule_refs" not in no_refs.envelope.facts
    assert "rationale_refs" not in no_refs.envelope.facts["items"].value[0]


def test_prescription_validation(conn):
    both = _run(conn, "get_prescription", prescription_id="a", for_date="2026-11-02")
    assert both.error.field == "prescription_id"
    assert _run(conn, "get_prescription",
                for_date="02/11/2026").error.field == "for_date"
    assert _run(conn, "get_prescription", bogus=1).error.field == "bogus"


def test_vbt_without_data_reports_abstention(conn):
    result = _run(conn, "get_vbt_analysis", **{"from": "2026-09-01", "to": "2026-11-14"})
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "no_data"
    assert env.missing and "VBT target" in env.missing[0]
    assert {"summary", "gates", "cohorts", "weekly", "drift"} <= set(env.facts)


def test_programme_block_is_a_derived_window(conn):
    result = _run(conn, "get_programme_block_summary", as_of="2026-11-14", block_weeks=4)
    assert result.ok, result.error
    env = result.envelope
    assert env.status == "ok"
    assert env.facts["window"].value["weeks"] == 4
    assert "no stored training block" in " ".join(env.limitations).lower()
    assert _run(conn, "get_programme_block_summary",
                block_weeks=5).error.field == "block_weeks"


def test_compare_attendance_and_strength_direction(conn):
    attendance = _run(conn, "compare_training_periods", **{
        "period_a": {"start": "2026-09-01", "end": "2026-10-01"},
        "period_b": {"start": "2026-10-02", "end": "2026-11-14"},
        "metric": "attendance",
    })
    assert attendance.ok, attendance.error
    comparison = attendance.envelope.facts["comparison"].value
    assert comparison["metric"] == "attendance"
    assert comparison["delta"]["absolute"] is not None

    strength = _run(conn, "compare_training_periods", **{
        "period_a": {"start": "2026-09-01", "end": "2026-10-01"},
        "period_b": {"start": "2026-10-02", "end": "2026-11-14"},
        "metric": "strength_direction", "exercise_id": "trap_bar_deadlift",
    })
    assert strength.ok, strength.error
    assert strength.envelope.facts["comparison"].value["period_a"]["primary"] is not None

    missing_exercise = _run(conn, "compare_training_periods", **{
        "period_a": {"start": "2026-09-01", "end": "2026-10-01"},
        "period_b": {"start": "2026-10-02", "end": "2026-11-14"},
        "metric": "strength_direction",
    })
    assert missing_exercise.error.field == "exercise_id"
    assert _run(conn, "compare_training_periods", **{
        "period_a": {"start": "2026-09-01", "end": "2026-10-01"},
        "period_b": {"start": "2026-10-02", "end": "2026-11-14"},
        "metric": "sleep",
    }).error.field == "metric"


def test_catalogue_is_read_only(conn):
    tables = ("session", "clean_set", "workout_session", "prescription",
              "prescription_item", "readiness_day")
    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    changes = conn.total_changes
    for name, arguments in (
        ("get_exercise_progression", {"exercise_id": "trap_bar_deadlift"}),
        ("get_readiness_history", {"from": "2026-09-01", "to": "2026-11-14"}),
        ("get_adherence_analysis", {"weeks": 8}),
        ("get_prescription", {}),
        ("get_vbt_analysis", {"from": "2026-09-01", "to": "2026-11-14"}),
        ("get_programme_block_summary", {}),
        ("compare_training_periods", {
            "period_a": {"start": "2026-09-01", "end": "2026-10-01"},
            "period_b": {"start": "2026-10-02", "end": "2026-11-14"},
            "metric": "attendance",
        }),
    ):
        assert _run(conn, name, **arguments).ok, name
    assert conn.total_changes == changes
    assert {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables} == before


def test_progression_sessions_respect_the_window(conn):
    extra = make_training([
        {"Date": "2026-07-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "135",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2026-11-10", "Exercise": "Trap Bar Deadlift", "Weight_Used": "170",
         "RIR": "2", "Reps_Done": "5"},
    ])
    readiness = make_readiness([{}])
    importer.import_export(
        conn, extra, readiness,
        training_sha256=importer.sha256_frame(extra),
        readiness_sha256=importer.sha256_frame(readiness),
    )

    as_of = "2026-10-20"
    window_days = 60
    window_start = (dt.date(2026, 10, 20) - dt.timedelta(days=window_days - 1)).isoformat()
    result = _run(conn, "get_exercise_progression", exercise_id="trap_bar_deadlift",
                  as_of=as_of, window_days=window_days, include_sessions=True,
                  limit_sessions=20)
    assert result.ok, result.error
    env = result.envelope
    sessions = env.facts["sessions"].value
    dates = [session["occurred_on"] for session in sessions]

    assert dates, "the seeded window contains sessions"
    assert all(window_start <= day <= as_of for day in dates), dates
    assert "2026-07-01" not in dates, "a session before the window must be excluded"
    assert "2026-10-26" not in dates, "a session after as_of must be excluded"
    assert "2026-11-10" not in dates, "a session after as_of must be excluded"
    assert "2026-09-07" in dates and "2026-10-19" in dates

    observation_dates = [
        point["date"] for point in env.facts["series"].value["observations"]
    ]
    assert all(window_start <= day <= as_of for day in observation_dates)
    assert dates == sorted(dates, reverse=True), "sessions stay newest-first"

    without = _run(conn, "get_exercise_progression", exercise_id="trap_bar_deadlift",
                   as_of=as_of, window_days=window_days, include_sessions=False)
    assert "sessions" not in without.envelope.facts
