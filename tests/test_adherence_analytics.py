"""Longitudinal adherence aggregation: summed denominators, filters and coverage."""

from __future__ import annotations

import json

import pytest

from strength_coach import history, workout
from strength_coach.features import adherence_analytics
from strength_coach.store import db

READINESS = {"sleep": 4, "energy": 4, "mood": 4, "soreness": 2, "stress": 3}


@pytest.fixture
def conn():
    store = db.Store(":memory:")
    try:
        yield store.connection
    finally:
        store.close()


def item(exercise_id="trap_bar_deadlift", **overrides):
    value = {
        "exercise_id": exercise_id,
        "sets": 3,
        "reps_low": 3,
        "reps_high": 5,
        "load_kg": 100,
        "rir_target": 2,
    }
    value.update(overrides)
    return value


def start(conn, day, *items, session_type="hinge"):
    plan = {"for_date": day, "session_type": session_type, "items": list(items)}
    return workout.start(
        conn, for_date=day, plan=plan, readiness=READINESS,
    )


def log(conn, started, exercise_id="trap_bar_deadlift", load=100, reps=5, rir=2):
    workout.add_set(
        conn, started["workout_id"], exercise_id=exercise_id,
        load_kg=load, reps=reps, rir=rir,
    )


def end(conn, started):
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=30)


def aggregate(conn, **query):
    return adherence_analytics.analytics(conn, query)


def test_aggregation_sums_numerators_and_denominators_not_percentages(conn):
    first = start(conn, "2024-01-01", item(sets=10))
    for _ in range(10):
        log(conn, first)
    end(conn, first)
    second = start(conn, "2024-01-02", item(sets=2))
    log(conn, second)
    end(conn, second)

    result = aggregate(conn, **{"from": "2024-01-01", "to": "2024-01-31"})
    original = result["original"]
    assert result["coverage"]["workouts_analysed"] == 2
    assert original["workouts"] == 2
    assert original["set_completion"] == {
        "numerator": 11, "denominator": 12, "ratio": 0.9167,
    }
    # Average of 10/10 and 1/2 would be 75%, which is deliberately not used.
    assert original["set_completion"]["ratio"] != 0.75
    assert original["prescribed_sets"] == 12
    assert original["matched_sets"] == 11
    assert original["missing_sets"] == 1


def test_original_and_final_prescriptions_are_aggregated_separately(conn):
    started = start(conn, "2024-01-03", item(sets=5))
    workout.change_sets(conn, started["workout_id"], 0, -2)
    for _ in range(3):
        log(conn, started)
    end(conn, started)

    result = aggregate(conn, **{"from": "2024-01-01", "to": "2024-01-31"})
    assert result["original"]["prescribed_sets"] == 5
    assert result["original"]["matched_sets"] == 3
    assert result["original"]["set_completion"]["ratio"] == 0.6
    assert result["final_plan"]["prescribed_sets"] == 3
    assert result["final_plan"]["matched_sets"] == 3
    assert result["final_plan"]["set_completion"]["ratio"] == 1.0
    row = result["workouts"][0]
    assert row["original"]["set_completion"]["numerator"] == 3
    assert row["final_plan"]["set_completion"]["denominator"] == 3


def test_month_grouping_keeps_empty_periods_empty(conn):
    january = start(conn, "2024-01-03", item(sets=2))
    log(conn, january)
    end(conn, january)
    march = start(conn, "2024-03-10", item(sets=2))
    log(conn, march)
    log(conn, march)
    end(conn, march)

    result = aggregate(conn, **{
        "from": "2024-01-01", "to": "2024-04-30", "group_by": "month",
    })
    periods = {row["key"]: row for row in result["original"]["periods"]}
    assert list(periods) == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert periods["2024-02"]["has_data"] is False
    assert periods["2024-02"]["set_completion"] == {
        "numerator": 0, "denominator": 0, "ratio": None,
    }
    assert periods["2024-02"]["workouts"] == 0
    assert periods["2024-01"]["set_completion"]["ratio"] == 0.5
    assert periods["2024-03"]["set_completion"]["ratio"] == 1.0


