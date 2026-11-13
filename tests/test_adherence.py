"""Prescription adherence engine: authoritative derivation, no persistence."""

from __future__ import annotations

import json

import pytest

from strength_coach import adherence, workout
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
        "reps_low": 5,
        "reps_high": 5,
        "load_kg": 100,
        "rir_target": 2,
    }
    value.update(overrides)
    return value


def start(conn, *items, bodyweight=None, session_type="hinge"):
    plan = {"for_date": "2024-01-01", "session_type": session_type, "items": list(items)}
    readiness = dict(READINESS)
    if bodyweight is not None:
        readiness["bodyweight_kg"] = bodyweight
    return workout.start(conn, for_date="2024-01-01", plan=plan, readiness=readiness)


def finish(conn, started):
    workout.end(conn, started["workout_id"], session_rpe=7, duration_min=45)
    return workout.get(conn, started["workout_id"])


def log(conn, started, *, exercise_id="trap_bar_deadlift", load=100, reps=5, rir=2,
        set_role=None, plan_item_index=None):
    workout.add_set(
        conn, started["workout_id"], exercise_id=exercise_id, load_kg=load,
        reps=reps, rir=rir, set_role=set_role, plan_item_index=plan_item_index,
    )


def test_a_fully_completed_prescription_is_complete(conn):
    started = start(conn, item(sets=3), item("competition_bench_press", sets=2, load_kg=80))
    for _ in range(3):
        log(conn, started)
    for _ in range(2):
        log(conn, started, exercise_id="competition_bench_press", load=80)
    result = adherence.analyse(finish(conn, started))

    assert result["version"] == 1
    assert result["status"] == "available"
    for view in ("original", "final_plan"):
        summary = result[view]
        assert summary["prescribed_sets"] == 5
        assert summary["matched_sets"] == 5
        assert summary["missing_sets"] == 0
        assert summary["extra_sets"] == 0
        assert summary["set_completion"] == {
            "numerator": 5, "denominator": 5, "ratio": 1.0,
        }
        assert summary["reps"]["attainment"]["ratio"] == 1.0
        assert summary["load"]["attainment"]["ratio"] == 1.0
        assert summary["rir"]["attainment"]["ratio"] == 1.0
        assert all(entry["status"] == "complete" for entry in summary["exercises"])


def test_missing_sets_lower_completion_without_touching_target_attainment(conn):
    started = start(conn, item(sets=3))
    for _ in range(2):
        log(conn, started)
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["prescribed_sets"] == 3
    assert result["matched_sets"] == 2
    assert result["missing_sets"] == 1
    assert result["extra_sets"] == 0
    assert result["set_completion"]["ratio"] == pytest.approx(0.6667)
    assert result["exercises"][0]["status"] == "under"
    # The two performed sets still met their targets; completion and attainment are distinct.
    assert result["reps"]["attainment"]["ratio"] == 1.0


def test_sets_beyond_the_prescription_are_extra_work(conn):
    started = start(conn, item(sets=3))
    for _ in range(5):
        log(conn, started)
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["prescribed_sets"] == 3
    assert result["performed_sets"] == 5
    assert result["matched_sets"] == 3
    assert result["missing_sets"] == 0
    assert result["extra_sets"] == 2
    assert result["set_completion"]["ratio"] == 1.0
    entry = result["exercises"][0]
    assert entry["status"] == "over"
    assert entry["extra_sets"] == 2
    assert [row["matched"] for row in entry["sets"]] == [True, True, True, False, False]
    assert entry["sets"][3]["included_in_attainment"] is False
    # Extra sets are still evaluated for display, but they do not inflate attainment.
    assert entry["reps"]["evaluated_sets"] == 3


