"""Live workout: required readiness, append-only sets, measured/manual end."""

from __future__ import annotations

import pytest

from strength_coach import workout
from strength_coach.store import db

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


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def test_start_requires_all_seven_readiness_fields(conn):
    with pytest.raises(ValueError, match="readiness.energy"):
        workout.start(conn, for_date="2024-01-01", plan=PLAN,
                      readiness={**READINESS, "energy": None})
    assert workout.active_workout(conn) is None


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


def test_end_scores_rubric_and_review_closes_workout(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    workout.add_set(conn, started["workout_id"], exercise_id="trap_bar_deadlift",
                    load_kg=100, reps=5, rir=2)
    ended = workout.end(conn, started["workout_id"], session_rpe=7, duration_min=55)
    assert ended["critique_id"]
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM critique WHERE session_id = ?",
        (started["workout_id"],),
    ).fetchone()["c"] == 1
    assert workout.mark_reviewed(conn, started["workout_id"]) is True
    assert workout.mark_reviewed(conn, started["workout_id"]) is False
    assert workout.get(conn, started["workout_id"])["reviewed_at"]


def test_plan_overrides_keep_the_original_prescription(conn):
    started = workout.start(conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS)
    swapped = workout.swap_exercise(
        conn, started["workout_id"], 0, "conventional_deadlift"
    )
    assert swapped["original_plan"]["items"][0]["exercise_id"] == "trap_bar_deadlift"
    assert swapped["plan"]["items"][0]["exercise_id"] == "conventional_deadlift"
    assert swapped["plan"]["items"][0]["substitution_for"] == "trap_bar_deadlift"
    assert swapped["plan"]["items"][0]["load_kg"] is None
    assert swapped["plan_modified"] is True

    added = workout.add_exercise(
        conn, started["workout_id"], exercise_id="lat_pulldown", sets=2,
        reps_low=10, reps_high=12,
    )
    assert any(item["exercise_id"] == "lat_pulldown" for item in added["plan"]["items"])
    assert len(added["original_plan"]["items"]) == 2

    changed = workout.change_sets(conn, started["workout_id"], 0, 1)
    assert changed["plan"]["items"][0]["sets"] == 6
    removed = workout.remove_exercise(conn, started["workout_id"], 2)
    assert all(item["exercise_id"] != "lat_pulldown" for item in removed["plan"]["items"])
    assert len(removed["plan"]["items"]) == 2


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
    assert rows[3]["exercise_id"] == "bench_press_wide_grip"
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
    assert any(item["exercise_id"] == "push_press"
               for item in first["workout"]["plan"]["items"])
    changed = CSV.replace("Push Press,1,4,???,20.0kg,4", "Push Press,1,4,???,25.0kg,4")
    preview = workout.import_csv(conn, started["workout_id"], changed, apply=False)
    assert preview["preview"]["rows"][0]["plan_new"] is False
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
