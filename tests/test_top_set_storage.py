"""Step 3 storage: set groups and workout set roles."""

from __future__ import annotations

import json

from strength_coach import workout
from strength_coach.store import db, repositories


def _prescription(conn, *, set_groups):
    run = repositories.start_run(conn, input_hash="top-set", code_version="test")
    repositories.append_prescription(
        conn,
        prescription_id="p-top",
        run_id=run.run_id,
        for_date="2026-11-01",
        session_type="squat",
        fallback_level="full",
        rule_document_version="test",
        calibration_ids=(),
        approved_by="deterministic",
        items=[
            {
                "order_index": 0,
                "exercise_id": "ssb_squat",
                "sets": 4,
                "reps_low": 5,
                "reps_high": 5,
                "load_kg": 100.0,
                "load_basis": "external",
                "rounding_increment": 2.5,
                "rir_target": 2,
                "essential": True,
                "set_groups": set_groups,
            }
        ],
    )


def test_top_set_columns_and_prescription_round_trip() -> None:
    with db.Store(":memory:") as store:
        conn = store.connection
        item_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(prescription_item)")
        }
        set_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(workout_set)")
        }
        clean_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(clean_set)")
        }
        assert "set_groups_json" in item_columns
        assert "set_role" in set_columns
        assert "set_role" in clean_columns
        groups = [
            {
                "role": "top_set",
                "sets": 1,
                "load_kg": 120.0,
                "reps_low": 5,
                "reps_high": 5,
                "rir_target": 1,
                "percent_of_top": None,
            },
            {
                "role": "back_off",
                "sets": 3,
                "load_kg": 100.0,
                "reps_low": 5,
                "reps_high": 5,
                "rir_target": 2,
                "percent_of_top": 0.85,
            },
        ]
        _prescription(conn, set_groups=groups)
        raw = conn.execute(
            "SELECT set_groups_json FROM prescription_item WHERE prescription_id='p-top'"
        ).fetchone()["set_groups_json"]
    assert json.loads(raw) == groups


def test_workout_role_is_logged_and_survives_an_ordinary_update() -> None:
    with db.Store(":memory:") as store:
        conn = store.connection
        plan = {
            "session_type": "squat",
            "items": [
                {
                    "order_index": 0,
                    "exercise_id": "ssb_squat",
                    "sets": 2,
                    "reps_low": 5,
                    "reps_high": 5,
                    "load_kg": 100.0,
                    "set_groups": [
                        {"role": "top_set", "sets": 1, "load_kg": 120.0},
                        {"role": "back_off", "sets": 1, "load_kg": 100.0},
                    ],
                }
            ],
        }
        started = workout.start(
            conn,
            for_date="2026-11-01",
            plan=plan,
            readiness={"sleep": 4, "energy": 4, "mood": 4, "soreness": 2,
                       "stress": 4, "nutrition": 4, "hydration": 4},
        )
        workout.add_set(
            conn, started["workout_id"], exercise_id="ssb_squat",
            load_kg=120.0, reps=5, rir=1, set_role="top_set",
        )
        row = workout.get(conn, started["workout_id"])["sets"][0]
        assert row["set_role"] == "top_set"
        workout.update_set(conn, started["workout_id"], row["set_id"], reps=5)
        updated = workout.get(conn, started["workout_id"])["sets"][0]
        assert updated["set_role"] == "top_set"