def test_repetition_range_and_fixed_targets_are_reported_separately(conn):
    started = start(
        conn,
        item(sets=3, reps_low=5, reps_high=8),
        item("competition_bench_press", sets=3, reps_low=5, reps_high=5, load_kg=80),
    )
    for reps in (5, 4, 9):
        log(conn, started, reps=reps)
    for reps in (5, 5, 6):
        log(conn, started, exercise_id="competition_bench_press", load=80, reps=reps)
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["reps"]["evaluated_sets"] == 6
    assert result["reps"]["within_target"] == 3
    assert result["reps"]["below_target"] == 1
    assert result["reps"]["above_target"] == 2
    assert result["reps"]["attainment"] == {
        "numerator": 3, "denominator": 6, "ratio": 0.5,
    }
    range_item, fixed_item = result["exercises"]
    assert range_item["reps"]["common_target_low"] == 5
    assert range_item["reps"]["common_target_high"] == 8
    assert (fixed_item["reps"]["common_target_low"],
            fixed_item["reps"]["common_target_high"]) == (5, 5)
    assert fixed_item["reps"]["mean_actual_reps"] == pytest.approx(5.33)


def test_load_deviations_use_absolute_and_relative_deviation(conn):
    started = start(conn, item(sets=3, load_kg=100))
    for load in (100, 95, 105):
        log(conn, started, load=load)
    result = adherence.analyse(finish(conn, started))["original"]
    load = result["load"]

    assert load["evaluated_sets"] == 3
    assert load["at_target"] == 1
    assert load["below_target"] == 1
    assert load["above_target"] == 1
    assert load["attainment"] == {"numerator": 1, "denominator": 3, "ratio": 0.3333}
    assert load["mean_absolute_deviation_kg"] == pytest.approx(3.33)
    assert load["max_absolute_deviation_kg"] == 5.0
    assert load["mean_relative_deviation_pct"] == pytest.approx(0.0)
    deviations = [row["load_deviation_kg"] for row in result["exercises"][0]["sets"]]
    assert deviations == [0.0, -5.0, 5.0]
    assert result["exercises"][0]["sets"][1]["load_status"] == "below"
    assert result["exercises"][0]["sets"][2]["load_status"] == "above"


def test_rir_deviation_direction_and_tolerance(conn):
    started = start(conn, item(sets=4, rir_target=2))
    for rir in (2, 4, 0, 3):
        log(conn, started, rir=rir)
    result = adherence.analyse(finish(conn, started))["original"]
    rir = result["rir"]

    assert rir["evaluated_sets"] == 4
    assert rir["at_target"] == 2          # 2 and the tolerance-inclusive 3
    assert rir["above_target"] == 1
    assert rir["below_target"] == 1
    assert rir["attainment"] == {"numerator": 2, "denominator": 4, "ratio": 0.5}
    assert rir["mean_deviation"] == pytest.approx(0.25)
    rows = result["exercises"][0]["sets"]
    assert [row["rir_deviation"] for row in rows] == [0, 2, -2, 1]
    assert rows[1]["rir_status"] == "above"
    assert rows[2]["rir_status"] == "below"


def test_modified_set_count_keeps_original_and_final_distinct(conn):
    started = start(conn, item(sets=5))
    workout.change_sets(conn, started["workout_id"], 0, -2)
    for _ in range(3):
        log(conn, started)
    data = finish(conn, started)
    result = adherence.analyse(data)

    assert data["plan_modified"] is True
    assert result["original"]["prescribed_sets"] == 5
    assert result["original"]["matched_sets"] == 3
    assert result["original"]["missing_sets"] == 2
    assert result["original"]["set_completion"]["ratio"] == 0.6
    assert result["final_plan"]["prescribed_sets"] == 3
    assert result["final_plan"]["matched_sets"] == 3
    assert result["final_plan"]["missing_sets"] == 0
    assert result["final_plan"]["set_completion"]["ratio"] == 1.0
    assert result["changes"]["set_count_changed"] == [{
        "plan_item_index": 0,
        "exercise_id": "trap_bar_deadlift",
        "from_sets": 5,
        "to_sets": 3,
    }]


