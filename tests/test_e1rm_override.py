"""Manual e1RM overrides.

An override is athlete state, not a prompt: it outranks the computed estimate, it can expire,
and the prescription must cite the row it used so the number is auditable.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.prescribe import build_prescription, validate_references
from strength_coach.rules import RuleContext
from strength_coach.store import db, importer, queries, repositories

HISTORY = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
]


@contextmanager
def store_with(rows=HISTORY):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def squat_load(prescription):
    return next(i for i in prescription.items if i.exercise_id == "ssb_squat")


def test_override_outranks_the_computed_estimate():
    with store_with() as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=160, effective_from="2024-01-15",
            reason="tested single",
        )
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")
        context = RuleContext.from_store(conn, end="2024-02-01")

        item = squat_load(prescription)
        # 160 / (1 + (3+2)/30) = 137.14 -> rounded down to the 0.5 kg increment
        assert item.load_kg == pytest.approx(137.0)
        assert item.rationale_refs[1].startswith("e1rm_override:")
        assert any("manual e1RM override" in w for w in prescription.warnings)
        assert validate_references(prescription, context, conn) == []


def test_expired_override_is_ignored():
    with store_with() as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=160,
            effective_from="2023-01-01", expires_on="2023-06-01",
        )
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")

    item = squat_load(prescription)
    assert item.load_kg == pytest.approx(105.5)   # back to the computed estimate
    assert not item.rationale_refs[1].startswith("e1rm_override:")


def test_future_override_is_ignored():
    with store_with() as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=160, effective_from="2024-06-01",
        )
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")

    assert squat_load(prescription).load_kg == pytest.approx(105.5)


def test_latest_effective_override_wins():
    with store_with() as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=160, effective_from="2023-12-01",
        )
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=180, effective_from="2024-01-01",
        )
        prescription = build_prescription(conn, for_date="2024-02-01", session_day="A")

    # 180 / (1 + 5/30) = 154.29 -> 154.0
    assert squat_load(prescription).load_kg == pytest.approx(154.0)


def test_overrides_are_append_only():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=160, effective_from="2024-01-01",
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM e1rm_override")


def test_override_lookup_respects_the_window():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_e1rm_override(
            conn, exercise_id="ssb_squat", e1rm_kg=160,
            effective_from="2024-01-01", expires_on="2024-03-01",
        )
        assert queries.e1rm_override(conn, "ssb_squat", "2024-02-01")["e1rm_kg"] == 160
        assert queries.e1rm_override(conn, "ssb_squat", "2024-04-01") is None
        assert queries.e1rm_override(conn, "ssb_squat", "2023-12-01") is None


def test_cli_sets_and_lists_overrides(tmp_path, capsys):
    path = tmp_path / "coach.db"
    assert cli.main([
        "--db", str(path), "e1rm", "set", "--exercise", "ssb_squat", "--kg", "160",
        "--from", "2024-01-01", "--reason", "tested single",
    ]) == 0
    out = capsys.readouterr().out
    assert "e1RM override: ssb_squat = 160 kg from 2024-01-01" in out

    assert cli.main(["--db", str(path), "e1rm", "list"]) == 0
    out = capsys.readouterr().out
    assert "ssb_squat" in out
    assert "160" in out


def test_state_import_accepts_overrides(tmp_path, capsys):
    path = tmp_path / "coach.db"
    state = tmp_path / "state.yaml"
    state.write_text(
        """
profile:
  effective_from: "2026-10-17"
  primary_goal: longevity
e1rm_overrides:
  - exercise_id: ssb_squat
    e1rm_kg: 160
    effective_from: "2026-10-17"
    reason: "tested single"
""".strip(),
        encoding="utf-8",
    )
    assert cli.main(["--db", str(path), "state", "--import", str(state)]) == 0
    out = capsys.readouterr().out
    assert "e1RM overrides 1" in out

    store = db.Store(path)
    try:
        row = queries.e1rm_override(store.connection, "ssb_squat", "2026-10-17")
        assert row["e1rm_kg"] == 160
    finally:
        store.close()
