"""Read-only weekly volume budget (step 1 of the volume-modulation plan)."""

from __future__ import annotations

import json

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.features import programme
from strength_coach.prescribe import build_prescription, volume_budget
from strength_coach.store import db, importer, queries, repositories
from strength_coach.utils import exercises

TODAY = "2026-10-26"


def store_with(rows=None, readiness_rows=None):
    training = make_training(rows or [{
        "Date": TODAY, "Exercise": "Safety Squat Bar", "Weight_Used": "100",
        "RIR": "2", "Reps_Done": "5",
    }])
    readiness = make_readiness(readiness_rows or [{"Date": TODAY}])
    store = db.Store(":memory:")
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    return store


def _prescription(conn, for_date: str = TODAY) -> str:
    run = repositories.start_run(conn, input_hash="test", code_version="test")
    repositories.append_prescription(
        conn, prescription_id="p1", run_id=run.run_id, for_date=for_date,
        session_type="squat", fallback_level="full", rule_document_version="test",
        calibration_ids=(), approved_by="deterministic", items=[],
    )
    return "p1"


def test_weekly_target_matches_the_six_session_template_sum():
    store = db.Store(":memory:")
    try:
        entries = programme.build_programme(
            store.connection, start="2026-10-26", weeks=2, per_week=3,
            start_session_type="bench_squat",
        )
    finally:
        store.close()
    totals = {key: 0 for key in volume_budget.TARGET_KEYS}
    taxonomy = exercises.taxonomy()
    for entry in entries:
        for item in entry.prescription.items:
            key = volume_budget.pattern_key(item.exercise_id, taxonomy)
            if key in totals:
                totals[key] += item.sets
    config = volume_budget.BudgetConfig.load()
    assert {key: totals[key] / 2 for key in totals} == pytest.approx(
        dict(config.weekly_target)
    )


def test_iso_week_is_monday_to_sunday():
    assert volume_budget.week_bounds("2026-10-29") == ("2026-10-26", "2026-11-01")
    assert volume_budget.week_bounds("2026-11-01") == ("2026-10-26", "2026-11-01")


def test_completed_sets_and_sessions_use_working_sets():
    store = store_with([
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "RIR": "2"},
        {"Date": "2026-10-27", "Exercise": "Safety Squat Bar", "RIR": "2"},
        {"Date": "2026-10-28", "Exercise": "Competition Bench Press", "RIR": "2"},
    ])
    try:
        before = volume_budget.completed_sets(
            store.connection, on_date="2026-10-28", include_today=False
        )
        through = volume_budget.completed_sets(
            store.connection, on_date="2026-10-28", include_today=True
        )
        assert before["squat"] == 2 and before["horizontal_push"] == 0
        assert through["squat"] == 2 and through["horizontal_push"] == 1
        assert volume_budget.completed_sessions(store.connection, on_date="2026-10-28") == 3
    finally:
        store.close()


def test_exemptions_lower_the_effective_target_and_report_writes_nothing():
    store = store_with()
    try:
        conn = store.connection
        prescription_id = _prescription(conn)
        repositories.append_volume_exemption(
            conn, prescription_id=prescription_id, effective_on=TODAY,
            pattern="squat", sets=2, source="MOD-FAT-001",
        )
        before = conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0]
        exemptions = conn.execute("SELECT COUNT(*) FROM volume_exemption").fetchone()[0]
        report = volume_budget.report(conn, TODAY)
        after = conn.execute("SELECT COUNT(*) FROM prescription").fetchone()[0]
        after_exemptions = conn.execute("SELECT COUNT(*) FROM volume_exemption").fetchone()[0]
    finally:
        store.close()
    assert report["exempt"]["squat"] == 2
    assert report["effective_targets"]["squat"] == report["targets"]["squat"] - 2
    assert before == after and exemptions == after_exemptions
    assert report["note"].startswith("Read-only")


def test_an_exemption_needs_a_positive_set_count():
    store = db.Store(":memory:")
    try:
        with pytest.raises(ValueError, match="at least one set"):
            repositories.append_volume_exemption(
                store.connection, prescription_id="p1", effective_on=TODAY,
                pattern="squat", sets=0, source="MOD-FAT-001",
            )
    finally:
        store.close()