def test_set_count_and_target_changes_are_reported_independently(conn):
    """One edit must not hide another: set count and target provenance are separate rows."""
    started = start(conn, item(sets=5))
    workout.change_sets(conn, started["workout_id"], 0, -2)
    plan = workout.get(conn, started["workout_id"])["plan"]
    plan["items"][0].update({"reps_low": 8, "reps_high": 8})
    conn.execute(
        "UPDATE workout_session SET plan_modified_json = ? WHERE workout_id = ?",
        (json.dumps(plan), started["workout_id"]),
    )
    for _ in range(3):
        log(conn, started, reps=5)
    result = adherence.analyse(finish(conn, started))

    assert result["changes"]["set_count_changed"] == [{
        "plan_item_index": 0,
        "exercise_id": "trap_bar_deadlift",
        "from_sets": 5,
        "to_sets": 3,
    }]
    assert result["changes"]["targets_changed"] == [{
        "plan_item_index": 0,
        "exercise_id": "trap_bar_deadlift",
        "fields": ["reps_high", "reps_low"],
    }]
    assert result["original"]["reps"]["attainment"]["ratio"] == 1.0
    assert result["final_plan"]["reps"]["attainment"]["ratio"] == 0.0


def test_a_swapped_exercise_makes_only_that_original_item_unavailable(conn):
    started = start(conn, item(sets=2), item("competition_bench_press", sets=2, load_kg=80))
    workout.swap_exercise(conn, started["workout_id"], 0, "conventional_deadlift")
    for _ in range(2):
        log(conn, started, exercise_id="conventional_deadlift", load=100)
    for _ in range(2):
        log(conn, started, exercise_id="competition_bench_press", load=80)
    result = adherence.analyse(finish(conn, started))

    assert result["changes"]["swapped"] == [{
        "plan_item_index": 0,
        "from_exercise_id": "trap_bar_deadlift",
        "to_exercise_id": "conventional_deadlift",
    }]
    original = result["original"]
    assert original["prescribed_sets"] == 2          # only the untouched bench item
    assert original["unattributable_planned_sets"] == 2
    assert original["matched_sets"] == 2
    assert original["extra_sets"] == 2
    swapped = original["exercises"][0]
    assert swapped["attributable"] is False
    assert swapped["status"] == "unavailable"
    assert swapped["prescribed_sets"] == 0
    assert swapped["limitations"] == ["swapped_exercise"]
    assert original["quality"]["unmatched_sets"] == 2
    assert original["quality"]["mismatched_attribution"] == 2
    assert {row["reason"] for row in original["quality"]["unmatched"]} == {
        "mismatched_exercise"
    }
    assert result["final_plan"]["prescribed_sets"] == 4
    assert result["final_plan"]["matched_sets"] == 4


def test_addition_and_removal_do_not_reuse_identities(conn):
    started = start(conn, item(sets=2), item("competition_bench_press", sets=2, load_kg=80))
    workout.remove_exercise(conn, started["workout_id"], 1)
    added = workout.add_exercise(
        conn, started["workout_id"], exercise_id="competition_squat", sets=2,
    )
    squat = next(value for value in added["plan"]["items"]
                 if value["exercise_id"] == "competition_squat")
    assert squat["order_index"] == 2          # never reuse the removed identity 1
    for _ in range(2):
        log(conn, started)
    for _ in range(2):
        log(conn, started, exercise_id="competition_squat", load=100)
    result = adherence.analyse(finish(conn, started))

    assert result["changes"]["removed"] == [{
        "plan_item_index": 1,
        "exercise_id": "competition_bench_press",
        "sets": 2,
    }]
    assert result["changes"]["added"] == [{
        "plan_item_index": 2,
        "exercise_id": "competition_squat",
        "sets": 2,
    }]
    original = result["original"]
    assert original["prescribed_sets"] == 4
    assert original["matched_sets"] == 2
    assert original["missing_sets"] == 2
    assert original["extra_sets"] == 2
    assert original["quality"]["added_exercise_sets"] == 2
    removed_item = next(value for value in original["exercises"]
                        if value["exercise_id"] == "competition_bench_press")
    assert removed_item["status"] == "missing"
    final = result["final_plan"]
    assert final["prescribed_sets"] == 4
    assert final["matched_sets"] == 4
    assert final["extra_sets"] == 0


