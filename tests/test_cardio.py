"""Cardio capture: append-only, validated, and summarised as context not prescription."""

from __future__ import annotations

import sqlite3

import pytest

from strength_coach import cli
from strength_coach.features import cardio
from strength_coach.store import db, queries, repositories


def store():
    return db.Store(":memory:")


def log(conn, **overrides):
    payload = {
        "performed_on": "2024-01-02",
        "modality": "walk",
        "duration_s": 1800,
    }
    payload.update(overrides)
    return repositories.append_cardio(conn, **payload)


def test_summary_totals_weeks_and_modalities():
    with store() as s:
        conn = s.connection
        log(conn, performed_on="2024-01-02", modality="walk", duration_s=1800)
        log(conn, performed_on="2024-01-04", modality="bike", duration_s=2700,
            avg_hr=140, max_hr=165, srpe=6)
        log(conn, performed_on="2024-01-09", modality="walk", duration_s=3600)

        summary = cardio.compute(conn, on_date="2024-01-10", weeks=2)

    assert summary.sessions == 3
    assert summary.total_minutes == 135.0
    assert summary.average_weekly_minutes == 67.5
    assert summary.by_modality == {"bike": 1, "walk": 2}
    assert summary.average_srpe == 6.0
    assert summary.weekly_minutes == {"2024-W01": 75.0, "2024-W02": 60.0}
    assert summary.reference_min == 150
    assert "not a personal target" in summary.reference_note.lower()


def test_the_window_excludes_older_sessions():
    with store() as s:
        conn = s.connection
        log(conn, performed_on="2023-06-01", duration_s=3600)
        log(conn, performed_on="2024-01-09", duration_s=1800)

        summary = cardio.compute(conn, on_date="2024-01-10", weeks=2)

    assert summary.sessions == 1
    assert summary.total_minutes == 30.0


def test_an_empty_log_is_zero_not_an_error():
    with store() as s:
        summary = cardio.compute(s.connection, weeks=4)
    assert summary.sessions == 0
    assert summary.total_minutes == 0
    assert summary.weekly_minutes == {}


def test_a_wrong_distance_average_heart_rate_is_rejected():
    with store() as s, pytest.raises(ValueError, match="avg_hr cannot exceed"):
        log(s.connection, avg_hr=160, max_hr=150)


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"performed_on": "02/01/2024"}, "date must be"),
        ({"modality": "  "}, "modality cannot be empty"),
        ({"duration_s": 0}, "duration must be positive"),
        ({"avg_hr": 20}, "avg_hr must be"),
        ({"max_hr": 300}, "max_hr must be"),
        ({"srpe": 11}, "srpe must be"),
        ({"distance_m": -1}, "distance_m cannot be negative"),
    ],
)
def test_invalid_sessions_are_rejected(overrides, message):
    with store() as s, pytest.raises(ValueError, match=message):
        log(s.connection, **overrides)


def test_cardio_rows_are_append_only():
    with store() as s:
        conn = s.connection
        log(conn)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE cardio_log SET duration_s = 60")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM cardio_log")


def test_entries_are_ordered_and_queryable_by_window():
    with store() as s:
        conn = s.connection
        log(conn, performed_on="2024-01-05")
        log(conn, performed_on="2024-01-02")
        rows = queries.cardio_entries(conn, since="2024-01-01", until="2024-01-31")

    assert [row["performed_on"] for row in rows] == ["2024-01-02", "2024-01-05"]


def test_cli_logs_and_summarises(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main([
        "--db", str(path), "cardio", "--date", "2024-01-02",
        "--modality", "run", "--minutes", "40", "--avg-hr", "150",
        "--max-hr", "170", "--srpe", "6",
    ]) == 0
    out = capsys.readouterr().out
    assert "logged run 40 min on 2024-01-02" in out

    assert cli.main(["--db", str(path), "cardio", "--show", "--date", "2024-01-10"]) == 0
    out = capsys.readouterr().out
    assert "sessions        1" in out
    assert "run x1" in out
    assert "150-300 min/week" in out


def test_cli_requires_modality_and_minutes(tmp_path):
    path = tmp_path / "coach.db"
    with pytest.raises(SystemExit, match="--minutes is required"):
        cli.main(["--db", str(path), "cardio", "--modality", "walk"])
    with pytest.raises(SystemExit, match="--modality is required"):
        cli.main(["--db", str(path), "cardio", "--minutes", "30"])
