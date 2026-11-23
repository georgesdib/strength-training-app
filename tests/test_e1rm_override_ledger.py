"""The append-only e1RM override ledger: overrides, withdrawals and statuses."""

from __future__ import annotations

from strength_coach.features import e1rm_override_ledger
from strength_coach.store import db, queries, repositories


def test_ledger_tracks_override_withdrawal_and_re_override():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=160, effective_from="2024-01-01",
        )
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=180, effective_from="2024-02-01",
        )
        repositories.append_e1rm_withdrawal(
            conn, exercise_id="ssb_squat", effective_from="2024-02-15", reason="wrong entry",
        )
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=190, effective_from="2024-03-01",
        )

        feb = e1rm_override_ledger.build(conn, on_date="2024-02-20")
        assert [(row.kind, row.effective_from, row.status) for row in feb] == [
            ("override", "2024-03-01", "future"),
            ("withdrawal", "2024-02-15", "withdrawn"),
            ("override", "2024-02-01", "superseded"),
            ("override", "2024-01-01", "superseded"),
        ]
        assert feb[1].e1rm_kg is None

        mar = e1rm_override_ledger.build(conn, on_date="2024-03-05")
        assert [(row.kind, row.effective_from, row.status) for row in mar] == [
            ("override", "2024-03-01", "active"),
            ("withdrawal", "2024-02-15", "superseded"),
            ("override", "2024-02-01", "superseded"),
            ("override", "2024-01-01", "superseded"),
        ]

        mid_feb = e1rm_override_ledger.build(conn, on_date="2024-02-10")
        assert [(row.kind, row.effective_from, row.status) for row in mid_feb] == [
            ("override", "2024-03-01", "future"),
            ("withdrawal", "2024-02-15", "future withdrawal"),
            ("override", "2024-02-01", "active"),
            ("override", "2024-01-01", "superseded"),
        ]


def test_same_day_withdrawal_wins_the_tie():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=160, effective_from="2024-01-01",
        )
        repositories.append_e1rm_withdrawal(
            conn, exercise_id="ssb_squat", effective_from="2024-01-01", reason="wrong entry",
        )

        assert queries.e1rm_override(conn, "ssb_squat", "2024-01-02") is None
        rows = e1rm_override_ledger.build(conn, on_date="2024-01-02")
        assert rows[0].kind == "withdrawal"
        assert rows[0].status == "withdrawn"
        assert rows[1].status == "superseded"


def test_ledger_is_empty_without_any_records():
    with db.Store(":memory:") as store:
        assert e1rm_override_ledger.build(store.connection, on_date="2024-01-01") == []