def test_sets_for_a_removed_exercise_remain_visible_as_final_extra_work(conn):
    started = start(conn, item(sets=2), item("competition_bench_press", sets=2, load_kg=80))
    for _ in range(2):
        log(conn, started, exercise_id="competition_bench_press", load=80)
    workout.remove_exercise(conn, started["workout_id"], 1)
    for _ in range(2):
        log(conn, started)
    result = adherence.analyse(finish(conn, started))

    assert result["original"]["matched_sets"] == 4
    assert result["original"]["missing_sets"] == 0
    final = result["final_plan"]
    assert final["prescribed_sets"] == 2
    assert final["matched_sets"] == 2
    assert final["extra_sets"] == 2
    assert final["quality"]["removed_exercise_sets"] == 2
    assert {row["reason"] for row in final["quality"]["unmatched"]} == {
        "removed_from_final_plan"
    }


def test_a_duplicate_exercise_without_an_index_is_ambiguous(conn):
    duplicate = item(sets=2)
    started = start(conn, duplicate, dict(duplicate))
    log(conn, started)          # unique-name resolution refuses to choose an occurrence
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["matched_sets"] == 0
    assert result["missing_sets"] == 4
    assert result["extra_sets"] == 1
    assert result["quality"]["ambiguous_attribution"] == 1
    assert result["quality"]["unmatched"][0]["reason"] == "ambiguous_attribution"
    assert all(entry["status"] == "missing" for entry in result["exercises"])


def test_an_unplanned_exercise_is_reported_as_unmatched(conn):
    started = start(conn, item(sets=2))
    for _ in range(2):
        log(conn, started, exercise_id="competition_squat", load=100)
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["matched_sets"] == 0
    assert result["missing_sets"] == 2
    assert result["extra_sets"] == 2
    assert result["quality"]["unmatched_sets"] == 2
    assert {row["reason"] for row in result["quality"]["unmatched"]} == {"unattributed"}


def test_warm_ups_and_contradictory_roles_are_excluded_and_visible(conn):
    started = start(conn, item(sets=3))
    log(conn, started, load=50, reps=10, rir=6)                     # logged warm-up
    log(conn, started, rir=6, set_role="top_set")                   # contradictory role
    for _ in range(2):
        log(conn, started)
    data = finish(conn, started)
    result = adherence.analyse(data)

    assert len(data["sets"]) == 4
    assert result["quality"]["warm_up_sets_excluded"] == 1
    assert result["quality"]["ambiguous_status_sets"] == 1
    original = result["original"]
    assert original["performed_sets"] == 2
    assert original["matched_sets"] == 2
    assert original["missing_sets"] == 1
    assert original["warm_up_sets_excluded"] == 1
    assert len(original["exercises"][0]["sets"]) == 2
    assert all(row["matched"] for row in original["exercises"][0]["sets"])


def test_bodyweight_total_mass_is_comparable_with_a_bodyweight_target(conn):
    started = start(
        conn,
        item("pull_up", sets=2, reps_low=5, reps_high=8, load_kg=0,
             load_basis="bodyweight_total", rir_target=2),
        bodyweight=80,
    )
    log(conn, started, exercise_id="pull_up", load=0, reps=6, rir=2)
    log(conn, started, exercise_id="pull_up", load=82, reps=6, rir=2)
    log(conn, started, exercise_id="pull_up", load=5, reps=6, rir=2)   # extra added plate
    result = adherence.analyse(finish(conn, started))["original"]

    load = result["load"]
    assert load["evaluated_sets"] == 2
    assert load["at_target"] == 2
    assert load["attainment"]["ratio"] == 1.0
    rows = result["exercises"][0]["sets"]
    assert rows[0]["load_actual_external_kg"] == 0.0
    assert rows[1]["load_actual_external_kg"] == 0.0
    assert rows[0]["load_target_kg"] == 0.0
    assert rows[0]["load_deviation_pct"] is None       # relative deviation is undefined at 0
    assert rows[2]["extra"] is True
    assert rows[2]["load_deviation_kg"] == 5.0
    assert rows[2]["load_status"] == "above"


