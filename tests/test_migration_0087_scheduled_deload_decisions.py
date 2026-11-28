from __future__ import annotations

import shutil
import sqlite3

import pytest

from strength_coach.store import db


def _before_0087(tmp_path):
    partial = tmp_path / "migrations-before-0087"
    partial.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if path.name.startswith("0087"):
            continue
        shutil.copy2(path, partial / path.name)
    return partial


def test_scheduled_deload_decisions_are_append_only_and_track_deferral_issuance(
    tmp_path,
):
    conn = db.connect(tmp_path / "coach.db")
    try:
        db.migrate(conn, _before_0087(tmp_path))
        db.migrate(conn)
        conn.execute(
            """
            INSERT INTO scheduled_deload_decision (
                event_id, schedule_anchor, window_starts_on, window_ends_on,
                decision, decided_at, operation_id, consumed_by_issuance_id,
                reconsider_after_issuance_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "scheduled:2026-01-01:2026-02-05",
                "2026-01-01",
                "2026-02-05",
                "2026-02-11",
                "deferred",
                "2026-02-05T12:00:00Z",
                "defer-operation",
                "issuance-1",
                "issuance-1",
            ),
        )
        row = conn.execute(
            "SELECT decision, consumed_by_issuance_id, "
            "reconsider_after_issuance_id FROM scheduled_deload_decision"
        ).fetchone()
        assert tuple(row) == ("deferred", "issuance-1", "issuance-1")

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE scheduled_deload_decision SET decision = 'accepted'"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM scheduled_deload_decision")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO scheduled_deload_decision (
                    event_id, schedule_anchor, window_starts_on, window_ends_on,
                    decision, decided_at, operation_id, consumed_by_issuance_id,
                    reconsider_after_issuance_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "scheduled:2026-01-01:2026-02-05",
                    "2026-01-01",
                    "2026-02-05",
                    "2026-02-11",
                    "not-a-decision",
                    "2026-02-05T12:00:00Z",
                    "bad-operation",
                    "issuance-1",
                    None,
                ),
            )
        # A deferral names the issuance that consumes it; other decisions name none.
        for decision, reconsider in (("deferred", "issuance-2"), ("accepted", "issuance-1")):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO scheduled_deload_decision (
                        event_id, schedule_anchor, window_starts_on, window_ends_on,
                        decision, decided_at, operation_id, consumed_by_issuance_id,
                        reconsider_after_issuance_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "scheduled:2026-01-01:2026-02-05",
                        "2026-01-01",
                        "2026-02-05",
                        "2026-02-11",
                        decision,
                        "2026-02-05T12:00:00Z",
                        f"bad-{decision}",
                        "issuance-1",
                        reconsider,
                    ),
                )
    finally:
        conn.close()
