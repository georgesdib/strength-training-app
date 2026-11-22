"""Execution substitutions and additions: append-only, idempotent, watermark-ordered."""

from __future__ import annotations

import threading
import uuid

import pytest

from strength_coach import workout
from strength_coach.prescribe.models import PrescriptionItem
from strength_coach.store import db

PLAN = {
    "for_date": "2026-11-01",
    "session_type": "squat",
    "items": [
        {"order_index": 0, "exercise_id": "trap_bar_deadlift", "sets": 4,
         "reps_low": 3, "reps_high": 5, "load_kg": 150.0, "rir_target": 2},
        {"order_index": 1, "exercise_id": "bench_press", "sets": 3,
         "reps_low": 5, "reps_high": 5, "load_kg": 90.0, "rir_target": 2},
    ],
}
READINESS = {
    "sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3,
    "nutrition": 4, "hydration": 4,
}


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def _started(conn):
    return workout.start(
        conn, for_date="2026-11-01", plan=PLAN, readiness=READINESS,
    )


def _solved_item(load_kg: float = 55.0, unknown: str | None = None) -> PrescriptionItem:
    return PrescriptionItem(
        order_index=0,
        exercise_id="bench_press",
        sets=3,
        reps_low=5,
        reps_high=5,
        load_kg=None if unknown else load_kg,
        load_basis="external",
        rounding_increment_kg=2.5,
        rir_target=2,
        rest_s=180,
        essential=False,
        unknown_load_reason=unknown,
    )


def _patch_solver(monkeypatch, item: PrescriptionItem) -> None:
    from strength_coach.prescribe import engine

    def fake(*args, **kwargs):
        return item, ("prefill warning",), {"status": "solved"}

    monkeypatch.setattr(engine, "resolve_replacement", fake)


def test_a_substitution_is_solved_by_the_server_and_enters_the_view(conn, monkeypatch):
    _patch_solver(monkeypatch, _solved_item(55.0))
    started = _started(conn)
    event_id = str(uuid.uuid4())
    view = workout.record_execution_change(
        conn, started["workout_id"], client_event_id=event_id,
        kind="substitution", exercise_id="bench_press",
        plan_item_index=0,
    )
    change = view["substitutions"][0]
    assert change["plan_item_index"] == 0
    assert change["exercise_id"] == "bench_press"
    assert change["prefill_load_kg"] == 55.0
    assert change["prefill_reason"] == "solved"
    assert change["event_id"] > 0
    assert view["watermark"] == change["event_id"]
    assert view["additions"] == []


def test_a_substitution_is_rejected_after_a_set_was_logged(conn, monkeypatch):
    _patch_solver(monkeypatch, _solved_item(55.0))
    started = _started(conn)
    workout.add_set(
        conn, started["workout_id"], exercise_id="trap_bar_deadlift",
        load_kg=150.0, reps=5, rir=2, set_index=1, plan_item_index=0,
    )
    with pytest.raises(ValueError, match="after sets have been logged"):
        workout.record_execution_change(
            conn, started["workout_id"], client_event_id=str(uuid.uuid4()),
            kind="substitution", exercise_id="bench_press",
            plan_item_index=0,
        )


def test_a_matching_set_index_is_idempotent_only_for_the_same_payload(conn):
    started = _started(conn)
    kwargs = dict(
        exercise_id="trap_bar_deadlift", load_kg=150.0, reps=5, rir=2,
        set_index=1, plan_item_index=0,
    )
    first = workout.add_set(conn, started["workout_id"], **kwargs)
    assert len(first["sets"]) == 1
    replay = workout.add_set(conn, started["workout_id"], **kwargs)
    assert len(replay["sets"]) == 1
    with pytest.raises(ValueError, match="set_index_conflict"):
        workout.add_set(
            conn, started["workout_id"],
            **{**kwargs, "load_kg": 155.0},
        )