def test_added_load_target_and_captured_total_mass_are_not_comparable(conn):
    started = start(
        conn,
        item("pull_up", sets=2, reps_low=5, reps_high=8, load_kg=5,
             load_basis="external", rir_target=2),
        bodyweight=80,
    )
    log(conn, started, exercise_id="pull_up", load=5, reps=6, rir=2)     # added plate
    log(conn, started, exercise_id="pull_up", load=82, reps=6, rir=2)    # captured total
    result = adherence.analyse(finish(conn, started))["original"]

    load = result["load"]
    assert load["evaluated_sets"] == 1
    assert load["at_target"] == 1
    assert load["unavailable_sets"] == 1
    assert "actual_load_includes_bodyweight" in result["quality"]["unavailable_metrics"]
    rows = result["exercises"][0]["sets"]
    assert rows[0]["load_status"] == "at_target"
    assert rows[1]["load_status"] == "unavailable"
    assert "actual_load_includes_bodyweight" in rows[1]["limitations"]


def test_missing_and_invalid_targets_are_explicitly_unavailable(conn):
    started = start(conn, item(sets=3, reps_low=None, reps_high=None,
                               load_kg=None, rir_target=None))
    for _ in range(3):
        log(conn, started)
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["reps"]["evaluated_sets"] == 0
    assert result["load"]["evaluated_sets"] == 0
    assert result["rir"]["evaluated_sets"] == 0
    for metric in ("reps", "load", "rir"):
        assert result[metric]["attainment"] == {
            "numerator": 0, "denominator": 0, "ratio": None,
        }
    limitations = set(result["quality"]["unavailable_metrics"])
    assert {"missing_prescribed_reps", "missing_prescribed_load",
            "missing_prescribed_rir"} <= limitations
    assert result["reps"]["unavailable_sets"] == 3


def test_a_zero_set_target_has_a_safe_denominator(conn):
    started = start(conn, item(sets=0))
    log(conn, started)          # an actual set beyond a zero-set prescription
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["prescribed_sets"] == 0
    assert result["matched_sets"] == 0
    assert result["extra_sets"] == 1
    assert result["set_completion"] == {
        "numerator": 0, "denominator": 0, "ratio": None,
    }
    assert result["exercises"][0]["status"] == "over"


def test_time_based_reps_use_seconds_and_load_is_not_scored(conn):
    started = start(conn, item("plank", sets=2, reps_low=60, reps_high=60,
                               load_kg=0, load_basis="bodyweight_total", rir_target=None))
    log(conn, started, exercise_id="plank", load=0, reps=60, rir=None)
    log(conn, started, exercise_id="plank", load=0, reps=45, rir=None)
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["reps"]["unit"] == "seconds"
    assert result["reps"]["within_target"] == 1
    assert result["reps"]["below_target"] == 1
    assert result["load"]["evaluated_sets"] == 0
    assert "time_based_load" in result["quality"]["unavailable_metrics"]
    assert "missing_prescribed_rir" in result["quality"]["unavailable_metrics"]


def test_top_set_and_back_off_targets_come_from_the_set_group(conn):
    top = {"role": "top_set", "sets": 1, "load_kg": 110, "reps_low": 3,
           "reps_high": 5, "rir_target": 1, "percent_of_top": None}
    back = {"role": "back_off", "sets": 1, "load_kg": 90, "reps_low": 3,
            "reps_high": 5, "rir_target": 2, "percent_of_top": 0.82}
    started = start(conn, item(sets=2, reps_low=3, load_kg=90, load_basis="external",
                               set_groups=[top, back]))
    log(conn, started, load=110, reps=3, rir=1, set_role="top_set")
    log(conn, started, load=90, reps=5, rir=2, set_role="back_off")
    result = adherence.analyse(finish(conn, started))["original"]

    rows = result["exercises"][0]["sets"]
    assert [(row["load_target_kg"], row["rir_target"]) for row in rows] == [
        (110.0, 1), (90.0, 2),
    ]
    assert result["load"]["at_target"] == 2
    assert result["rir"]["at_target"] == 2


