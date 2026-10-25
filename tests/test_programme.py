"""Rolling programme forecast and reactive deload."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.features import deload as deload_feature
from strength_coach.features import programme
from strength_coach.prescribe import deload as deload_mod
from strength_coach.store import db, importer, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
]


@contextmanager
def store_with(rows=ROWS):
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


def test_programme_is_a_weekday_abc_forecast_and_persists_nothing():
    with store_with() as store:
        before = store.connection.execute(
            "SELECT COUNT(*) AS c FROM prescription"
        ).fetchone()["c"]
        entries = programme.build_programme(
            store.connection, start="2024-01-02", weeks=2,
            per_week=3, start_session_type="squat",
        )
        after = store.connection.execute(
            "SELECT COUNT(*) AS c FROM prescription"
        ).fetchone()["c"]

    assert len(entries) == 6
    assert all(e.session_type in {"squat", "hinge", "bench_squat", "bench_hinge"} for e in entries)
    assert all(e.session_type in {
        "squat", "hinge", "bench_squat", "bench_hinge"
    } for e in entries)
    assert len({e.session_type for e in entries}) >= 3
    assert all(dt.date.fromisoformat(e.on_date).weekday() in (0, 2, 4) for e in entries)
    assert before == after == 0


def test_two_flaring_sessions_trigger_a_reactive_deload():
    rows = ROWS + [
        {"Date": "2024-01-03", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
         "RIR": "2", "Reps_Done": "3"},
        {"Date": "2024-01-03", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "80",
         "RIR": "2", "Reps_Done": "5"},
    ]
    with store_with(rows) as store:
        conn = store.connection
        for day in ("2024-01-01", "2024-01-03"):
            repositories.append_symptom(
                conn, logged_on=day, timing="pre_session", region="low_back",
                level=2, settled_within_48h=0,
            )
        entries = programme.build_programme(
            conn, start="2024-01-04", weeks=1, per_week=3, start_session_type="squat",
        )

    assert entries[0].deload_reason is not None
    assert entries[0].prescription.fallback_level == "fatigue_reduced"
    assert "reactive deload" in " ".join(entries[0].prescription.warnings)


def test_a_forecast_entry_equals_a_freshly_built_prescription():
    # The forecast shares one history frame and one VBT calibration across entries for speed;
    # that must not change what building that date on its own would produce.
    from strength_coach.prescribe import build_prescription

    with store_with() as store:
        conn = store.connection
        entries = programme.build_programme(
            conn, start="2024-01-02", weeks=1, per_week=3, start_session_type="squat",
        )
        entry = entries[1]
        direct = build_prescription(
            conn, for_date=entry.on_date, session_type=entry.session_type,
        )

    assert entry.prescription.items == direct.items
    assert entry.prescription.warnings == direct.warnings
    assert entry.prescription.notes == direct.notes


def test_programme_can_use_a_selection_chooser():
    calls = []

    def chooser(slot, candidates):
        calls.append(slot.id)
        return None

    with store_with() as store:
        entries = programme.build_programme(
            store.connection, start="2024-01-02", weeks=1, per_week=1,
            start_session_type="squat", apply_selection=True,
            selection_chooser=chooser,
        )

    assert calls
    selection = entries[0].prescription.notes["selection"]
    assert selection["requested"] is True
    assert selection["llm_requested"] is True


def test_a_forecast_on_an_empty_store_is_empty_not_a_crash():
    # A new athlete clicking "Build forecast" before importing must get a plan with unknown
    # loads, not a 500. The VBT calibration and the spinal-cost helper both assume columns
    # that an empty history does not carry.
    store = db.Store(":memory:")
    try:
        entries = programme.build_programme(
            store.connection, start="2024-01-02", weeks=1, per_week=3, start_session_type="squat",
        )
    finally:
        store.close()

    assert len(entries) == 3
    assert all(entry.prescription.items for entry in entries)
    assert not any(entry.prescription.executable for entry in entries)


def test_programme_cli_prints_a_horizon(tmp_path, capsys):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()

    assert cli.main(["--db", str(path), "programme", "--weeks", "2",
                     "--start", "2024-01-02", "--start-session-type", "squat"]) == 0
    out = capsys.readouterr().out
    assert "forecast only" in out
    assert "2024-01-03" in out
    assert "Day A" not in out  # column format, not prose


def test_start_session_type_can_force_bench_hinge():
    with store_with() as store:
        conn = store.connection
        forced = programme.build_programme(
            conn, start="2024-01-02", weeks=1, per_week=1,
            start_session_type="bench_hinge",
        )
        legacy = programme.build_programme(
            conn, start="2024-01-02", weeks=1, per_week=1, start_session_type="bench_squat",
        )
    assert forced[0].session_type == "bench_hinge"
    assert legacy[0].session_type == "bench_squat"


def test_scheduled_deload_is_suggested_not_applied():
    with store_with() as store:
        conn = store.connection
        repositories.append_athlete_profile(
            conn, effective_from="2024-01-01", primary_goal="strength",
            goal_rank=["strength"], focus_lifts=["ssb_squat"],
            block_start_date="2024-01-01",
        )
        entries = programme.build_programme(
            conn, start="2024-02-05", weeks=1, per_week=3,
            start_session_type="squat",
        )

    assert all(entry.deload_suggestion for entry in entries)
    assert all(entry.deload_reason is None for entry in entries)
    assert all(entry.deload_applied is False for entry in entries)
    assert all("deload" not in entry.prescription.notes for entry in entries)
    assert all(
        entry.prescription.notes["deload_suggestion"]["trigger"] == "scheduled"
        for entry in entries
    )
    assert all(
        not any("MOD-DELOAD-001" in warning for warning in entry.prescription.warnings)
        for entry in entries
    )
    squat = next(
        item for entry in entries for item in entry.prescription.items
        if item.exercise_id == "ssb_squat"
    )
    assert squat.sets == 5
    assert squat.rir_target >= 2


def test_scheduled_deload_needs_an_anchor():
    with store_with() as store:
        entries = programme.build_programme(
            store.connection, start="2024-02-05", weeks=1, per_week=1,
            start_session_type="squat",
        )
    assert entries[0].deload_reason is None
    assert entries[0].deload_suggestion is None


def test_scheduled_deload_can_be_applied_after_confirmation():
    with store_with() as store:
        conn = store.connection
        repositories.append_athlete_profile(
            conn, effective_from="2024-01-01", primary_goal="strength",
            goal_rank=["strength"], focus_lifts=["ssb_squat"],
            block_start_date="2024-01-01",
        )
        suggestion = deload_feature.scheduled_decision(conn, "2024-02-05")
        entry = programme.build_programme(
            conn, start="2024-02-05", weeks=1, per_week=1,
            start_session_type="squat",
        )[0]
        applied = deload_mod.apply(entry.prescription, suggestion)
    assert suggestion is not None
    assert applied.fallback_level == "fatigue_reduced"
    assert applied.notes["deload"]["trigger"] == "scheduled"
    assert applied.notes["deload_suggestion"]["applied"] is False
    assert any("MOD-DELOAD-001" in warning for warning in applied.warnings)
    squat = next(item for item in applied.items if item.exercise_id == "ssb_squat")
    assert squat.sets == 4
