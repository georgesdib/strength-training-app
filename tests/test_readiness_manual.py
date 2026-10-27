"""Manual readiness: per-field precedence, append-only history, and honest absence."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach import cli
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer, queries, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


@contextmanager
def store_with():
    training = make_training(ROWS)
    readiness = make_readiness([{"Date": "2024-01-01", "Sleep": "5", "Energy": "4"}])
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


def test_manual_wins_per_field_and_import_fills_the_rest():
    with store_with() as store:
        conn = store.connection
        repositories.append_readiness_entry(
            conn, on_date="2024-01-01", field="sleep", value=2, note="rough night",
        )
        repositories.append_readiness_entry(
            conn, on_date="2024-01-01", field="bodyweight_kg", value=80.5,
        )
        merged = queries.readiness_day(conn, "2024-01-01")

    assert merged["sleep"] == 2
    assert merged["energy"] == 4
    assert merged["sources"]["sleep"] == "manual"
    assert merged["sources"]["energy"] == "import"
    assert merged["bodyweight_kg"] == 80.5
    assert merged["sources"]["bodyweight_kg"] == "manual"
    assert merged["manual_fields"] == ["bodyweight_kg", "sleep"]
    note = json.loads(merged["manual_merge_note"])
    assert note["sleep"] == {"imported": 5.0, "manual": 2.0, "winner": "manual"}


def test_grip_strength_is_not_a_readiness_field():
    # DEC-GRIP-01: grip is a periodic capacity measurement, not daily readiness.
    with store_with() as store, pytest.raises(ValueError, match="unknown readiness field"):
        repositories.append_readiness_entry(
            store.connection, on_date="2024-01-01",
            field="grip_strength_kg", value=45.5,
        )


def test_relogging_appends_and_latest_wins():
    with store_with() as store:
        conn = store.connection
        repositories.append_readiness_entry(conn, on_date="2024-01-01", field="sleep", value=2)
        repositories.append_readiness_entry(conn, on_date="2024-01-01", field="sleep", value=3)
        rows = conn.execute(
            "SELECT value FROM readiness_entry WHERE on_date='2024-01-01' AND field='sleep' "
            "ORDER BY rowid"
        ).fetchall()
        merged = queries.readiness_day(conn, "2024-01-01")

    assert [r["value"] for r in rows] == [2, 3]
    assert merged["sleep"] == 3


def test_manual_entry_is_append_only():
    with store_with() as store:
        conn = store.connection
        repositories.append_readiness_entry(conn, on_date="2024-01-01", field="sleep", value=2)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE readiness_entry SET value = 5")


def test_unknown_readiness_is_said_out_loud():
    with store_with() as store:
        prescription = build_prescription(store.connection, for_date="2024-01-08",
                                          session_type="squat")

    assert any("readiness unknown for 2024-01-08" in w for w in prescription.warnings)


def test_manual_readiness_arms_the_fatigue_modifier():
    with store_with() as store:
        conn = store.connection
        repositories.append_readiness_entry(conn, on_date="2024-01-08", field="sleep", value=2)
        prescription = build_prescription(conn, for_date="2024-01-08", session_type="squat")

    assert prescription.fallback_level == "fatigue_reduced"
    assert any("MOD-FAT-001" in w for w in prescription.warnings)
    assert all(
        "readiness:2024-01-08" in item.rationale_refs
        for item in prescription.items if item.load_kg is not None
    )


def test_readiness_set_cli_and_bulk_import(tmp_path):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training(ROWS)
    readiness = make_readiness([{"Date": "2024-01-01"}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    assert cli.main(["--db", str(path), "readiness", "set", "--date", "2024-01-02",
                     "--sleep", "2", "--energy", "3", "--bodyweight", "80.5"]) == 0
    store = db.Store(path)
    try:
        day = queries.readiness_day(store.connection, "2024-01-02")
    finally:
        store.close()
    assert (day["sleep"], day["energy"], day["bodyweight_kg"]) == (2, 3, 80.5)

    state = tmp_path / "state.yaml"
    state.write_text(
        "profile:\n"
        "  effective_from: '2024-01-01'\n"
        "  primary_goal: longevity\n"
        "readiness:\n"
        "  - date: '2024-01-03'\n"
        "    sleep: 1\n",
        encoding="utf-8",
    )
    assert cli.main(["--db", str(path), "state", "--import", str(state)]) == 0
    store = db.Store(path)
    try:
        day = queries.readiness_day(store.connection, "2024-01-03")
    finally:
        store.close()
    assert day["sleep"] == 1


def test_volume_valve_config_can_be_saved_without_losing_the_file(tmp_path):
    from strength_coach.features import readiness as readiness_mod

    path = tmp_path / "readiness.yaml"
    path.write_text("modifier:\n  fields: [sleep, energy]\nset_reduction:\n  enabled: true\n  score_below: 0.50\n")
    cfg = readiness_mod.save_set_reduction(
        enabled=False, score_below=0.40, sets=2, include_essential=True, path=path,
    )
    assert cfg.set_reduction_enabled is False
    assert cfg.set_reduction_score_below == 0.40
    assert cfg.set_reduction_sets == 2
    assert cfg.set_reduction_include_essential is True
    text = path.read_text()
    assert "modifier:" in text
    assert "score_below: 0.40" in text


def test_wearable_score_is_an_accepted_readiness_observation():
    with store_with() as store:
        conn = store.connection
        from strength_coach.features import readiness as readiness_feature
        readiness_feature.record_manual(
            conn, "2024-01-08", {"sleep": 4, "wearable_score": 78},
        )
        row = conn.execute(
            "SELECT value FROM readiness_entry "
            "WHERE on_date='2024-01-08' AND field='wearable_score'"
        ).fetchone()
        sleep = conn.execute(
            "SELECT value FROM readiness_entry "
            "WHERE on_date='2024-01-08' AND field='sleep'"
        ).fetchone()
    assert row["value"] == 78
    assert sleep["value"] == 4