def test_a_missing_set_role_leaves_group_load_and_rir_unavailable(conn):
    top = {"role": "top_set", "sets": 1, "load_kg": 110, "reps_low": 3,
           "reps_high": 5, "rir_target": 1, "percent_of_top": None}
    back = {"role": "back_off", "sets": 1, "load_kg": 90, "reps_low": 3,
            "reps_high": 5, "rir_target": 2, "percent_of_top": 0.82}
    started = start(conn, item(sets=2, reps_low=3, load_kg=90, load_basis="external",
                               set_groups=[top, back]))
    log(conn, started, load=110, reps=3, rir=1)
    log(conn, started, load=90, reps=5, rir=2)
    result = adherence.analyse(finish(conn, started))["original"]

    assert result["load"]["evaluated_sets"] == 0
    assert result["rir"]["evaluated_sets"] == 0
    assert result["reps"]["evaluated_sets"] == 2      # groups share the rep range
    assert "ambiguous_set_role" in result["quality"]["unavailable_metrics"]


def test_legacy_plan_and_legacy_set_attribution_stay_explicit(conn):
    started = start(conn, item(sets=2))
    assert started["plan"]["items"][0].get("order_index") is None
    workout_id = started["workout_id"]
    conn.execute(
        "INSERT INTO workout_set (workout_id, exercise_id, set_index, load_kg, reps, rir,"
        " source, prescription_item_index) VALUES (?, 'trap_bar_deadlift', 1, 100, 5, 2,"
        " 'manual', 0)",
        (workout_id,),
    )
    conn.execute(
        "INSERT INTO workout_set (workout_id, exercise_id, set_index, load_kg, reps, rir,"
        " source, prescription_item_index) VALUES (?, 'trap_bar_deadlift', 2, 100, 5, 2,"
        " 'manual', NULL)",
        (workout_id,),
    )
    result = adherence.analyse(finish(conn, started))

    assert result["quality"]["legacy_plan_without_order_index"] is True
    original = result["original"]
    assert original["matched_sets"] == 1
    assert original["missing_sets"] == 1
    assert original["extra_sets"] == 1
    assert original["quality"]["unmatched"][0]["reason"] == "unattributed"


def test_a_workout_without_a_prescription_is_unavailable(conn):
    started = start(conn, session_type="technique")
    log(conn, started, exercise_id="competition_squat", load=100)
    result = adherence.analyse(finish(conn, started))

    assert result["status"] == "unavailable"
    assert result["reason"] == "no_prescription_items"
    assert result["original"]["status"] == "unavailable"
    assert result["final_plan"]["status"] == "unavailable"
    assert result["original"]["performed_sets"] == 1
    assert result["original"]["quality"]["unmatched"][0]["reason"] == "no_prescription_items"


def test_legacy_identity_reuse_is_not_reported_as_a_swap(conn):
    started = start(conn, item(sets=2), item("competition_bench_press", sets=2, load_kg=80))
    legacy_plan = {
        "for_date": "2024-01-01",
        "session_type": "hinge",
        "items": [
            item(sets=2),
            item("competition_squat", sets=2, added_during_workout=True),
        ],
    }
    legacy_plan["items"][0]["order_index"] = 0
    legacy_plan["items"][1]["order_index"] = 1   # reused the removed bench identity
    conn.execute(
        "UPDATE workout_session SET plan_modified_json = ? WHERE workout_id = ?",
        (json.dumps(legacy_plan), started["workout_id"]),
    )
    for _ in range(2):
        log(conn, started)
    for _ in range(2):
        log(conn, started, exercise_id="competition_squat", load=100)
    result = adherence.analyse(finish(conn, started))

    assert result["changes"]["swapped"] == []
    assert result["changes"]["removed"] == [{
        "plan_item_index": 1,
        "exercise_id": "competition_bench_press",
        "sets": 2,
        "identity_reused": True,
    }]
    assert result["changes"]["added"] == [{
        "plan_item_index": 1,
        "exercise_id": "competition_squat",
        "sets": 2,
        "identity_reused": True,
    }]
    bench = next(value for value in result["original"]["exercises"]
                 if value["exercise_id"] == "competition_bench_press")
    assert bench["attributable"] is True
    assert bench["status"] == "missing"
    assert result["original"]["quality"]["mismatched_attribution"] == 2
