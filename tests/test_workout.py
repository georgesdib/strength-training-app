"""Live workout: required readiness, append-only sets, measured/manual end."""

from __future__ import annotations

import datetime as dt
import threading

import pytest

from strength_coach import history, workout
from strength_coach.features import residual
from strength_coach.store import db, repositories

PLAN = {
    "for_date": "2024-01-01",
    "session_type": "hinge",
    "items": [
        {"exercise_id": "trap_bar_deadlift", "sets": 5, "reps_low": 3,
         "reps_high": 5, "load_kg": 100, "rir_target": 2},
        {"exercise_id": "competition_bench_press", "sets": 3, "reps_low": 5,
         "reps_high": 5, "load_kg": 80, "rir_target": 2},
    ],
}
READINESS = {
    "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
    "nutrition": 4, "hydration": 4,
}

MINIMUM_PLAN = {
    **PLAN,
    "notes": {"minimum_session": {
        "requested": True, "applied": True, "status": "applied",
        "target_minutes": 45, "before_minutes": 58.0, "after_minutes": 44.0,
        "include_main": False, "removed_sets": 2, "removed_exercises": [],
    }},
}


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def test_a_minimum_session_reports_target_estimate_and_measured_time(conn):
    # LIM-47: the target is judged against a planning estimate, so the payload must carry both
    # that estimate and the clock, and recompute the estimate from the plan as it stands.
    started = workout.start(conn, for_date="2024-01-01", plan=MINIMUM_PLAN,
                            readiness=READINESS)
    summary = started["minimum_session"]
    assert summary["target_minutes"] == 45
    assert summary["estimated_minutes"] > 0
    assert summary["measured_minutes"] is None          # still in progress
    assert summary["status"] == "applied"

    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=58)
    summary = ended["minimum_session"]
    assert summary["measured_minutes"] == 58.0
    assert summary["duration_source"] == "manual"


def test_a_workout_note_is_readable_from_history(conn):
    # The note is provenance for a backfilled session; the detail view shows it beside the sets.
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS,
                            note="backfilled from the 9 October session CSV")
    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=40)
    assert history.detail(conn, ended["workout_id"])["workout_note"] == (
        "backfilled from the 9 October session CSV"
    )


def test_a_plan_without_a_minimum_session_has_no_summary(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    assert started["minimum_session"] is None


def test_start_accepts_an_unresolved_load_and_the_first_set_fills_it(conn):
    # A first exercise has no history: the plan carries no load, but the workout can start and
    # the actual set becomes the baseline. This is the no-history path, not a dropped item.
    plan = {
        **PLAN,
        "items": [
            {**PLAN["items"][0], "load_kg": None},
            PLAN["items"][1],
        ],
    }
    started = workout.start(conn, for_date="2024-01-01", plan=plan, readiness=READINESS)
    assert started["plan"]["items"][0]["load_kg"] is None

    updated = workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=120, reps=5, rir=2,
    )
    assert updated["sets"][0]["load_kg"] == 120


def test_start_rejects_inconsistent_set_groups_without_a_workout(conn):
    bad = {
        **PLAN,
        "items": [{
            **PLAN["items"][0],
            "sets": 5,
            "set_groups": [
                {"role": "top_set", "sets": 1, "load_kg": 110, "reps_low": 3,
                 "reps_high": 5, "rir_target": 1, "percent_of_top": None},
                {"role": "back_off", "sets": 1, "load_kg": 90, "reps_low": 3,
                 "reps_high": 5, "rir_target": 2, "percent_of_top": 0.85},
            ],
        }],
    }
    with pytest.raises(ValueError, match="must equal item.sets"):
        workout.start(conn, for_date="2024-01-01", plan=bad, readiness=READINESS)
    assert conn.execute("SELECT COUNT(*) FROM workout_session").fetchone()[0] == 0



def test_substitution_attribution_survives_materialisation(conn):
    plan = {
        **PLAN,
        "items": [{
            **PLAN["items"][0],
            "sets": 2,
            "set_groups": [
                {"group_index": 0, "sets": 1, "load_kg": 110, "reps_low": 3,
                 "reps_high": 5, "rir_target": 1},
                {"group_index": 1, "sets": 1, "load_kg": 90, "reps_low": 3,
                 "reps_high": 5, "rir_target": 2},
            ],
        }],
    }
    started = workout.start(conn, for_date="2024-01-01", plan=plan, readiness=READINESS)
    workout.add_set(
        conn, started["workout_id"], exercise_id="competition_bench_press",
        load_kg=90, reps=5, rir=2, substitutes_plan_item_index=0,
    )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)
    row = conn.execute(
        "SELECT prescription_item_index, substitutes_plan_item_index, set_role "
        "FROM clean_set ORDER BY set_id"
    ).fetchone()
    assert row["prescription_item_index"] == 0
    assert row["substitutes_plan_item_index"] == 0
    # New sets never carry a role; the legacy column stays null (DEC-RESOLVER-23).
    assert row["set_role"] is None


