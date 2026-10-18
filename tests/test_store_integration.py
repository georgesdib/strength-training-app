"""End-to-end on the real export: rows go in, and a re-run changes nothing.

This is the acceptance criterion for phase 3 stated as a test. It is marked `integration`
because it reads `data/raw`, and it asserts measured counts from the cleaner rather than
hard-coded numbers, so it cannot drift away from the cleaning policy.
"""

from __future__ import annotations

import pytest

from strength_coach.ingest import clean as clean_mod
from strength_coach.ingest import sessions as sessions_mod
from strength_coach.store import importer

pytestmark = pytest.mark.integration


def test_real_export_round_trip(populated_db, training_frame, readiness_frame):
    store, first, (training_sha, readiness_sha) = populated_db
    conn = store.connection

    expected = clean_mod.build_clean_sets(training_frame, readiness_frame)
    expected_sessions = sessions_mod.build_sessions(expected.sets)

    assert first.clean_sets_inserted == expected.n_sets
    assert first.quarantined == expected.n_quarantined
    assert first.sessions_written == len(expected_sessions)
    assert first.raw_rows_inserted == len(training_frame) + len(readiness_frame)

    stored = {
        table: conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
        for table in ("raw_row", "clean_set", "session", "quarantine")
    }
    assert stored["clean_set"] == expected.n_sets
    assert stored["session"] == len(expected_sessions)
    assert stored["quarantine"] == expected.n_quarantined

    # Re-importing the identical file must be a no-op in content, not a second copy.
    second = importer.import_export(
        conn, training_frame, readiness_frame,
        training_sha256=training_sha, readiness_sha256=readiness_sha,
    )
    assert second.clean_sets_inserted == 0
    assert second.raw_rows_inserted == 0
    assert second.quarantined == 0
    assert {
        table: conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
        for table in stored
    } == stored

    # Every clean set is traceable to a raw line, and every session to its date.
    orphans = conn.execute(
        "SELECT COUNT(*) AS c FROM clean_set s "
        "LEFT JOIN raw_row r ON s.raw_id = r.raw_id WHERE r.raw_id IS NULL"
    ).fetchone()["c"]
    assert orphans == 0
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM clean_set WHERE session_id <> occurred_on"
    ).fetchone()["c"] == 0
