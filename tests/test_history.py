"""History edits are append-only corrections, not mutations."""

from __future__ import annotations

from conftest import make_readiness, make_training
from strength_coach import history
from strength_coach.store import db, importer, queries

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


def _store():
    store = db.Store(":memory:")
    training = make_training(ROWS)
    readiness = make_readiness([{"Date": "2024-01-01"}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def test_history_lists_and_edits_with_superseding_rows():
    store = _store()
    try:
        conn = store.connection
        page = history.list_sessions(conn)
        assert page["total"] == 1
        session_id = page["sessions"][0]["session_id"]
        detail = history.detail(conn, session_id)
        assert len(detail["sets"]) == 2
        first = detail["sets"][0]
        edited = history.edit_session(
            conn, session_id,
            sets=[
                {**first, "load_kg": 105, "reps": 4},
                detail["sets"][1],
            ],
            session_rpe=8, duration_min=50, notes="corrected",
            reason="typo",
        )
        assert edited["warnings"] == []
        after = history.detail(conn, session_id)
        squat = next(item for item in after["sets"] if item["exercise_id"] == "ssb_squat")
        assert squat["load_kg"] == 105
        assert squat["reps"] == 4
        assert after["needs_review"] == 1
        rows = conn.execute(
            "SELECT set_id, supersedes_id, voided FROM clean_set ORDER BY set_id"
        ).fetchall()
        assert any(row["supersedes_id"] is not None for row in rows)
        assert len([row for row in rows if not row["voided"]]) == 3
        assert conn.execute("SELECT COUNT(*) AS n FROM session_edit").fetchone()["n"] == 1
        current = queries.clean_sets(conn)
        assert len(current) == 2
        assert 105.0 in current["load_kg"].tolist()
    finally:
        store.close()


def test_history_removal_is_a_tombstone():
    store = _store()
    try:
        conn = store.connection
        detail = history.detail(conn, history.list_sessions(conn)["sessions"][0]["session_id"])
        history.edit_session(conn, detail["session_id"], sets=[detail["sets"][0]])
        after = history.detail(conn, detail["session_id"])
        assert len(after["sets"]) == 1
        assert len(queries.clean_sets(conn)) == 1
        voided = conn.execute(
            "SELECT COUNT(*) AS n FROM clean_set WHERE voided = 1"
        ).fetchone()["n"]
        assert voided == 1
    finally:
        store.close()


def test_void_and_unvoid_remove_the_session_from_metrics():
    store = _store()
    try:
        conn = store.connection
        session_id = history.list_sessions(conn)["sessions"][0]["session_id"]
        voided = history.void_session(conn, session_id, reason="test")
        assert voided["voided"] == 1
        assert queries.sessions(conn).empty
        assert queries.clean_sets(conn).empty
        assert history.list_sessions(conn)["total"] == 1
        restored = history.void_session(conn, session_id, unvoid=True)
        assert restored["voided"] == 0
        assert len(queries.clean_sets(conn)) == 2
    finally:
        store.close()


def test_apply_vbt_set_and_rep_overrides():
    store = _store()
    try:
        conn = store.connection
        session_id = history.list_sessions(conn)["sessions"][0]["session_id"]
        detail = history.detail(conn, session_id)
        set_id = detail["sets"][0]["set_id"]
        result = history.apply_vbt(conn, session_id, [{
            "set_id": set_id, "mean": 0.81,
            "reps": [{"rep_index": 1, "velocity_mps": 0.84},
                     {"rep_index": 5, "velocity_mps": 0.76}],
        }])
        items = {item["set_id"]: item for item in result["session"]["sets"]}
        assert items[set_id]["vbt_mean"] == 0.81
        assert items[set_id]["vbt_reps"][0]["rep_index"] == 1
        assert len(result["session"]["sets"]) == 2
    finally:
        store.close()
