"""VBT wiring: attach a velocity target when the calibration is trustworthy, say so when not."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from conftest import make_readiness, make_training

from strength_coach import workout
from strength_coach.features import vbt_calibration
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer
from strength_coach.web.server import prescription_dict

DATES = ("2024-01-04", "2024-01-11", "2024-01-18")
READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}


def rows_with_velocity() -> list[dict]:
    rows = []
    for _day_index, day in enumerate(DATES):
        for set_index in range(4):
            rows.append({
                "Date": day,
                "Exercise": "Safety Squat Bar",
                "Weight_Used": "100",
                "RIR": "2",
                "Reps_Done": "3",
                "Avg_velocity": f"{0.34 + 0.01 * set_index:.6f}",
            })
    rows += [
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
         "RIR": "2", "Reps_Done": "10"},
    ]
    return rows


def rows_without_velocity() -> list[dict]:
    return [
        {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
         "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
         "RIR": "2", "Reps_Done": "10"},
    ]


@contextmanager
def store_with(rows, readiness_rows=None):
    training = make_training(rows)
    readiness = make_readiness(readiness_rows or [{}])
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


def test_a_trustworthy_calibration_attaches_and_persists_a_target():
    with store_with(rows_with_velocity()) as store:
        conn = store.connection
        prescription = build_prescription(conn, for_date="2024-01-22", session_type="squat")
        squat = next(i for i in prescription.items if i.exercise_id == "ssb_squat")
        rows = [
            dict(row) for row in conn.execute(
                "SELECT * FROM vbt_calibration"
            )
        ]

    assert squat.velocity_target == pytest.approx(0.355, abs=0.01)
    assert squat.vbt_basis and "lift" in squat.vbt_basis
    assert len(prescription.calibration_ids) == 1
    assert prescription.notes["vbt"]["status"] == "available"
    assert prescription.notes["vbt"]["targets"] == 1
    assert len(rows) == 1

    target = squat.vbt
    assert target is not None
    assert target.target_mps == pytest.approx(squat.velocity_target)
    assert target.low_mps < target.target_mps < target.high_mps
    assert target.rep_count == 3
    assert (target.rir_low, target.rir_high) == (2, 3)
    assert target.scope == "lift"
    assert target.family == "squat"
    assert target.n_sets == 12
    assert target.n_sessions == 3
    assert target.method_version == vbt_calibration.METHOD_VERSION
    assert target.calibration_id == prescription.calibration_ids[0]
    assert target.source == "computed"

    row = rows[0]
    assert row["vbt_family"] == "squat"
    assert row["velocity_mad"] is not None
    assert row["source"] == "computed"

    stored = [value for value in prescription.as_rows() if value["exercise_id"] == "ssb_squat"][0]
    assert stored["velocity_target"] == pytest.approx(squat.velocity_target)
    assert stored["vbt_basis"] == squat.vbt_basis


def test_the_same_target_is_not_persisted_twice():
    with store_with(rows_with_velocity()) as store:
        conn = store.connection
        first = build_prescription(conn, for_date="2024-01-22", session_type="squat")
        second = build_prescription(conn, for_date="2024-01-22", session_type="squat")
        count = conn.execute("SELECT COUNT(*) AS c FROM vbt_calibration").fetchone()["c"]

    assert first.calibration_ids == second.calibration_ids
    assert count == 1


def test_without_enough_velocity_data_no_target_is_invented():
    with store_with(rows_without_velocity()) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-22",
                                          session_type="squat")

    assert all(item.velocity_target is None for item in prescription.items)
    assert all(item.vbt is None for item in prescription.items)
    assert prescription.calibration_ids == ()
    assert prescription.notes["vbt"]["status"] == "unavailable"
    assert "12 clean sets" in prescription.notes["vbt"]["reason"]


def test_a_modified_session_skips_velocity_targets():
    with store_with(
        rows_with_velocity(),
        readiness_rows=[{"Date": "2024-01-22", "Sleep": "2", "Energy": "4"}],
    ) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-22",
                                          session_type="squat")

    assert prescription.fallback_level == "fatigue_reduced"
    assert all(item.velocity_target is None for item in prescription.items)
    assert prescription.notes["vbt"]["status"] == "skipped"


def test_hex_bar_velocity_targets_are_withheld():
    rows = []
    for day in ("2024-01-04", "2024-01-11", "2024-01-18"):
        for index in range(4):
            rows.append({
                "Date": day, "Exercise": "Trap Bar Deadlift", "Weight_Used": "180",
                "RIR": "2", "Reps_Done": "3",
                "Avg_velocity": f"{0.31 + 0.01 * index:.6f}",
            })
    rows += [
        {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)",
         "Weight_Used": "70", "RIR": "2", "Reps_Done": "5"},
        {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
         "RIR": "2", "Reps_Done": "10"},
        {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30",
         "RIR": "3", "Reps_Done": "8"},
    ]
    with store_with(rows) as store:
        prescription = build_prescription(store.connection, for_date="2024-01-22",
                                          session_type="hinge")

    trap_bar = next(i for i in prescription.items if i.exercise_id == "trap_bar_deadlift")
    assert trap_bar.velocity_target is None
    assert trap_bar.vbt is None
    assert "trap_bar_deadlift" in prescription.notes["vbt"]["withheld"]


def test_structured_metadata_survives_workout_start_and_retrieval():
    with store_with(rows_with_velocity()) as store:
        conn = store.connection
        prescription = build_prescription(
            conn, for_date="2024-01-22", session_type="squat",
        )
        plan = prescription_dict(prescription)
        item = next(
            value for value in plan["items"] if value["exercise_id"] == "ssb_squat"
        )
        started = workout.start(
            conn, for_date="2024-01-22", plan=plan, readiness=READINESS,
        )
        stored = workout.get(conn, started["workout_id"])

    stored_item = next(
        value for value in stored["plan"]["items"]
        if value["exercise_id"] == "ssb_squat"
    )
    assert item["vbt"]["calibration_id"] is not None
    assert stored_item["vbt"] == item["vbt"]
    assert stored_item["velocity_target"] == item["velocity_target"]


def test_set_count_change_keeps_metadata_while_swap_and_add_clear_it():
    with store_with(rows_with_velocity()) as store:
        conn = store.connection
        prescription = build_prescription(
            conn, for_date="2024-01-22", session_type="squat",
        )
        plan = prescription_dict(prescription)
        index = next(
            position for position, value in enumerate(plan["items"])
            if value["exercise_id"] == "ssb_squat"
        )
        target = plan["items"][index]["vbt"]
        assert target is not None
        started = workout.start(
            conn, for_date="2024-01-22", plan=plan, readiness=READINESS,
        )
        changed = workout.change_sets(conn, started["workout_id"], index, 1)
        changed_item = changed["plan"]["items"][index]
        assert changed_item["vbt"] == target
        assert changed_item["velocity_target"] == target["target_mps"]

        swapped = workout.swap_exercise(
            conn, started["workout_id"], index, "competition_squat",
        )
        swapped_item = swapped["plan"]["items"][index]
        assert swapped_item["velocity_target"] is None
        assert swapped_item["vbt_basis"] is None
        assert swapped_item["vbt"] is None
        # The original snapshot still retains the target for audit; only the final plan drops it.
        original_item = swapped["original_plan"]["items"][index]
        assert original_item["vbt"] == target

        added = workout.add_exercise(
            conn, started["workout_id"], exercise_id="lat_pulldown", sets=2,
        )
        new_item = next(
            value for value in added["plan"]["items"]
            if value["exercise_id"] == "lat_pulldown"
        )
        assert new_item["vbt"] is None


def test_historical_target_stays_frozen_after_later_recalibration(monkeypatch):
    with store_with(rows_with_velocity()) as store:
        conn = store.connection
        first = build_prescription(
            conn, for_date="2024-01-22", session_type="squat",
        )
        first_plan = prescription_dict(first)
        first_item = next(
            value for value in first_plan["items"]
            if value["exercise_id"] == "ssb_squat"
        )
        started = workout.start(
            conn, for_date="2024-01-22", plan=first_plan, readiness=READINESS,
        )

        replacement = vbt_calibration.CalibrationTarget(
            exercise_id="ssb_squat", scope="lift", rep_count=3, rir_band=(2, 3),
            velocity_median=0.41, velocity_low=0.39, velocity_high=0.43,
            n_sets=17, n_sessions=4, velocity_mad=0.01, vbt_family="squat",
            method_version=vbt_calibration.METHOD_VERSION,
            params={"k": 2.0},
        )
        monkeypatch.setattr(
            vbt_calibration, "calibrate",
            lambda sets, **_kwargs: vbt_calibration.CalibrationResult(
                targets=[replacement], excluded={}, params=replacement.params,
            ),
        )
        second = build_prescription(
            conn, for_date="2024-01-22", session_type="squat",
        )
        second_item = next(
            value for value in prescription_dict(second)["items"]
            if value["exercise_id"] == "ssb_squat"
        )
        frozen = workout.get(conn, started["workout_id"])

    frozen_item = next(
        value for value in frozen["plan"]["items"]
        if value["exercise_id"] == "ssb_squat"
    )
    assert first_item["vbt"]["target_mps"] == pytest.approx(0.355, abs=0.01)
    assert frozen_item["vbt"] == first_item["vbt"]
    assert second_item["vbt"]["target_mps"] == 0.41
    assert frozen_item["vbt"]["calibration_id"] != second_item["vbt"]["calibration_id"]


def test_a_legacy_plan_item_without_structured_metadata_is_not_backfilled():
    plan = {
        "for_date": "2024-01-23",
        "session_type": "squat",
        "items": [{
            "exercise_id": "ssb_squat", "sets": 3, "reps_low": 3, "reps_high": 3,
            "load_kg": 100, "rir_target": 2, "essential": True, "refs": [],
            "velocity_target": 0.35, "vbt_basis": "lift · 12 sets/3 sessions",
        }],
    }
    store = db.Store(":memory:")
    try:
        started = workout.start(
            store.connection, for_date="2024-01-23", plan=plan, readiness=READINESS,
        )
        stored = workout.get(store.connection, started["workout_id"])
    finally:
        store.close()
    item = stored["plan"]["items"][0]
    assert item["velocity_target"] == 0.35
    assert item.get("vbt") is None


def test_calibration_ids_distinguish_lift_and_family_scope():
    from strength_coach.prescribe import engine

    base = {
        "exercise_id": "ssb_squat", "rep_count": 3, "rir_band": (2, 3),
        "velocity_median": 0.40, "velocity_low": 0.38, "velocity_high": 0.42,
        "n_sets": 18, "n_sessions": 3, "velocity_mad": 0.01,
        "vbt_family": "squat", "method_version": vbt_calibration.METHOD_VERSION,
        "params": {"k": 2.0},
    }
    store = db.Store(":memory:")
    try:
        conn = store.connection
        lift_id = engine._persist_calibration(
            conn,
            vbt_calibration.CalibrationTarget(**base, scope="lift"),
            "2024-01-22",
        )
        family_id = engine._persist_calibration(
            conn,
            vbt_calibration.CalibrationTarget(**base, scope="family"),
            "2024-01-22",
        )
        rows = [dict(row) for row in conn.execute(
            "SELECT calibration_id, scope, vbt_family, velocity_mad FROM vbt_calibration "
            "ORDER BY calibration_id"
        )]
    finally:
        store.close()
    assert lift_id != family_id
    assert {row["scope"] for row in rows} == {"lift", "family"}
    assert {row["vbt_family"] for row in rows} == {"squat"}
    assert all(row["velocity_mad"] == 0.01 for row in rows)


def test_family_scope_metadata_reaches_the_plan_item(monkeypatch):
    with store_with(rows_with_velocity()) as store:
        conn = store.connection
        family_target = vbt_calibration.CalibrationTarget(
            exercise_id="ssb_squat", scope="family", rep_count=3, rir_band=(2, 3),
            velocity_median=0.40, velocity_low=0.37, velocity_high=0.43,
            n_sets=24, n_sessions=4, velocity_mad=0.015, vbt_family="squat",
            method_version=vbt_calibration.METHOD_VERSION, params={"k": 2.0},
        )
        monkeypatch.setattr(
            vbt_calibration, "calibrate",
            lambda sets, **_kwargs: vbt_calibration.CalibrationResult(
                targets=[family_target], excluded={}, params=family_target.params,
            ),
        )
        prescription = build_prescription(
            conn, for_date="2024-01-22", session_type="squat",
        )
        payload = prescription_dict(prescription)
        item = next(
            value for value in payload["items"] if value["exercise_id"] == "ssb_squat"
        )
        row = conn.execute(
            "SELECT scope, vbt_family FROM vbt_calibration WHERE calibration_id = ?",
            (item["vbt"]["calibration_id"],),
        ).fetchone()

    assert item["vbt"]["scope"] == "family"
    assert item["vbt"]["family"] == "squat"
    assert row["scope"] == "family"
    assert row["vbt_family"] == "squat"