def test_start_requires_all_seven_readiness_fields(conn):
    with pytest.raises(ValueError, match="readiness.energy"):
        workout.start(conn, for_date="2024-01-01", plan=PLAN,
                      readiness={**READINESS, "energy": None})
    assert workout.active_workout(conn) is None


def test_start_accepts_explicitly_acknowledged_partial_readiness(conn):
    clean = workout.validate_readiness({"sleep": 2}, allow_partial=True)
    started = workout.start(
        conn, for_date="2024-01-01", plan=PLAN, readiness=clean,
        allow_partial_readiness=True,
    )
    assert started["readiness"] == {"sleep": 2.0}
    assert workout.active_workout(conn)["workout_id"] == started["workout_id"]


CORE_READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("hrv_ms", -1, "readiness.hrv_ms"),
        ("hrv_ms", 0, "readiness.hrv_ms"),
        ("rhr_bpm", -1, "readiness.rhr_bpm"),
        ("rhr_bpm", 0, "readiness.rhr_bpm"),
        ("bodyweight_kg", -1, "readiness.bodyweight_kg"),
        ("bodyweight_kg", 0, "readiness.bodyweight_kg"),
        ("wearable_score", -1, "readiness.wearable_score"),
        ("wearable_score", 101, "readiness.wearable_score"),
        ("hrv_ms", "nan", "readiness.hrv_ms"),
        ("rhr_bpm", "inf", "readiness.rhr_bpm"),
        ("bodyweight_kg", "-inf", "readiness.bodyweight_kg"),
        ("wearable_score", "nan", "readiness.wearable_score"),
    ],
)
def test_validate_readiness_rejects_invalid_optional_device_values(field, value, message):
    with pytest.raises(ValueError, match=message):
        workout.validate_readiness({**CORE_READINESS, field: value})


def test_validate_readiness_accepts_valid_optional_device_values():
    clean = workout.validate_readiness({
        **CORE_READINESS,
        "hrv_ms": 55,
        "rhr_bpm": 52,
        "bodyweight_kg": 80.5,
        "wearable_score": 0,
    })
    assert clean == {
        **CORE_READINESS,
        "hrv_ms": 55.0,
        "rhr_bpm": 52.0,
        "bodyweight_kg": 80.5,
        "wearable_score": 0.0,
    }


def test_validate_readiness_preserves_missing_optional_and_partial_fields():
    assert workout.validate_readiness(CORE_READINESS) == {
        key: float(value) for key, value in CORE_READINESS.items()
    }
    assert workout.validate_readiness({"sleep": 2}, allow_partial=True) == {"sleep": 2.0}


def test_validate_readiness_keeps_required_field_validation():
    with pytest.raises(ValueError, match="readiness.energy is required"):
        workout.validate_readiness({**CORE_READINESS, "energy": None})
    with pytest.raises(ValueError, match="readiness.sleep must be between 1 and 5"):
        workout.validate_readiness({**CORE_READINESS, "sleep": 6})


def test_start_add_remove_and_end(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    assert started["status"] == "in_progress"
    assert workout.active_workout(conn)["workout_id"] == started["workout_id"]

    with pytest.raises(ValueError, match="already in progress"):
        workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)

    added = workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                            load_kg=100, reps=5, rir=2)
    assert len(added["sets"]) == 1
    set_id = added["sets"][0]["set_id"]

    removed = workout.remove_set(conn, started["workout_id"], set_id)
    assert removed["sets"] == []

    ended = workout.end(conn, started["workout_id"], session_rpe=7,
                        duration_min=55, notes="felt good")
    assert ended["status"] == "completed"
    assert ended["duration_source"] == "manual"
    assert ended["duration_min"] == 55
    assert ended["session_rpe_recorded"] == 1
    assert workout.active_workout(conn) is None