def test_exercise_filter_includes_surplus_and_unmatched_sets_for_that_exercise(conn):
    started = start(conn, "2024-01-04", item(sets=2),
                    item("competition_bench_press", sets=2, load_kg=80))
    for _ in range(3):          # two planned slots plus one surplus
        log(conn, started)
    log(conn, started, exercise_id="competition_squat")   # unplanned exercise
    end(conn, started)

    trap = aggregate(conn, **{
        "from": "2024-01-01", "to": "2024-01-31",
        "exercise_id": "trap_bar_deadlift",
    })["original"]
    assert trap["prescribed_sets"] == 2
    assert trap["matched_sets"] == 2
    assert trap["performed_sets"] == 3
    assert trap["extra_sets"] == 1
    assert trap["set_completion"]["ratio"] == 1.0
    assert [row["exercise_id"] for row in trap["exercises"]] == ["trap_bar_deadlift"]

    squat = aggregate(conn, **{
        "from": "2024-01-01", "to": "2024-01-31",
        "exercise_id": "competition_squat",
    })["original"]
    assert squat["prescribed_sets"] == 0
    assert squat["performed_sets"] == 1
    assert squat["extra_sets"] == 1
    assert squat["set_completion"]["ratio"] is None


def test_session_type_filter_and_options(conn):
    hinge = start(conn, "2024-01-05", item(sets=2), session_type="hinge")
    log(conn, hinge)
    end(conn, hinge)
    squat = start(conn, "2024-01-06", item("competition_squat", sets=2),
                  session_type="squat")
    log(conn, squat, exercise_id="competition_squat")
    log(conn, squat, exercise_id="competition_squat")
    end(conn, squat)

    result = aggregate(conn, **{
        "from": "2024-01-01", "to": "2024-01-31", "session_type": "squat",
    })
    assert result["coverage"]["workouts_in_range"] == 1
    assert result["coverage"]["workouts_analysed"] == 1
    assert result["original"]["set_completion"]["numerator"] == 2
    assert result["filters"]["session_types"] == ["hinge", "squat"]
    assert result["filters"]["session_type"] == "squat"


def test_missing_targets_do_not_become_attainment(conn):
    started = start(conn, "2024-01-07", {"exercise_id": "trap_bar_deadlift", "sets": 2})
    log(conn, started)
    end(conn, started)

    original = aggregate(conn, **{
        "from": "2024-01-01", "to": "2024-01-31",
    })["original"]
    assert original["set_completion"] == {
        "numerator": 1, "denominator": 2, "ratio": 0.5,
    }
    for metric in (original["reps"], original["load"], original["rir"]):
        assert metric["evaluated_sets"] == 0
        assert metric["attainment"] == {
            "numerator": 0, "denominator": 0, "ratio": None,
        }


def test_voided_missing_session_and_invalid_snapshot_are_excluded(conn):
    live = start(conn, "2024-01-08", item(sets=2))
    log(conn, live)
    end(conn, live)
    history.void_session(conn, live["workout_id"], reason="duplicate")

    # A completed workout row without its materialised session is an integrity gap; it must
    # be counted and excluded rather than compared with an empty performed-set list.
    conn.execute(
        "INSERT INTO workout_session (workout_id, for_date, session_type, status, plan_json,"
        " readiness_json, started_at, plan_revision, last_activity_at) VALUES"
        " ('missing-session', '2024-01-09', 'hinge', 'completed', ?, '{}',"
        " '2024-01-09T10:00:00+00:00', 0, '2024-01-09T10:00:00+00:00')",
        (json.dumps({"for_date": "2024-01-09", "session_type": "hinge",
                     "items": [item(sets=2)]}),),
    )

    invalid = start(conn, "2024-01-10", item(sets=2))
    log(conn, invalid)
    end(conn, invalid)
    conn.execute(
        "UPDATE workout_session SET plan_json = 'not json' WHERE workout_id = ?",
        (invalid["workout_id"],),
    )

    result = aggregate(conn, **{"from": "2024-01-01", "to": "2024-01-31"})
    assert result["coverage"]["workouts_in_range"] == 3
    assert result["coverage"]["workouts_analysed"] == 0
    assert result["coverage"]["workouts_voided"] == 1
    assert result["coverage"]["workouts_without_session"] == 1
    assert result["coverage"]["invalid_plan_rows"] == 1
    assert result["original"]["set_completion"]["denominator"] == 0
    reasons = {row["reason"] for row in result["coverage"]["excluded"]}
    assert reasons == {
        "session_voided", "missing_materialised_session", "invalid_plan_json",
    }