def test_feasibility_flags_a_frequency_below_the_minimum():
    config = volume_budget.BudgetConfig.load()
    effective = dict(config.weekly_target)
    reachable = volume_budget.feasibility(effective, config, current_frequency=3)
    unreachable = volume_budget.feasibility(effective, config, current_frequency=1)
    assert reachable["min_sessions"] == 2
    assert reachable["reachable"] is True
    assert unreachable["reachable"] is False
    assert unreachable["unreachable_sets"] == 27.0


def _rows():
    return [
        {"exercise_id": "ssb_squat", "sets": 5, "essential": True, "rest_s": 180,
         "key": "squat"},
        {"exercise_id": "dumbbell_row", "sets": 3, "essential": False, "rest_s": 90,
         "key": "horizontal_pull"},
        {"exercise_id": "ab_wheel", "sets": 3, "essential": False, "rest_s": 90,
         "key": "core"},
    ]


def _effective(**values):
    out = {key: 0.0 for key in volume_budget.TARGET_KEYS}
    out.update(values)
    return out


def test_plan_tops_up_to_the_bottom_of_the_band():
    plan = volume_budget.plan_session(
        _rows(), completed={}, future_sets=[],
        effective=_effective(squat=5, horizontal_pull=6, core=3),
        config=volume_budget.BudgetConfig(), time_cap_minutes=80,
    )
    assert plan["action"] == "top_up"
    assert plan["total_before"] == 11.0
    assert plan["total_after"] == 13.0
    assert plan["added"] == [{"exercise_id": "dumbbell_row", "key": "horizontal_pull",
                              "delta": 2}]


def test_plan_trims_accessories_but_never_essentials():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 10, "essential": True, "rest_s": 180,
         "key": "squat"},
        {"exercise_id": "dumbbell_row", "sets": 8, "essential": False, "rest_s": 90,
         "key": "horizontal_pull"},
        {"exercise_id": "ab_wheel", "sets": 8, "essential": False, "rest_s": 90,
         "key": "core"},
    ]
    plan = volume_budget.plan_session(
        rows, completed={}, future_sets=[],
        effective=_effective(squat=10, horizontal_pull=1, core=1),
        config=volume_budget.BudgetConfig(), time_cap_minutes=80,
    )
    assert plan["action"] == "trim"
    assert plan["after"]["squat"] == 10
    assert plan["after"]["horizontal_pull"] == 2
    assert plan["after"]["core"] == 1
    assert plan["total_after"] == 13.0
    assert plan["truncated"] is False


def test_the_session_cap_stops_a_top_up():
    plan = volume_budget.plan_session(
        _rows(), completed={}, future_sets=[],
        effective=_effective(squat=10, horizontal_pull=10, core=10),
        config=volume_budget.BudgetConfig(session_cap_total=12), time_cap_minutes=80,
    )
    assert plan["action"] == "top_up"
    assert plan["total_after"] == 12.0
    assert plan["unreachable_sets"] > 0


def test_the_time_cap_stops_a_top_up():
    plan = volume_budget.plan_session(
        _rows(), completed={}, future_sets=[],
        effective=_effective(squat=10, horizontal_pull=10, core=10),
        config=volume_budget.BudgetConfig(), time_cap_minutes=1,
    )
    assert plan["time_bound"] is True
    assert plan["added"] == []


def test_top_up_capacity_is_zero_where_no_accessory_exists():
    config = volume_budget.BudgetConfig.load()
    hinge = volume_budget.top_up_capacity(
        volume_budget.template_rows("hinge"), config=config
    )
    assert hinge["hinge"]["sets"] == 0          # trap bar is essential
    assert hinge["horizontal_pull"]["sets"] > 0  # dumbbell row is not

    bench_squat = volume_budget.top_up_capacity(
        volume_budget.template_rows("bench_squat"), config=config
    )
    assert bench_squat["squat"]["sets"] == 0          # competition squat is essential
    assert bench_squat["horizontal_push"]["sets"] == 0  # bench is essential

    bench_hinge = volume_budget.top_up_capacity(
        volume_budget.template_rows("bench_hinge"), config=config
    )
    assert bench_hinge["hinge"]["sets"] > 0      # sumo is non-essential on this day