def test_end_requires_srpe_or_explicit_not_recorded(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    with pytest.raises(ValueError, match="session_rpe"):
        workout.end(conn, started["workout_id"], session_rpe=None)
    ended = workout.end(conn, started["workout_id"], session_rpe=None, not_recorded=True)
    assert ended["session_rpe_recorded"] == 0
    assert ended["session_rpe"] is None


def test_end_materialises_session_and_comparison(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                    load_kg=100, reps=5, rir=2)
    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)

    session = conn.execute(
        "SELECT session_id, source, workout_id, prescription_id, set_count,"
        " working_set_count, session_rpe FROM session WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()
    assert session["source"] == "workout"
    assert session["workout_id"] == started["workout_id"]
    assert session["set_count"] == 1
    assert session["working_set_count"] == 1
    assert session["session_rpe"] == 7
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM clean_set WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()["c"] == 1
    assert ended["comparison"]["items"][0]["status"] == "under"
    assert ended["comparison"]["items"][1]["status"] == "missing"


def test_a_unique_exercise_is_matched_without_an_explicit_index(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    added = workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    assert added["sets"][0]["prescription_item_index"] == 0


def test_a_duplicate_exercise_is_matched_by_explicit_plan_item_index(conn):
    duplicate = {
        **PLAN,
        "items": [PLAN["items"][0], {**PLAN["items"][0], "sets": 1}],
    }
    started = workout.start(conn, for_date="2024-01-01", plan=duplicate, readiness=READINESS)
    added = workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2, plan_item_index=1,
    )
    assert added["sets"][0]["prescription_item_index"] == 1
    items = added["comparison"]["items"]
    assert items[0]["status"] == "missing"
    assert items[1]["status"] == "complete"
    assert items[1]["match_status"] == "matched"
    assert items[1]["actual_set_ids"] == [added["sets"][0]["set_id"]]


def test_a_duplicate_exercise_without_an_index_remains_ambiguous(conn):
    duplicate = {
        **PLAN,
        "items": [PLAN["items"][0], {**PLAN["items"][0], "sets": 2}],
    }
    started = workout.start(conn, for_date="2024-01-01", plan=duplicate, readiness=READINESS)
    added = workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    assert added["sets"][0]["prescription_item_index"] is None
    assert added["comparison"]["items"][0]["status"] == "missing"
    assert added["comparison"]["extra"][0]["match_status"] == "ambiguous"


def test_a_stale_plan_item_index_is_preserved_as_extra_work(conn):
    # With a frozen plan the item index cannot change, so this only covers a stale or buggy
    # client index: the set is kept and never attributed to another exercise's slot.
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    result = workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2, plan_item_index=1,
    )
    row = result["sets"][0]
    assert row["prescription_item_index"] is None
    assert row["substitutes_plan_item_index"] is None




def test_sets_and_end_preserve_explicit_local_timestamps(conn):
    import datetime as dt

    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    start = dt.datetime.fromisoformat(started["started_at"])
    performed = start + dt.timedelta(seconds=1)
    changed = workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2, set_index=1, plan_item_index=0,
        performed_at=performed.isoformat(),
    )
    assert changed["sets"][0]["created_at"].startswith(
        performed.astimezone(dt.UTC).isoformat(timespec="milliseconds")[:19]
    )

    with pytest.raises(ValueError, match="before the workout start"):
        workout.add_set(
            conn, started["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=5, rir=2, set_index=2, plan_item_index=0,
            performed_at=(start - dt.timedelta(seconds=1)).isoformat(),
        )
    with pytest.raises(ValueError, match="future"):
        workout.add_set(
            conn, started["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=5, rir=2, set_index=2, plan_item_index=0,
            performed_at=(dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)).isoformat(),
        )

    now = dt.datetime.now(dt.UTC)
    conn.execute(
        "UPDATE workout_session SET started_at = ? WHERE workout_id = ?",
        ((now - dt.timedelta(minutes=10)).isoformat(), started["workout_id"]),
    )
    with pytest.raises(ValueError, match="before the workout start"):
        workout.end(
            conn, started["workout_id"], session_rpe=7, not_recorded=False,
            ended_at=(now - dt.timedelta(minutes=20)).isoformat(),
        )
    ended = workout.end(
        conn, started["workout_id"], session_rpe=7, not_recorded=False,
        ended_at=(now - dt.timedelta(minutes=1)).isoformat(),
    )
    assert ended["duration_source"] == "measured"
    assert 8.5 <= ended["duration_min"] <= 9.5
    assert ended["ended_at"].startswith((now - dt.timedelta(minutes=1)).isoformat()[:19])






def test_weekly_residual_uses_stored_plan_item_target(conn):
    conn.execute(
        "INSERT INTO run (run_id, started_at, input_hash, code_version, status) "
        "VALUES ('run-1', '2024-01-01T00:00:00Z', 'input', 'test', 'ok')"
    )
    repositories.append_prescription(
        conn,
        prescription_id="rx-1",
        run_id="run-1",
        for_date="2024-01-01",
        session_type="hinge",
        fallback_level="full",
        rule_document_version="test",
        calibration_ids=(),
        approved_by="deterministic",
        items=[{
            "order_index": 0, "exercise_id": "trap_bar_deadlift", "sets": 1,
            "reps_low": 5, "reps_high": 5, "load_kg": 100,
            "load_basis": "external", "rounding_increment": None, "rir_target": 2,
            "velocity_target": 0.5, "vbt_basis": "lift", "essential": True,
        }],
    )
    started = workout.start(
        conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS,
        prescription_id="rx-1",
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2, velocity=0.4, plan_item_index=0,
    )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)
    weekly = residual.weekly_history(conn, "2024-01-01", "2024-01-01")
    assert weekly == [{
        "week_start": "2024-01-01", "n": 1, "mean_mps": -0.1,
        "spread_mps": None, "status": "insufficient",
    }]


