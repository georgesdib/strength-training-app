"""UI-committed plans become the same prescription artifacts as CLI runs."""

from __future__ import annotations

import pytest

from strength_coach import workout
from strength_coach.prescribe import generated, persistence
from strength_coach.store import db

PLAN = {
    "for_date": "2024-01-01",
    "session_type": "squat",
    "fallback_level": "fatigue_reduced",
    "rule_document_version": "test-rules",
    "calibration_ids": ["cal-1"],
    "items": [{
        "order_index": 0, "exercise_id": "ssb_squat", "sets": 4, "reps_low": 5,
        "reps_high": 5, "load_kg": 100, "load_basis": "external",
        "rounding_increment_kg": 2.5, "rir_target": 2, "essential": True,
        "e1rm_source_sets": 3, "refs": ["MOD-FAT-001", "MOD-MIN-001"], "warmup": [],
    }],
    "notes": {"fatigue_trigger": "sleep", "minimum_session": {"status": "applied"}},
}
READINESS = {
    "sleep": 3, "energy": 3, "mood": 3, "soreness": 4, "stress": 4,
    "nutrition": 4, "hydration": 4,
}


def test_store_plan_writes_prescription_and_provenance():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        conn.execute("BEGIN IMMEDIATE")
        prescription_id = persistence.store_plan(conn, PLAN)
        conn.execute("COMMIT")
        assert conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM prescription_item").fetchone()[0] == 1
        assert conn.execute(
            "SELECT e1rm_source_sets FROM prescription_item"
        ).fetchone()[0] == 3
        rows = conn.execute(
            "SELECT modifier_key, applied_on FROM prescription_modifier"
        ).fetchall()
        assert [(row["modifier_key"], row["applied_on"]) for row in rows] == [
            ("MOD-FAT-001", "2024-01-01"),
            ("MOD-MIN-001", "2024-01-01"),
        ]
        started = workout.start(
            conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS,
            prescription_id=prescription_id,
        )
        assert started["prescription_id"] == prescription_id
    finally:
        store.close()


def test_store_plan_keeps_resolver_provenance():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        plan = {
            **PLAN,
            "template_digest": "blueprint-digest",
            "policy_digest": "policy-digest",
            "input_hash": "input-digest",
            "generated_session": {
                "session_type": "squat",
                "assignment": {"squat_main": "ssb_squat"},
                "slots": [{
                    "id": "squat_main", "exercise_id": "ssb_squat", "sets": 4,
                    "reps_low": 5, "reps_high": 5, "rir_low": 2, "rir_high": 3,
                    "rest_s": 180, "essential": True, "load_source": "e1rm",
                    "power": False, "quality_stop": None,
                }],
            },
        }
        persistence.store_plan(conn, plan)
        row = conn.execute(
            "SELECT template_digest, policy_digest, input_hash, generated_session_json "
            "FROM prescription"
        ).fetchone()
        assert row["template_digest"] == "blueprint-digest"
        assert row["policy_digest"] == "policy-digest"
        assert row["input_hash"] == "input-digest"
        assert "squat_main" in row["generated_session_json"]
    finally:
        store.close()


def test_invalid_set_groups_are_rejected_before_any_append():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        plan = {
            **PLAN,
            "items": [{
                **PLAN["items"][0],
                "set_groups": [
                    {"role": "top_set", "sets": 1, "load_kg": 110,
                     "reps_low": 5, "reps_high": 5, "rir_target": 1},
                    {"role": "back_off", "sets": 1, "load_kg": 90,
                     "reps_low": 5, "reps_high": 5, "rir_target": 2},
                ],
            }],
        }
        with pytest.raises(ValueError, match="must equal item.sets"):
            persistence.store_plan(conn, plan)
        assert conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM workout_session").fetchone()[0] == 0
    finally:
        store.close()


def test_invalid_resolver_snapshot_is_rejected_before_any_append():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        plan = {
            **PLAN,
            "generated_session": {"slots": [{"id": "squat_main"}]},
        }
        with pytest.raises(generated.SnapshotError, match="exercise_id"):
            persistence.store_plan(conn, plan)
        assert conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0] == 0
    finally:
        store.close()


def test_rollback_leaves_no_artifact():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        conn.execute("BEGIN IMMEDIATE")
        persistence.store_plan(conn, PLAN)
        conn.execute("ROLLBACK")
        assert conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM prescription_modifier").fetchone()[0] == 0
    finally:
        store.close()


def test_minimum_provenance_survives_removal_of_all_affected_items():
    plan = {
        **PLAN,
        "items": [{**PLAN["items"][0], "refs": []}],
        "notes": {"minimum_session": {"requested": True, "applied": True}},
    }
    store = db.Store(":memory:")
    try:
        conn = store.connection
        conn.execute("BEGIN IMMEDIATE")
        persistence.store_plan(conn, plan)
        conn.execute("COMMIT")
        rows = conn.execute(
            "SELECT modifier_key FROM prescription_modifier"
        ).fetchall()
        assert [row["modifier_key"] for row in rows] == ["MOD-MIN-001"]
    finally:
        store.close()
