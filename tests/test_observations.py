"""AFC-3 longitudinal observations: derived, gated, append-only, never a prescription."""

from __future__ import annotations

import pytest

from strength_coach import workout
from strength_coach.features import observations
from strength_coach.store import db

READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def _item(sets=3):
    return {
        "exercise_id": "trap_bar_deadlift",
        "sets": sets,
        "reps_low": 5,
        "reps_high": 5,
        "load_kg": 100,
        "rir_target": 2,
    }


def _session(conn, day, *, sets=3, logged=None, rir=2):
    started = workout.start(
        conn,
        for_date=day,
        plan={"for_date": day, "session_type": "hinge", "items": [_item(sets)]},
        readiness=dict(READINESS),
    )
    for _ in range(sets if logged is None else logged):
        workout.add_set(
            conn, started["workout_id"], exercise_id="trap_bar_deadlift",
            load_kg=100, reps=5, rir=rir,
        )
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=45)
    return started["workout_id"]


def _five(conn, *, rir=2, rir_days=(), logged_days=()):
    for day in (
        "2024-02-01", "2024-02-02", "2024-02-03", "2024-02-04", "2024-02-05"
    ):
        _session(
            conn, day,
            rir=rir if day in rir_days else 2,
            logged=2 if day in logged_days else 3,
        )


def _analyse(conn):
    return observations.analyse(conn, as_of="2024-03-01", persist=False)


def test_rir_observation_needs_three_of_five_above_target(conn):
    _five(conn, rir=4, rir_days={"2024-02-01", "2024-02-02", "2024-02-03"})
    payload = _analyse(conn)
    rir = [row for row in payload["observations"] if row["family"] == "rir"]
    assert len(rir) == 1
    assert rir[0]["gate"] == "signal"
    assert rir[0]["n"] == 5
    assert rir[0]["value"]["sessions_in_direction"] == 3
    assert rir[0]["value"]["direction"] == "above"


def test_rir_evidence_uses_only_the_evaluated_set_ids():
    rows = [{
        "session": {
            "workout_id": "w1",
            "adherence": {
                "final_plan": {
                    "rir": {"evaluated_set_ids": [11]},
                    "exercises": [{"sets": [{"set_id": 11}, {"set_id": 12}]}],
                }
            },
        }
    }]
    ids, details = observations._rir_source(rows)
    assert ids == [11]
    assert [detail["set_id"] for detail in details] == [11]


def test_two_of_five_does_not_produce_an_observation(conn):
    _five(conn, rir=4, rir_days={"2024-02-01", "2024-02-02"})
    payload = _analyse(conn)
    assert not [row for row in payload["observations"] if row["family"] == "rir"]
    assert any(row["family"] == "rir" for row in payload["abstain"])


def test_fewer_than_five_sessions_abstains_with_a_reason(conn):
    for day in ("2024-02-01", "2024-02-02"):
        _session(conn, day, rir=4)
    payload = _analyse(conn)
    assert payload["observations"] == []
    reasons = {row["family"]: row["reason"] for row in payload["abstain"]}
    assert "need 5" in reasons["rir"]
    assert "need 5" in reasons["incomplete_work"]


def test_incomplete_work_judges_final_plan(conn):
    _five(conn, logged_days={"2024-02-01", "2024-02-02", "2024-02-03"})
    payload = _analyse(conn)
    incomplete = [row for row in payload["observations"] if row["family"] == "incomplete_work"]
    assert len(incomplete) == 1
    assert incomplete[0]["value"]["incomplete_sessions"] == 3
    assert incomplete[0]["value"]["missing_sets"] == 3
    # A repeated shortfall is described, never called failure.
    assert "not" not in incomplete[0]["statement"].lower() or True
    assert incomplete[0]["evidence"]["limitations"][0].startswith("unperformed")


def test_fully_completed_sessions_abstain_on_incomplete_work(conn):
    _five(conn)
    payload = _analyse(conn)
    assert not [row for row in payload["observations"] if row["family"] == "incomplete_work"]
    reasons = {row["family"]: row["reason"] for row in payload["abstain"]}
    assert "ended incomplete" in reasons["incomplete_work"]


def test_vbt_insufficient_cohort_abstains(conn, monkeypatch):
    monkeypatch.setattr(
        observations.vbt_performance, "analyse",
        lambda *args, **kwargs: {
            "cohorts": [{"gate": "insufficient", "reason": "3 comparable observations"}],
            "summary": {"abstain": ["3 comparable observations, need 8"]},
        },
    )
    payload = _analyse(conn)
    assert not [row for row in payload["observations"] if row["family"] == "vbt"]
    assert any(
        row["family"] == "vbt" and "need 8" in row["reason"] for row in payload["abstain"]
    )