def test_end_writes_no_critique(conn):
    """The rubric is retired (DEC-EVAL-09): completion must not score the session."""
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                    load_kg=100, reps=5, rir=2)
    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)
    assert not ended.get("critique_id")
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM critique WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()["c"] == 0
    assert ended["status"] == "completed"



CSV = """Exercise,Set,RPE,Value,Weight,Reps
Push Press,1,4,???,20.0kg,4
Push Press,2,5.5,0.67m/s,40.0kg,5
Push Press,3,6,0.78m/s,50.0kg,4
Bench Press (Wide-Grip),4,7,0.35m/s,100.0kg,6
Bench Press (Wide-Grip),5,7.5,0.31m/s,100.0kg,6
Bench Press (Wide-Grip),6,8,0.35m/s,100.0kg,6
"""


def test_parse_import_maps_exercises_rpe_and_missing_velocity():
    preview = workout.parse_import(CSV)
    assert preview["errors"] == []
    rows = preview["rows"]
    assert rows[0]["exercise_id"] == "push_press"
    assert rows[0]["rir"] == 6 and rows[0]["warmup"] is True
    assert rows[1]["rir"] == 4 and rows[0]["velocity_mps"] is None
    # DEC-VARIANT-06: the wide-grip spelling is the bench press.
    assert rows[3]["exercise_id"] == "bench_press"
    assert rows[3]["rir"] == 3
    assert rows[4]["rir"] == 2
    assert rows[2]["load_kg"] == 50.0


