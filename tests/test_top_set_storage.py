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
        # The stored shape is ordered: no role and no back-off ratio (DEC-RESOLVER-18).
        groups = [
            {
                "group_index": 0,
                "sets": 1,
                "load_kg": 120.0,
                "reps_low": 5,
                "reps_high": 5,
                "rir_target": 1,
            },
            {
                "group_index": 1,
                "sets": 3,
                "load_kg": 100.0,
                "reps_low": 5,
                "reps_high": 5,
                "rir_target": 2,
            },
        ]
        _prescription(conn, set_groups=groups)
        raw = conn.execute(
            "SELECT set_groups_json FROM prescription_item WHERE prescription_id='p-top'"
        ).fetchone()["set_groups_json"]
    assert json.loads(raw) == groups


def test_new_sets_write_no_role_and_a_legacy_value_stays_provenance() -> None:
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
                        {"group_index": 0, "sets": 1, "load_kg": 120.0,
                         "reps_low": 5, "reps_high": 5, "rir_target": 1},
                        {"group_index": 1, "sets": 1, "load_kg": 100.0,
                         "reps_low": 5, "reps_high": 5, "rir_target": 2},
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
            load_kg=120.0, reps=5, rir=1,
        )
        row = workout.get(conn, started["workout_id"])["sets"][0]
        # A new set carries no role and no substitution annotation unless one was given.
        assert row["set_role"] is None
        assert row["substitutes_plan_item_index"] is None
        # A historical row keeps its stored role: copied to clean_set as read-only provenance
        # and never rewritten or re-asked for (DEC-RESOLVER-23).
        conn.execute(
            "INSERT INTO workout_set (workout_id, exercise_id, set_index, load_kg, "
            "reps, rir, source, prescription_item_index, set_role) "
            "VALUES (?, 'ssb_squat', 2, 100.0, 5, 2, 'manual', 0, 'back_off')",
            (started["workout_id"],),
        )
        workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)
        roles = [
            record["set_role"] for record in conn.execute(
                "SELECT set_role FROM clean_set ORDER BY set_id"
            )
        ]
        assert roles == [None, "back_off"]
