"""History edits are append-only corrections, not mutations."""

from __future__ import annotations

import pytest

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


def test_per_rep_velocity_can_be_backfilled_and_is_read_back():
    store = _store()
    try:
        conn = store.connection
        session_id = history.list_sessions(conn)["sessions"][0]["session_id"]
        detail = history.detail(conn, session_id)
        set_id = detail["sets"][0]["set_id"]
        history.apply_vbt(conn, session_id, [{
            "set_id": set_id,
            "mean": 0.72,
            "reps": [{"rep_index": 1, "velocity_mps": 0.75},
                     {"rep_index": 2, "velocity_mps": 0.69}],
        }], reason="backfill")
        after = history.detail(conn, session_id)
    finally:
        store.close()
    first = after["sets"][0]
    assert first["vbt_mean"] == 0.72
    assert [rep["velocity_mps"] for rep in first["vbt_reps"]] == [0.75, 0.69]
    assert after["vbt_override_count"] == 1


def test_sets_keep_the_order_they_were_logged():
    # An import inserts rows grouped by exercise, so set_id order is not the order the sets
    # were performed; raw_id is. The details view must show the log order.
    rows = [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Reps_Done": "5", "RIR": "2"},
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Reps_Done": "5", "RIR": "2"},
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Reps_Done": "5", "RIR": "2"},
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Reps_Done": "5", "RIR": "2"},
    ]
    store = db.Store(":memory:")
    try:
        training = make_training(rows)
        readiness = make_readiness([{"Date": "2024-01-01"}])
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        page = history.list_sessions(store.connection)
        session_id = page["sessions"][0]["session_id"]
        detail = history.detail(store.connection, session_id)
    finally:
        store.close()
    assert [item["exercise_id"] for item in detail["sets"]] == [
        "ssb_squat", "bench_press", "ssb_squat", "bench_press",
    ]
    # JSON columns must reach the browser as arrays: flags is text in SQLite, and a string has
    # no .join(), which is what broke the details sheet.
    assert isinstance(detail["flags"], list)
    assert isinstance(page["sessions"][0]["flags"], list)


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
        # Backfilled session values live in the append-only feedback row, not on the session.
        assert after["feedback"]["srpe"] == 8
        assert after["feedback"]["duration_min"] == 50
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


def test_history_form_ratings_are_append_only_and_amendable():
    store = _store()
    try:
        conn = store.connection
        session_id = history.list_sessions(conn)["sessions"][0]["session_id"]
        detail = history.detail(conn, session_id)
        history.edit_session(
            conn, session_id, sets=detail["sets"],
            forms=[{"exercise_id": "ssb_squat", "rating": 3}],
        )
        first = history.detail(conn, session_id)["forms"]
        assert first[0]["rating"] == 3
        history.edit_session(
            conn, session_id, sets=detail["sets"],
            forms=[{"exercise_id": "ssb_squat", "rating": 5}],
        )
        latest = history.detail(conn, session_id)["forms"]
        assert len(latest) == 1
        assert latest[0]["rating"] == 5
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM session_form_rating"
        ).fetchone()["n"] == 2
    finally:
        store.close()


def test_invalid_form_does_not_commit_set_changes():
    store = _store()
    try:
        conn = store.connection
        detail = history.detail(conn, history.list_sessions(conn)["sessions"][0]["session_id"])
        original = {item["set_id"]: item for item in detail["sets"]}
        first = detail["sets"][0]
        with pytest.raises(ValueError, match="rating must be between 1 and 5"):
            history.edit_session(
                conn, detail["session_id"],
                sets=[{**first, "load_kg": 105}, detail["sets"][1]],
                forms=[{"exercise_id": "ssb_squat", "rating": 9}],
            )
        after = {item["set_id"]: item for item in history.detail(conn, detail["session_id"])["sets"]}
        assert after[first["set_id"]]["load_kg"] == original[first["set_id"]]["load_kg"]
        assert conn.execute("SELECT COUNT(*) AS n FROM session_edit").fetchone()["n"] == 0
    finally:
        store.close()


def test_injected_failure_rolls_back_the_whole_edit(monkeypatch):
    store = _store()
    try:
        conn = store.connection
        detail = history.detail(conn, history.list_sessions(conn)["sessions"][0]["session_id"])
        first = detail["sets"][0]

        def boom(*_args, **_kwargs):
            raise RuntimeError("injected aggregate failure")

        monkeypatch.setattr(history, "_refresh_session", boom)
        with pytest.raises(RuntimeError, match="injected"):
            history.edit_session(
                conn, detail["session_id"],
                sets=[{**first, "load_kg": 105}, detail["sets"][1]],
            )
        after = history.detail(conn, detail["session_id"])
        assert after["sets"][0]["load_kg"] == first["load_kg"]
        assert conn.execute("SELECT COUNT(*) AS n FROM session_edit").fetchone()["n"] == 0
    finally:
        store.close()