def test_a_duplicate_change_identity_is_idempotent_and_never_rewritten(conn, monkeypatch):
    _patch_solver(monkeypatch, _solved_item(55.0))
    started = _started(conn)
    event_id = str(uuid.uuid4())
    kwargs = dict(
        client_event_id=event_id,
        kind="substitution",
        exercise_id="bench_press",
        plan_item_index=0,
    )
    first = workout.record_execution_change(conn, started["workout_id"], **kwargs)
    second = workout.record_execution_change(conn, started["workout_id"], **kwargs)
    assert second["watermark"] == first["watermark"]
    assert conn.execute(
        "SELECT COUNT(*) FROM workout_event WHERE event_type = 'substitution'"
    ).fetchone()[0] == 1
    with pytest.raises(ValueError, match="different change"):
        workout.record_execution_change(
            conn, started["workout_id"],
            **{**kwargs, "exercise_id": "competition_squat"},
        )


def test_the_latest_substitution_for_a_slot_wins(conn, monkeypatch):
    _patch_solver(monkeypatch, _solved_item(55.0))
    started = _started(conn)
    first = workout.record_execution_change(
        conn, started["workout_id"], client_event_id=str(uuid.uuid4()),
        kind="substitution", exercise_id="bench_press",
        plan_item_index=0,
    )
    second = workout.record_execution_change(
        conn, started["workout_id"], client_event_id=str(uuid.uuid4()),
        kind="substitution", exercise_id="competition_squat",
        plan_item_index=0,
    )
    assert second["watermark"] > first["watermark"]
    assert [change["exercise_id"] for change in second["substitutions"]] == [
        "competition_squat"
    ]
    # Both events stay append-only history.
    assert conn.execute(
        "SELECT COUNT(*) FROM workout_event WHERE event_type = 'substitution'"
    ).fetchone()[0] == 2


def test_an_addition_is_extra_work_with_its_own_shape(conn, monkeypatch):
    _patch_solver(monkeypatch, _solved_item(40.0))
    started = _started(conn)
    view = workout.record_execution_change(
        conn, started["workout_id"], client_event_id=str(uuid.uuid4()),
        kind="addition", exercise_id="lateral_raise",
        after_item_index=1, reps_low=10, reps_high=12, rir_target=3,
    )
    addition = view["additions"][0]
    assert addition["after_item_index"] == 1
    assert (addition["reps_low"], addition["reps_high"]) == (10, 12)
    assert addition["rir_target"] == 3
    assert addition["prefill_load_kg"] == 40.0
    assert view["substitutions"] == []


def test_an_offline_author_records_no_prefill_and_is_never_retro_solved(
    conn, monkeypatch,
):
    from strength_coach.prescribe import engine

    def boom(*args, **kwargs):
        raise AssertionError("an offline change must not be solved on arrival")

    monkeypatch.setattr(engine, "resolve_replacement", boom)
    started = _started(conn)
    view = workout.record_execution_change(
        conn, started["workout_id"], client_event_id=str(uuid.uuid4()),
        kind="substitution", exercise_id="bench_press",
        plan_item_index=0, prefill_requested=False,
    )
    change = view["substitutions"][0]
    assert change["prefill_load_kg"] is None
    assert change["prefill_reason"] == "authored_offline"


def test_an_unsolved_prefill_records_the_reason(conn, monkeypatch):
    _patch_solver(monkeypatch, _solved_item(unknown="no usable bench history"))
    started = _started(conn)
    view = workout.record_execution_change(
        conn, started["workout_id"], client_event_id=str(uuid.uuid4()),
        kind="substitution", exercise_id="bench_press",
        plan_item_index=0,
    )
    change = view["substitutions"][0]
    assert change["prefill_load_kg"] is None
    assert change["prefill_reason"] == "no usable bench history"


def test_change_validation_never_guesses(conn):
    started = _started(conn)
    workout_id = started["workout_id"]
    with pytest.raises(ValueError, match="UUID"):
        workout.record_execution_change(
            conn, workout_id, client_event_id="not-a-uuid",
            kind="substitution", exercise_id="bench_press",
            plan_item_index=0,
        )
    with pytest.raises(ValueError, match="different exercise"):
        workout.record_execution_change(
            conn, workout_id, client_event_id=str(uuid.uuid4()),
            kind="substitution", exercise_id="trap_bar_deadlift",
            plan_item_index=0,
        )
    with pytest.raises(ValueError, match="does not name a plan item"):
        workout.record_execution_change(
            conn, workout_id, client_event_id=str(uuid.uuid4()),
            kind="substitution", exercise_id="bench_press",
            plan_item_index=9,
        )
    with pytest.raises(ValueError, match="after_item_index is required"):
        workout.record_execution_change(
            conn, workout_id, client_event_id=str(uuid.uuid4()),
            kind="addition", exercise_id="bench_press",
            reps_low=8, reps_high=10,
        )
    with pytest.raises(ValueError, match="plan_item_index is required"):
        workout.record_execution_change(
            conn, workout_id, client_event_id=str(uuid.uuid4()),
            kind="substitution", exercise_id="bench_press",
        )
    with pytest.raises(ValueError, match="only to a substitution"):
        workout.record_execution_change(
            conn, workout_id, client_event_id=str(uuid.uuid4()),
            kind="addition", exercise_id="bench_press",
            after_item_index=0, plan_item_index=0, reps_low=8, reps_high=10,
        )