def test_per_pattern_status_catches_a_group_deficit_the_total_hides():
    config = volume_budget.BudgetConfig.load()
    effective = _effective(
        squat=10, hinge=6.5, horizontal_push=12, horizontal_pull=9,
        vertical_push=3, vertical_pull=4.5, core=6,
    )
    projected = {key: 0.0 for key in volume_budget.TARGET_KEYS}
    projected.update({
        "squat": 10, "hinge": 4, "horizontal_push": 13, "horizontal_pull": 9,
        "vertical_push": 3, "vertical_pull": 4.5, "core": 6,
        "erector_extension": 3, "power_jump": 3,
    })
    diag = volume_budget.per_pattern_status(
        targets=config.weekly_target,
        effective=effective,
        completed={},
        projected=projected,
        rows=volume_budget.template_rows("hinge"),
        config=config,
        persistent={"hinge": {"status": "under", "average": 4.0}},
    )
    assert diag["hinge"]["status"] == "under"
    assert diag["hinge"]["short"] == 2.5
    assert diag["hinge"]["top_up_capacity"]["sets"] == 0
    assert diag["hinge"]["persistent"]["status"] == "under"
    assert diag["squat"]["status"] == "within"


def test_report_includes_the_per_pattern_diagnosis():
    store = store_with()
    try:
        report = volume_budget.report(store.connection, TODAY)
    finally:
        store.close()
    assert set(report["per_pattern"]) == set(volume_budget.MANAGED_KEYS)
    hinge = report["per_pattern"]["hinge"]
    assert hinge["target"] == 6.5
    assert "top_up_capacity" in hinge
    assert "persistent" in hinge


def test_allocate_items_trims_an_over_group_and_keeps_essentials():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 5, "essential": True, "rest_s": 180,
         "key": "squat"},
        {"exercise_id": "split_squat", "sets": 4, "essential": False, "rest_s": 90,
         "key": "squat"},
        {"exercise_id": "dumbbell_row", "sets": 3, "essential": False, "rest_s": 90,
         "key": "horizontal_pull"},
    ]
    result = volume_budget.allocate_items(
        rows, effective=_effective(squat=5, horizontal_pull=3), completed={},
        future_sets=[], persistent={}, config=volume_budget.BudgetConfig(),
        time_cap_minutes=80,
    )
    assert result["actions"]["squat"] == "over"
    assert result["rows"][0]["sets"] == 5
    assert result["rows"][1]["sets"] == 1
    assert result["changed"] == [{"exercise_id": "split_squat", "key": "squat",
                                  "delta": -3}]


def test_allocate_items_tops_up_an_under_group_within_capacity():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 3, "essential": True, "rest_s": 180,
         "key": "squat"},
        {"exercise_id": "split_squat", "sets": 1, "essential": False, "rest_s": 90,
         "key": "squat"},
        {"exercise_id": "dumbbell_row", "sets": 3, "essential": False, "rest_s": 90,
         "key": "horizontal_pull"},
    ]
    result = volume_budget.allocate_items(
        rows, effective=_effective(squat=8, horizontal_pull=6), completed={},
        future_sets=[], persistent={}, config=volume_budget.BudgetConfig(),
        time_cap_minutes=80,
    )
    assert result["actions"]["squat"] == "under"
    assert result["rows"][0]["sets"] == 3
    assert result["rows"][1]["sets"] >= 4
    assert result["rows"][2]["sets"] >= 4


def test_allocate_items_does_not_re_add_a_safety_cut():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 3, "essential": True, "rest_s": 180,
         "key": "squat"},
        {"exercise_id": "split_squat", "sets": 1, "essential": False, "rest_s": 90,
         "key": "squat"},
    ]
    result = volume_budget.allocate_items(
        rows, effective=_effective(squat=8), completed={}, future_sets=[],
        persistent={}, config=volume_budget.BudgetConfig(), time_cap_minutes=80,
        safety_keys={"squat"},
    )
    assert result["rows"][1]["sets"] == 1
    assert any("safety cut" in item for item in result["blocked"])