def test_small_sample_guard_uses_workouts_and_prescribed_sets(conn):
    one = start(conn, "2024-01-11", item(sets=10))
    for _ in range(10):
        log(conn, one)
    end(conn, one)
    result = aggregate(conn, **{"from": "2024-01-01", "to": "2024-01-31"})
    assert result["original"]["small_sample"] is True

    for day in ("2024-01-12", "2024-01-13"):
        started = start(conn, day, item(sets=5))
        for _ in range(5):
            log(conn, started)
        end(conn, started)
    result = aggregate(conn, **{"from": "2024-01-01", "to": "2024-01-31"})
    assert result["original"]["workouts"] == 3
    assert result["original"]["small_sample"] is False


def test_week_grouping_and_drilldown_rows(conn):
    for day, done in (("2024-01-01", 2), ("2024-01-15", 1)):
        started = start(conn, day, item(sets=2))
        for _ in range(done):
            log(conn, started)
        end(conn, started)

    result = aggregate(conn, **{"from": "2024-01-01", "to": "2024-01-31"})
    periods = {row["key"]: row for row in result["original"]["periods"]}
    assert periods["2024-W01"]["set_completion"]["ratio"] == 1.0
    assert periods["2024-W02"]["has_data"] is False
    assert periods["2024-W03"]["set_completion"]["ratio"] == 0.5
    assert len(result["workouts"]) == 2
    assert result["workouts"][0]["for_date"] == "2024-01-15"
    assert result["workouts"][0]["original"]["set_completion"]["numerator"] == 1


def test_query_validation(conn):
    with pytest.raises(ValueError, match="weeks"):
        aggregate(conn, weeks=0)
    with pytest.raises(ValueError, match="weeks"):
        aggregate(conn, weeks=53)
    with pytest.raises(ValueError, match="date"):
        aggregate(conn, to="not-a-date")
    with pytest.raises(ValueError, match="group_by"):
        aggregate(conn, group_by="day")
    with pytest.raises(ValueError, match="known exercise"):
        aggregate(conn, exercise_id="not_a_lift")
    with pytest.raises(ValueError, match="at most"):
        aggregate(conn, **{"from": "2018-01-01", "to": "2024-01-01"})


def test_malformed_plan_items_are_excluded_instead_of_raising(conn):
    started = start(conn, "2024-01-14", item(sets=2))
    log(conn, started)
    end(conn, started)
    conn.execute(
        "UPDATE workout_session SET plan_json = ? WHERE workout_id = ?",
        (json.dumps({"for_date": "2024-01-14", "session_type": "hinge",
                     "items": [{"exercise_id": "trap_bar_deadlift", "sets": "many"}]}),
         started["workout_id"]),
    )

    result = aggregate(conn, **{"from": "2024-01-01", "to": "2024-01-31"})
    assert result["coverage"]["workouts_analysed"] == 0
    assert result["coverage"]["invalid_plan_rows"] == 1
    assert result["coverage"]["excluded"][0]["reason"] == "invalid_plan_json"
