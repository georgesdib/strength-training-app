"""3RM/5RM cadence is a reminder, not a prescription change."""

from __future__ import annotations

from strength_coach.features import test_cadence
from strength_coach.store import db, repositories


def test_cadence_is_due_without_a_test_and_alternates_schemes():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        first = test_cadence.status(conn, "2024-01-01")
        assert first["due"] is True
        assert first["next_scheme"] == "3RM"
        assert first["coverage"]["status"] == "unavailable"
        assert first["coverage"]["reason"]

        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=100.0,
            effective_from="2024-01-01", source="measured", reason="3RM test",
        )
        not_due = test_cadence.status(conn, "2024-02-01")
        due = test_cadence.status(conn, "2024-03-11")
    finally:
        store.close()
    assert not_due["due"] is False
    assert not_due["next_scheme"] == "5RM"
    assert not_due["coverage"]["status"] == "insufficient"
    assert "measured-test gate" in not_due["coverage"]["reason"]
    assert due["due"] is True
    assert due["next_due"] == "2024-03-11"
