"""UI-committed plans become the same prescription artifacts as CLI runs."""

from __future__ import annotations

from strength_coach import workout
from strength_coach.prescribe import persistence
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
        "refs": ["MOD-FAT-001"], "warmup": [],
    }],
    "notes": {"fatigue_trigger": "sleep"},
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
        rows = conn.execute(
            "SELECT modifier_key, applied_on FROM prescription_modifier"
        ).fetchall()
        assert [(row["modifier_key"], row["applied_on"]) for row in rows] == [
            ("MOD-FAT-001", "2024-01-01")
        ]
        started = workout.start(
            conn, for_date="2024-01-01", plan=PLAN, readiness=READINESS,
            prescription_id=prescription_id,
        )
        assert started["prescription_id"] == prescription_id
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