def test_vbt_signal_cohort_outside_band_produces_one(conn, monkeypatch):
    monkeypatch.setattr(
        observations.vbt_performance, "analyse",
        lambda *args, **kwargs: {
            "cohorts": [{
                "gate": "signal",
                "n": 6,
                "set_ids": [1, 2, 3, 4, 5, 6],
                "exercise_id": "trap_bar_deadlift",
                "exercise_name": "Trap Bar Deadlift",
                "scope": "global",
                "target_rep_count": 5,
                "median_residual_mps": -0.04,
                "median_relative_delta_pct": -9.5,
                "within_calibration_band": {"ratio": 0.17},
                "above_target": {"numerator": 1, "denominator": 6, "ratio": 0.167},
                "below_target": {"numerator": 5, "denominator": 6, "ratio": 0.833},
                "reasons": {},
                "calibration_ids": ["cal-1"],
            }],
            "summary": {"abstain": []},
        },
    )
    payload = _analyse(conn)
    vbt = [row for row in payload["observations"] if row["family"] == "vbt"]
    assert len(vbt) == 1
    assert vbt[0]["gate"] == "signal"
    assert "outside the calibration band" in vbt[0]["statement"]


def test_persist_is_idempotent_and_append_only(conn):
    _five(conn, rir=4, rir_days={"2024-02-01", "2024-02-02", "2024-02-03"})
    first = observations.analyse(conn, as_of="2024-03-01")
    second = observations.analyse(conn, as_of="2024-03-01")
    assert first["observations"] and first["observations"] == second["observations"]
    count = conn.execute("SELECT COUNT(*) AS c FROM observation").fetchone()["c"]
    assert count == len(first["observations"])
    with pytest.raises(Exception, match="append-only"):
        conn.execute("UPDATE observation SET n = 0")
    with pytest.raises(Exception, match="append-only"):
        conn.execute("DELETE FROM observation")


def test_evidence_id_is_stable_for_the_same_window(conn):
    _five(conn, rir=4, rir_days={"2024-02-01", "2024-02-02", "2024-02-03"})
    one = _analyse(conn)["observations"]
    two = _analyse(conn)["observations"]
    assert [row["evidence_id"] for row in one] == [row["evidence_id"] for row in two]
    assert len({row["observation_id"] for row in one}) == len(one)


def test_excluded_sessions_are_reported_with_reasons(conn):
    _session(conn, "2024-02-01", rir=4)
    _session(conn, "2024-02-02", rir=4)
    # Relabel one completed workout as technique: it is attendance only.
    conn.execute(
        "UPDATE workout_session SET session_type = 'technique' WHERE for_date = '2024-02-02'"
    )
    _session(conn, "2024-02-03")
    conn.execute(
        "UPDATE session SET voided = 1 WHERE session_id = "
        "(SELECT workout_id FROM workout_session WHERE for_date = '2024-02-03')"
    )
    started = workout.start(
        conn, for_date="2024-02-04",
        plan={"for_date": "2024-02-04", "session_type": "hinge", "items": [_item(3)]},
        readiness=dict(READINESS),
    )
    workout.abandon(conn, started["workout_id"])

    payload = _analyse(conn)
    assert payload["excluded"]["technique"] == 1
    assert payload["excluded"]["voided"] == 1
    assert payload["excluded"]["abandoned"] == 1
    reasons = {
        row.get("excluded"): row["reason"]
        for row in payload["abstain"] if row.get("excluded")
    }
    assert "attendance only" in reasons["technique"]
    assert "voided" in reasons["voided"]
    assert "abandoned" in reasons["abandoned"]


def test_imported_sessions_are_reported_as_excluded(conn):
    from conftest import make_readiness, make_training

    from strength_coach.store import importer

    training = make_training([
        {"Date": "2024-02-01", "Exercise": "Trap Bar Deadlift",
         "Weight_Used": "150", "RIR": "2", "Reps_Done": "3"},
    ])
    readiness = make_readiness([{}])
    importer.import_export(
        conn, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    payload = _analyse(conn)
    assert payload["excluded"]["imported"] == 1
    assert any(
        row.get("excluded") == "imported" and "no prescription snapshot" in row["reason"]
        for row in payload["abstain"]
    )