def test_a_change_requires_an_in_progress_workout(conn):
    started = _started(conn)
    workout.end(
        conn, started["workout_id"], session_rpe=7, duration_min=30,
    )
    with pytest.raises(ValueError, match="not in progress"):
        workout.record_execution_change(
            conn, started["workout_id"], client_event_id=str(uuid.uuid4()),
            kind="substitution", exercise_id="bench_press",
            plan_item_index=0,
        )


def test_an_empty_view_has_a_zero_watermark(conn):
    started = _started(conn)
    assert workout.execution_view(conn, started["workout_id"]) == {
        "workout_id": started["workout_id"],
        "watermark": 0,
        "substitutions": [],
        "additions": [],
    }


def test_set_attribution_accepts_an_annotation_and_drops_a_stale_index(conn):
    started = _started(conn)
    workout_id = started["workout_id"]
    annotated = workout.add_set(
        conn, workout_id, exercise_id="competition_squat",
        load_kg=100.0, reps=3, rir=2, substitutes_plan_item_index=0,
    )
    row = annotated["sets"][-1]
    assert row["prescription_item_index"] == 0
    assert row["substitutes_plan_item_index"] == 0
    assert row["set_role"] is None

    stale = workout.add_set(
        conn, workout_id, exercise_id="trap_bar_deadlift",
        load_kg=150.0, reps=3, rir=2, plan_item_index=1,
    )
    row = stale["sets"][-1]
    assert row["prescription_item_index"] is None
    assert row["substitutes_plan_item_index"] is None

    with pytest.raises(ValueError, match="different exercise"):
        workout.add_set(
            conn, workout_id, exercise_id="trap_bar_deadlift",
            load_kg=150.0, reps=3, rir=2, substitutes_plan_item_index=0,
        )


def test_a_concurrent_set_blocks_a_substitution_before_it_is_recorded(tmp_path):
    # The audit's race: the set is written but not yet committed while the substitution request
    # runs. The performed-slot check must happen after the write lock is acquired, so it sees the
    # committed set; a check made before BEGIN IMMEDIATE would miss it and record a substitution
    # for a slot that has already been trained.
    path = tmp_path / "coach.db"
    with db.Store(path) as store:
        started = workout.start(
            store.connection, for_date="2026-11-01", plan=PLAN, readiness=READINESS,
        )
    workout_id = started["workout_id"]
    inserted = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def record_set():
        conn = db.connect(path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            workout.add_set(
                conn, workout_id, exercise_id="trap_bar_deadlift",
                load_kg=150.0, reps=5, rir=2,
            )
            inserted.set()
            release.wait(timeout=15)
            conn.commit()
        except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)
        finally:
            conn.close()

    writer = threading.Thread(target=record_set)
    writer.start()
    try:
        assert inserted.wait(timeout=10)
        # Let the substitution request reach BEGIN IMMEDIATE and wait behind the uncommitted set.
        timer = threading.Timer(0.5, release.set)
        timer.start()
        conn = db.connect(path)
        try:
            with pytest.raises(ValueError, match="after sets have been logged"):
                workout.record_execution_change(
                    conn, workout_id,
                    client_event_id=str(uuid.uuid4()),
                    kind="substitution",
                    exercise_id="bench_press",
                    plan_item_index=0,
                )
            assert conn.execute(
                "SELECT COUNT(*) FROM workout_event WHERE event_type = 'substitution'"
            ).fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        release.set()
        writer.join(timeout=20)
    assert not errors