def test_import_applies_and_replaces_without_duplicating(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    first = workout.import_csv(conn, started["workout_id"], CSV, apply=True)
    assert len(first["workout"]["sets"]) == 6
    second = workout.import_csv(conn, started["workout_id"], CSV, apply=True)
    assert len(second["workout"]["sets"]) == 6
    assert all(row["source"] == "import" for row in second["workout"]["sets"])


def test_import_rejects_unknown_exercise(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    text = "Exercise,Set,RPE,Value,Weight,Reps\nUnknown Lift,1,4,0.5m/s,20kg,5\n"
    preview = workout.parse_import(text)
    assert preview["errors"]
    with pytest.raises(ValueError, match="errors"):
        workout.import_csv(conn, started["workout_id"], text, apply=True)


def test_update_actual_set_appends_correction(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    added = workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                            load_kg=100, reps=5, rir=2)
    set_id = added["sets"][0]["set_id"]
    updated = workout.update_set(
        conn, started["workout_id"], set_id, load_kg=105, reps=4, rir=3, velocity=0.42
    )
    row = updated["sets"][0]
    assert (row["load_kg"], row["reps"], row["rir"], row["velocity"]) == (105, 4, 3, 0.42)
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM workout_event WHERE event_type = 'update_set'"
    ).fetchone()["c"] == 1


def test_import_preview_reports_conflicts_and_undo_restores(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    first = workout.import_csv(conn, started["workout_id"], CSV, apply=True)
    assert first["workout"]["sets"][0]["load_kg"] == 20.0
    # The plan is frozen at start: an imported exercise that is not on it stays off-plan
    # rather than extending the prescription (DEC-RESOLVER-23).
    assert not any(item["exercise_id"] == "push_press"
                   for item in first["workout"]["plan"]["items"])
    assert first["workout"]["sets"][0]["prescription_item_index"] is None
    changed = CSV.replace("Push Press,1,4,???,20.0kg,4", "Push Press,1,4,???,25.0kg,4")
    preview = workout.import_csv(conn, started["workout_id"], changed, apply=False)
    assert preview["preview"]["rows"][0]["plan_new"] is True
    row = next(item for item in preview["preview"]["rows"] if item["exercise"] == "Push Press" and item["set_index"] == 1)
    assert row["conflicts"]["load_kg"] == [25.0, 20.0]
    workout.import_csv(conn, started["workout_id"], changed, apply=True)
    assert workout.get(conn, started["workout_id"])["sets"][0]["load_kg"] == 25.0
    restored = workout.undo_import(conn, started["workout_id"])
    assert restored["sets"][0]["load_kg"] == 20.0


def test_workout_materialisation_uses_actual_main_lifts_and_marks_incomplete(conn):
    started = workout.start(
        conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS,
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=20)
    row = conn.execute(
        "SELECT main_lifts, flags, set_count, working_set_count "
        "FROM session WHERE session_id = ?", (started["workout_id"],),
    ).fetchone()
    assert row["main_lifts"] == '["trap_bar_deadlift"]'
    assert "incomplete" in row["flags"]
    assert row["set_count"] == 1
    assert row["working_set_count"] == 1


def test_workout_materialisation_keeps_added_bodyweight_load_basis(conn):
    plan = {
        "for_date": "2024-01-01", "session_type": "squat",
        "items": [{
            "exercise_id": "back_extension", "sets": 3, "reps_low": 10,
            "reps_high": 12, "load_kg": 0, "rir_target": 2,
        }],
    }
    readiness = {**READINESS, "bodyweight_kg": 80}
    started = workout.start(conn, for_date="2024-01-01", plan=plan, readiness=readiness)
    workout.add_set(
        conn, started["workout_id"], exercise_id="back_extension",
        load_kg=5, reps=10, rir=2,
    )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=10)
    row = conn.execute(
        "SELECT load_basis, external_load_kg FROM clean_set WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()
    assert row["load_basis"] == "added"
    assert row["external_load_kg"] == 5.0


REP_CSV = """Exercise Name,Set Number,Metric Name,Rep Number,Velocity
Push Press,1,Mean Concentric Velocity,,0.780
Push Press,1,Mean Concentric Velocity,1,0.740
Push Press,1,Mean Concentric Velocity,2,0.740
Push Press,1,Mean Concentric Velocity,3,0.750
Push Press,1,Mean Concentric Velocity,4,0.880
"""


def test_parse_rep_import_reads_mean_and_samples():
    parsed = workout.parse_rep_import(REP_CSV)
    assert parsed["errors"] == []
    item = parsed["sets"][0]
    assert item["exercise_id"] == "push_press"
    assert item["mean"] == 0.780
    assert [rep["rep_index"] for rep in item["reps"]] == [1, 2, 3, 4]


def test_optional_rep_import_attaches_to_set_and_undo_restores(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.import_csv(conn, started["workout_id"], CSV, apply=True)
    preview = workout.import_csv(
        conn, started["workout_id"], CSV, apply=False, rep_text=REP_CSV
    )
    assert preview["preview"]["errors"] == []
    row = next(item for item in preview["preview"]["rows"]
               if item["exercise"] == "Push Press" and item["set_index"] == 1)
    assert row["velocity_mps"] == 0.78
    assert row["rep_mean"] == 0.78
    assert row["rep_velocities"][0]["rep_index"] == 1

    applied = workout.import_csv(
        conn, started["workout_id"], CSV, apply=True, rep_text=REP_CSV
    )
    set_row = next(item for item in applied["workout"]["sets"]
                   if item["exercise_id"] == "push_press" and item["set_index"] == 1)
    assert set_row["rep_summary"]["count"] == 4
    assert abs(set_row["rep_summary"]["loss_pct"]) > 0
    workout.undo_import(conn, started["workout_id"])
    restored = workout.get(conn, started["workout_id"])
    set_row = next(item for item in restored["sets"]
                   if item["exercise_id"] == "push_press" and item["set_index"] == 1)
    assert set_row["reps_detail"] is None


def test_per_rep_rows_must_match_a_main_set(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    rep_text = REP_CSV.replace("Push Press,1", "Push Press,9")
    preview = workout.import_csv(
        conn, started["workout_id"], CSV, apply=False, rep_text=rep_text
    )
    assert any("no matching set" in error["error"] for error in preview["preview"]["errors"])
    with pytest.raises(ValueError, match="errors"):
        workout.import_csv(
            conn, started["workout_id"], CSV, apply=True, rep_text=rep_text
        )


def test_manual_set_accepts_per_rep_velocities(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    updated = workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=3, rir=2,
        rep_velocities=[
            {"rep_index": 1, "velocity_mps": 0.62},
            {"rep_index": 2, "velocity_mps": 0.58},
            {"rep_index": 3, "velocity_mps": 0.55},
        ],
    )
    row = next(item for item in updated["sets"] if item["exercise_id"] == "trap_bar_deadlift")
    assert row["velocity"] == 0.583
    assert row["rep_summary"]["count"] == 3
    assert row["rep_summary"]["first"] == 0.62
    assert row["rep_summary"]["last"] == 0.55
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)
    reps = conn.execute(
        "SELECT rep_index, velocity_mps FROM clean_rep ORDER BY rep_index"
    ).fetchall()
    assert [item["velocity_mps"] for item in reps] == [0.62, 0.58, 0.55]


def test_manual_per_rep_count_cannot_exceed_reps(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    with pytest.raises(ValueError, match="exceeds reps"):
        workout.add_set(
            conn, started["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=2, rir=2,
            rep_velocities=[
                {"rep_index": 1, "velocity_mps": 0.62},
                {"rep_index": 2, "velocity_mps": 0.58},
                {"rep_index": 3, "velocity_mps": 0.55},
            ],
        )
    assert conn.execute("SELECT COUNT(*) FROM workout_set").fetchone()[0] == 0


def test_manual_per_rep_rejects_invalid_indices_and_velocities(conn):
    import math

    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    cases = [
        ([{"rep_index": 4, "velocity_mps": 0.6}], "exceeds reps"),
        ([{"rep_index": 1.5, "velocity_mps": 0.6}], "positive integer"),
        ([{"rep_index": 0, "velocity_mps": 0.6}], "positive integer"),
        ([{"rep_index": 1, "velocity_mps": math.nan}], "finite and positive"),
        ([{"rep_index": 1, "velocity_mps": math.inf}], "finite and positive"),
        ([{"rep_index": 1, "velocity_mps": -math.inf}], "finite and positive"),
        ([{"rep_index": 1, "velocity_mps": 0}], "finite and positive"),
        ([{"rep_index": 1, "velocity_mps": 0.6},
          {"rep_index": 1, "velocity_mps": 0.5}], "duplicate"),
    ]
    for values, message in cases:
        with pytest.raises(ValueError, match=message):
            workout.add_set(
                conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                load_kg=100, reps=3, rir=2, rep_velocities=values,
            )
    assert conn.execute("SELECT COUNT(*) FROM workout_set").fetchone()[0] == 0

    updated = workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=3, rir=2,
        rep_velocities=[
            {"rep_index": 1, "velocity_mps": 0.62},
            {"rep_index": 3, "velocity_mps": 0.55},
        ],
    )
    row = next(item for item in updated["sets"] if item["exercise_id"] == "trap_bar_deadlift")
    assert row["rep_summary"]["count"] == 2
    assert row["velocity"] == 0.585


def test_rep_import_materialises_clean_rep_rows(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.import_csv(
        conn, started["workout_id"], CSV, apply=True, rep_text=REP_CSV
    )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)
    rows = conn.execute(
        "SELECT rep_index, velocity_mps FROM clean_rep ORDER BY rep_index"
    ).fetchall()
    assert [row["rep_index"] for row in rows] == [1, 2, 3, 4]
    assert rows[0]["velocity_mps"] == 0.74


def test_rep_import_prefers_main_value_and_warns_on_mismatch(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    main = CSV.replace("Push Press,1,4,???,20.0kg,4", "Push Press,1,4,0.90m/s,20.0kg,4")
    preview = workout.import_csv(
        conn, started["workout_id"], main, apply=False, rep_text=REP_CSV
    )
    row = next(item for item in preview["preview"]["rows"]
               if item["exercise"] == "Push Press" and item["set_index"] == 1)
    assert row["velocity_mps"] == 0.90
    assert any("differs" in warning for warning in row["warnings"])


def test_rep_import_rejects_unknown_metric(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    bad = REP_CSV.replace("Mean Concentric Velocity", "Peak Velocity")
    preview = workout.import_csv(
        conn, started["workout_id"], CSV, apply=False, rep_text=bad
    )
    assert any("unsupported metric" in error["error"]
               for error in preview["preview"]["errors"])


def test_optional_post_lift_form_ratings_materialise(conn):
    started = workout.start(
        conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS,
    )
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=100, reps=5, rir=2,
    )
    rated = workout.set_form_rating(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift", rating=4,
    )
    assert rated["forms"][0]["rating"] == 4
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)
    rows = conn.execute(
        "SELECT exercise_id, rating FROM session_form_rating WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchall()
    assert [(row["exercise_id"], row["rating"]) for row in rows] == [
        ("trap_bar_deadlift", 4)
    ]

def test_duplicate_set_index_is_idempotent_only_for_the_same_payload(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    kwargs = dict(
        exercise_id="trap_bar_deadlift", load_kg=100, reps=5, rir=2, set_index=1,
    )
    first = workout.add_set(conn, started["workout_id"], **kwargs)
    retry = workout.add_set(conn, started["workout_id"], **kwargs)
    assert len(retry["sets"]) == 1
    assert retry["sets"][0]["set_id"] == first["sets"][0]["set_id"]
    with pytest.raises(ValueError, match="set_index_conflict"):
        workout.add_set(
            conn, started["workout_id"],
            **{**kwargs, "load_kg": 105, "reps": 4},
        )


def test_end_retry_returns_the_completed_workout(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                    load_kg=100, reps=5, rir=2)
    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)
    retry = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)
    assert retry["status"] == "completed"
    assert retry["ended_at"] == ended["ended_at"]
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM session WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()["c"] == 1
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM critique WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()["c"] == 0


def test_end_failure_rolls_back_the_completion(conn, monkeypatch):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                    load_kg=100, reps=5, rir=2)
    original = workout._event

    def boom(conn, workout_id, event_type, payload, **kwargs):
        if event_type == "end":
            raise RuntimeError("injected end failure")
        return original(conn, workout_id, event_type, payload, **kwargs)

    monkeypatch.setattr(workout, "_event", boom)
    with pytest.raises(RuntimeError, match="injected end failure"):
        workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)
    assert workout.get(conn, started["workout_id"])["status"] == "in_progress"
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM session WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()["c"] == 0


# ---------------------------------------------------------------------------
# Concurrent completion (release-integrity audit, WP2)
# ---------------------------------------------------------------------------


def _prepared_file_store(tmp_path):
    """A migrated file database plus one started workout, for cross-connection tests."""
    path = tmp_path / "coach.db"
    with db.Store(path) as store:
        started = workout.start(
            store.connection, for_date="2024-01-01", plan=PLAN, readiness=READINESS,
        )
        workout.add_set(
            store.connection, started["workout_id"],
            exercise_id="trap_bar_deadlift", load_kg=100, reps=5, rir=2,
        )
    return path, started["workout_id"]


def test_two_concurrent_completions_run_the_side_effects_once(tmp_path, monkeypatch):
    # Both requests observe in_progress before either transaction starts, which is exactly the
    # audit's race. The second must lose at the re-check inside the write transaction rather
    # than materialising a second session, advancing dwell twice or appending a second end
    # event. The barrier is injected on the pre-transaction read, not on completion itself.
    path, workout_id = _prepared_file_store(tmp_path)
    real_get = workout.get
    barrier = threading.Barrier(2)
    local = threading.local()

    def synced_get(conn, wid):
        snapshot = real_get(conn, wid)
        if (
            wid == workout_id
            and snapshot is not None
            and snapshot["status"] == "in_progress"
            and not getattr(local, "waited", False)
        ):
            local.waited = True
            barrier.wait(timeout=10)
        return snapshot

    monkeypatch.setattr(workout, "get", synced_get)
    results: list[dict] = []
    errors: list[BaseException] = []

    def complete():
        conn = db.connect(path)
        try:
            results.append(
                workout.end(conn, workout_id, session_rpe=7, duration_min=30)
            )
        except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=complete) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors
    assert [row["status"] for row in results] == ["completed", "completed"]
    with db.Store(path) as store:
        conn = store.connection
        assert conn.execute(
            "SELECT COUNT(*) FROM session WHERE session_id = ?", (workout_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM workout_event "
            "WHERE workout_id = ? AND event_type = 'end'", (workout_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM analytics_revision WHERE kind = 'workout_end'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM clean_set WHERE session_id = ?", (workout_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT done_count FROM exercise_dwell_state WHERE exercise_id = ?",
            ("trap_bar_deadlift",),
        ).fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Set idempotency (release-integrity audit, WP4)
# ---------------------------------------------------------------------------


def test_a_retry_must_match_the_complete_immutable_set_payload(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout_id = started["workout_id"]
    performed = started["started_at"]
    replica = [
        {"rep_index": 1, "velocity_mps": 0.50},
        {"rep_index": 2, "velocity_mps": 0.45},
    ]
    request = dict(
        exercise_id="trap_bar_deadlift",
        load_kg=100.0,
        reps=2,
        rir=2,
        source="device",
        set_index=1,
        rep_velocities=replica,
        performed_at=performed,
    )
    first = workout.add_set(conn, workout_id, **request)
    assert len(first["sets"]) == 1
    # The same instant in another offset, and the reps in another order, are a true replay.
    replay = workout.add_set(
        conn, workout_id,
        **{
            **request,
            "performed_at": dt.datetime.fromisoformat(performed)
                .astimezone(dt.timezone(dt.timedelta(hours=1))).isoformat(),
            "rep_velocities": list(reversed(replica)),
        },
    )
    assert len(replay["sets"]) == 1
    assert replay["sets"][0]["set_id"] == first["sets"][0]["set_id"]

    # Each field below changes the set, so each must be a conflict rather than a silent drop.
    conflicts = [
        {"source": "manual"},
        {"performed_at": (
            dt.datetime.fromisoformat(performed) + dt.timedelta(seconds=1)
        ).isoformat()},
        {"rep_velocities": [
            {"rep_index": 1, "velocity_mps": 0.49},
            {"rep_index": 2, "velocity_mps": 0.46},
        ]},
        {"rep_velocities": [{"rep_index": 1, "velocity_mps": 0.50}]},
    ]
    for change in conflicts:
        with pytest.raises(ValueError, match="set_index_conflict"):
            workout.add_set(conn, workout_id, **{**request, **change})
    assert len(workout.get(conn, workout_id)["sets"]) == 1


def test_concurrent_automatic_set_indices_are_not_lost(tmp_path):
    # Automatic indices are allocated under the write lock, so two writers cannot both choose
    # the same index and one of the sets cannot disappear into a false replay.
    path, workout_id = _prepared_file_store(tmp_path)
    barrier = threading.Barrier(6)
    errors: list[BaseException] = []

    def add(load: float):
        conn = db.connect(path)
        try:
            barrier.wait(timeout=10)
            workout.add_set(
                conn, workout_id, exercise_id="competition_bench_press",
                load_kg=load, reps=5, rir=2,
            )
        except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)
        finally:
            conn.close()

    loads = [40.0, 45.0, 50.0, 55.0, 60.0, 65.0]
    threads = [threading.Thread(target=add, args=(load,)) for load in loads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors
    with db.Store(path) as store:
        rows = store.connection.execute(
            "SELECT set_index, load_kg FROM workout_set "
            "WHERE exercise_id = 'competition_bench_press' ORDER BY set_index"
        ).fetchall()
    assert [row["set_index"] for row in rows] == [1, 2, 3, 4, 5, 6]
    assert sorted(row["load_kg"] for row in rows) == loads


def test_a_plan_carrying_a_constraint_veto_cannot_start(conn):
    """The web start path refuses rather than training around a recorded rule."""
    plan = {
        "for_date": "2024-01-01",
        "session_type": "hinge",
        "items": [{
            "exercise_id": "trap_bar_deadlift",
            "sets": 3, "reps_low": 5, "reps_high": 5,
            "load_kg": 100, "rir_target": 2,
        }],
        "issues": ["CONSTRAINT_VETO:trap_bar_deadlift:hard_exclude constraint 1 (injury low_back)"],
    }
    with pytest.raises(ValueError, match="recorded constraint blocks"):
        workout.start(
            conn, for_date="2024-01-01", plan=plan,
            readiness={"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3},
        )