def test_record_exemptions_writes_the_safety_cut():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        run = repositories.start_run(conn, input_hash="test", code_version="test")
        repositories.append_prescription(
            conn, prescription_id="p1", run_id=run.run_id, for_date=TODAY,
            session_type="squat", fallback_level="full", rule_document_version="test",
            calibration_ids=(), approved_by="deterministic", items=[],
        )
        volume_budget.record_exemptions(
            conn, prescription_id="p1", effective_on=TODAY, session_type="squat",
            items=[
                {"exercise_id": "ssb_squat", "sets": 4,
                 "rationale_refs": ["MOD-FAT-001"]},
                {"exercise_id": "bench_press", "sets": 4,
                 "rationale_refs": ["MOD-VOL-003"]},
            ],
        )
        rows = queries.volume_exemptions(conn, start=TODAY, end=TODAY)
    finally:
        store.close()
    assert [(row["pattern"], row["sets"], row["source"]) for row in rows] == [
        ("squat", 1, "MOD-FAT-001")
    ]


def _profile(conn, *, enabled: bool):
    current = queries.athlete_profile(conn) or {}
    repositories.append_athlete_profile(
        conn, effective_from=TODAY, primary_goal=current.get("primary_goal") or "strength",
        goal_rank=current.get("goal_rank") and json.loads(current["goal_rank"]) or ["strength"],
        focus_lifts=[], competition_date=None, sessions_per_week_target=3,
        max_session_minutes=90, block_start_date=None,
        volume_budget_enabled=enabled, main_lift_policy="preserve",
    )


def test_the_budget_is_off_by_default_and_enabled_by_the_profile():
    store = store_with()
    try:
        off = volume_budget.apply(
            (), conn=store.connection, context=None, for_date=TODAY,
            session_type="squat",
        )
        _profile(store.connection, enabled=True)
        on = volume_budget.apply(
            (), conn=store.connection, context=None, for_date=TODAY,
            session_type="squat",
        )
    finally:
        store.close()
    assert off[2]["enabled"] is False
    assert on[2]["enabled"] is True


def test_the_budget_note_is_wired_into_the_prescription():
    store = store_with()
    try:
        _profile(store.connection, enabled=False)
        off = build_prescription(
            store.connection, for_date=TODAY, session_type="squat",
        )
        _profile(store.connection, enabled=True)
        on = build_prescription(
            store.connection, for_date=TODAY, session_type="squat",
        )
    finally:
        store.close()
    assert off.notes["volume_budget"]["enabled"] is False
    assert on.notes["volume_budget"]["enabled"] is True


def test_cli_updates_the_budget_profile(tmp_path, capsys):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    repositories.append_athlete_profile(
        store.connection, effective_from=TODAY, primary_goal="strength",
        goal_rank=["strength"], focus_lifts=[], competition_date=None,
        sessions_per_week_target=3, max_session_minutes=90, block_start_date=None,
        volume_budget_enabled=False, main_lift_policy="preserve",
    )
    store.close()
    assert cli.main(["--db", str(path), "state", "--volume-budget", "on"]) == 0
    reopened = db.Store(path)
    try:
        profile = queries.athlete_profile(reopened.connection)
    finally:
        reopened.close()
    assert profile["volume_budget_enabled"] == 1
    assert profile["main_lift_policy"] == "preserve"


def test_cli_prints_the_read_only_budget(tmp_path, capsys):
    path = tmp_path / "coach.db"
    store = db.Store(path)
    training = make_training([{
        "Date": TODAY, "Exercise": "Safety Squat Bar", "RIR": "2",
    }])
    readiness = make_readiness([{"Date": TODAY}])
    importer.import_export(
        store.connection, training, readiness,
        training_sha256=importer.sha256_frame(training),
        readiness_sha256=importer.sha256_frame(readiness),
    )
    store.close()
    assert cli.main(["--db", str(path), "volume", "--budget", "--date", TODAY]) == 0
    out = capsys.readouterr().out
    assert "volume budget" in out and "read-only" in out