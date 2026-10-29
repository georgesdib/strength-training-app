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
    # 63 = 57 + 6 knee-flexion sets (DEC-KNEEFLEX-01). The template sum and the explicit
    # total must move together, which is what this test protects.
    assert config.total_target() == 63


def test_weekly_total_is_explicit_and_must_match_the_category_sum(tmp_path):
    source = volume_budget.BudgetConfig.load().source_path
    text = source.read_text(encoding="utf-8")
    mismatch = tmp_path / "mismatch.yaml"
    mismatch.write_text(
        text.replace("  weekly_total: 63", "  weekly_total: 66"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="weekly_total"):
        volume_budget.BudgetConfig.load(mismatch)
    consistent = tmp_path / "consistent.yaml"
    consistent.write_text(
        text.replace("  weekly_total: 63", "  weekly_total: 66").replace(
            "    squat: 10", "    squat: 13"
        ).replace(
            "  weekly_total_effective: 74.25", "  weekly_total_effective: 77.25"
        ),
        encoding="utf-8",
    )
    config = volume_budget.BudgetConfig.load(consistent)
    assert config.total_target() == 66
    assert config.weekly_target["squat"] == 13


def test_reduce_floor_is_configurable_and_validated(tmp_path):
    source = volume_budget.BudgetConfig.load().source_path
    text = source.read_text(encoding="utf-8")
    assert volume_budget.BudgetConfig.load().main_lift_floor == 3
    zero = tmp_path / "zero.yaml"
    zero.write_text(
        text.replace("  main_lift_floor: 3", "  main_lift_floor: 0"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="main_lift_floor"):
        volume_budget.BudgetConfig.load(zero)
    two = tmp_path / "two.yaml"
    two.write_text(
        text.replace("  main_lift_floor: 3", "  main_lift_floor: 2"), encoding="utf-8"
    )
    assert volume_budget.BudgetConfig.load(two).main_lift_floor == 2


def test_all_budget_parameters_are_config_backed(tmp_path):
    source = volume_budget.BudgetConfig.load().source_path
    text = source.read_text(encoding="utf-8")
    changed = (
        text.replace("  main_lift_floor: 3", "  main_lift_floor: 2")
        .replace("  trim_enabled: true", "  trim_enabled: false")
        .replace("  top_up_enabled: true", "  top_up_enabled: false")
        .replace("  band_min: 1", "  band_min: 2")
        .replace("  min_accessory_sets: 1", "  min_accessory_sets: 2")
        .replace("  top_up_max_sets_per_item: 8", "  top_up_max_sets_per_item: 6")
        .replace("  set_seconds: 30", "  set_seconds: 45")
        .replace("    total: 30", "    total: 24")
        .replace("    squat: 8", "    squat: 7")
        .replace("  tolerance: 0.10", "  tolerance: 0.20")
        .replace("  warmup_estimate_minutes: 5", "  warmup_estimate_minutes: 4")
        .replace("  session_time_cap_minutes: 80", "  session_time_cap_minutes: 70")
    )
    path = tmp_path / "all.yaml"
    path.write_text(changed, encoding="utf-8")
    config = volume_budget.BudgetConfig.load(path)
    assert config.main_lift_floor == 2
    assert config.trim_enabled is False
    assert config.top_up_enabled is False
    assert config.band_min == 2
    assert config.min_accessory_sets == 2
    assert config.top_up_max_sets_per_item == 6
    assert config.set_seconds == 45
    assert config.session_cap_total == 24
    assert config.session_cap_pattern["squat"] == 7
    assert config.tolerance == 0.20
    assert config.warmup_estimate_minutes == 4
    assert config.session_time_cap_minutes == 70


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
    # 63 sets against the 30-set session cap needs three sessions; adding knee flexion moved
    # this from two, so a two-session week is now correctly flagged instead of silently
    # overloaded.
    assert reachable["min_sessions"] == 3
    assert reachable["reachable"] is True
    assert unreachable["reachable"] is False
    assert unreachable["unreachable_sets"] == 33.0


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
    assert bench_hinge["hinge"]["sets"] == 0     # sumo is essential on this day


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


def _profile(
    conn, *, enabled: bool, policy: str = "preserve", sessions: int = 3,
    competition: str | None = None,
):
    current = queries.athlete_profile(conn) or {}
    repositories.append_athlete_profile(
        conn, effective_from=TODAY, primary_goal=current.get("primary_goal") or "strength",
        goal_rank=current.get("goal_rank") and json.loads(current["goal_rank"]) or ["strength"],
        focus_lifts=[], competition_date=competition, sessions_per_week_target=sessions,
        max_session_minutes=90, block_start_date=None,
        volume_budget_enabled=enabled, main_lift_policy=policy,
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


def test_reduce_trims_only_a_filled_groups_main_lift():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 5, "essential": True, "main_lift": True,
         "key": "squat", "rest_s": 180},
        {"exercise_id": "box_jump", "sets": 3, "essential": True, "main_lift": False,
         "key": "power_jump", "rest_s": 90},
        {"exercise_id": "split_squat", "sets": 4, "essential": False, "main_lift": False,
         "key": "squat", "rest_s": 90},
    ]
    result = volume_budget.reduce_filled_main_lifts(
        rows, completed={"squat": 10}, effective={"squat": 10}, floor=3,
    )
    assert result["rows"][0]["sets"] == 3
    assert result["rows"][1]["sets"] == 3
    assert result["rows"][2]["sets"] == 4
    assert result["changed"] == [{"exercise_id": "ssb_squat", "key": "squat",
                                  "delta": -2}]


def test_reduce_keeps_an_unfilled_lift_and_a_safety_cut():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 5, "essential": True, "main_lift": True,
         "key": "squat", "rest_s": 180},
        {"exercise_id": "bench_press", "sets": 4, "essential": True, "main_lift": True,
         "key": "horizontal_push", "rest_s": 180, "refs": ["MOD-FAT-001"]},
    ]
    result = volume_budget.reduce_filled_main_lifts(
        rows, completed={"squat": 4, "horizontal_push": 12},
        effective={"squat": 10, "horizontal_push": 12}, floor=3,
    )
    assert [row["sets"] for row in result["rows"]] == [5, 4]
    assert result["changed"] == []


def test_reduce_mode_does_not_top_up_another_group():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 5, "essential": True, "main_lift": True,
         "key": "squat", "rest_s": 180},
        {"exercise_id": "dumbbell_row", "sets": 1, "essential": False, "main_lift": False,
         "key": "horizontal_pull", "rest_s": 90},
    ]
    reduced = volume_budget.reduce_filled_main_lifts(
        rows, completed={"squat": 10}, effective={"squat": 10}, floor=3,
    )
    result = volume_budget.allocate_items(
        reduced["rows"], effective=_effective(squat=10, horizontal_pull=9),
        completed={"squat": 10}, future_sets=[], persistent={},
        config=volume_budget.BudgetConfig(), time_cap_minutes=80,
        allow_top_up=False,
    )
    assert result["rows"][1]["sets"] == 1
    assert any("top-up disabled" in item for item in result["blocked"])


def test_reduce_engine_slice_honours_the_profile():
    rows = [
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(5)
    ] + [
        {"Date": "2026-10-27", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(5)
    ]
    store = store_with(rows)
    try:
        _profile(store.connection, enabled=True, policy="reduce")
        reduced = build_prescription(
            store.connection, for_date="2026-10-29", session_type="squat",
        )
        _profile(store.connection, enabled=True, policy="preserve")
        preserved = build_prescription(
            store.connection, for_date="2026-10-29", session_type="squat",
        )
    finally:
        store.close()
    reduced_ssb = next(i for i in reduced.items if i.exercise_id == "ssb_squat")
    preserved_ssb = next(i for i in preserved.items if i.exercise_id == "ssb_squat")
    assert reduced_ssb.sets == 3
    assert "MOD-VOL-003" in reduced_ssb.rationale_refs
    assert preserved_ssb.sets == 5
    assert reduced.notes["volume_budget"]["main_lift_reduce"]


def test_compensation_prefers_bench_over_hinge_in_one_slot():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 5, "essential": True, "rest_s": 180,
         "key": "squat"},
        {"exercise_id": "split_squat", "sets": 3, "essential": False, "rest_s": 90,
         "key": "squat"},
    ]
    result = volume_budget.simulate_compensation(
        session_type="squat",
        rows=rows,
        completed={"squat": 10},
        effective={"squat": 10, "horizontal_push": 12, "hinge": 6.5},
        projected={"squat": 13, "horizontal_push": 10, "hinge": 5},
        config=volume_budget.BudgetConfig(compensation_enabled=True),
    )
    assert result["status"] == "simulated"
    assert result["freed"] == {"squat": 3}
    assert result["selected"]["group"] == "horizontal_push"
    assert result["selected"]["exercise_id"] == "dumbbell_bench_press"
    assert result["selected"]["sets"] == 2
    assert result["selected"]["weight"] == 0.8
    assert [row["group"] for row in result["candidates"]] == [
        "horizontal_push", "hinge"
    ]


def test_compensation_needs_a_filled_accessory_and_is_off_by_default():
    rows = [
        {"exercise_id": "split_squat", "sets": 3, "essential": False, "rest_s": 90,
         "key": "squat"},
    ]
    not_filled = volume_budget.simulate_compensation(
        session_type="squat", rows=rows, completed={"squat": 0},
        effective={"squat": 10}, projected={"squat": 3},
        config=volume_budget.BudgetConfig(compensation_enabled=True),
    )
    disabled = volume_budget.simulate_compensation(
        session_type="squat", rows=rows, completed={"squat": 10},
        effective={"squat": 10}, projected={"squat": 13},
        config=volume_budget.BudgetConfig(),
    )
    assert not_filled["status"] == "no_filled_accessory"
    assert not_filled["selected"] is None
    assert disabled["status"] == "disabled"


def test_compensation_caps_at_the_weekly_high_band():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 5, "essential": True, "rest_s": 180,
         "key": "squat"},
        {"exercise_id": "split_squat", "sets": 3, "essential": False, "rest_s": 90,
         "key": "squat"},
    ]
    result = volume_budget.simulate_compensation(
        session_type="squat", rows=rows, completed={"squat": 10},
        effective={"squat": 10, "horizontal_push": 10},
        projected={"squat": 13, "horizontal_push": 8},
        config=volume_budget.BudgetConfig(compensation_enabled=True),
    )
    assert result["status"] == "simulated"
    assert result["selected"]["sets"] == 1  # only 1 set of high-band headroom


def test_compensation_does_not_add_when_weekly_total_is_full():
    rows = [
        {"exercise_id": "ssb_squat", "sets": 5, "essential": True, "rest_s": 180,
         "key": "squat"},
        {"exercise_id": "split_squat", "sets": 3, "essential": False, "rest_s": 90,
         "key": "squat"},
    ]
    result = volume_budget.simulate_compensation(
        session_type="squat", rows=rows, completed={"squat": 10},
        effective={"squat": 10, "horizontal_push": 10},
        projected={"squat": 13, "horizontal_push": 10},
        config=volume_budget.BudgetConfig(compensation_enabled=True),
    )
    assert result["status"] == "weekly_full"
    assert result["selected"] is None


def test_compensation_apply_is_enabled_for_the_engine():
    rows = [
        {"exercise_id": "split_squat", "sets": 3, "essential": False, "rest_s": 90,
         "key": "squat"},
    ]
    result = volume_budget.simulate_compensation(
        session_type="squat", rows=rows, completed={"squat": 10},
        effective={"squat": 10, "horizontal_push": 12},
        projected={"squat": 13, "horizontal_push": 10},
        config=volume_budget.BudgetConfig(
            compensation_enabled=True, compensation_apply=True,
        ),
    )
    assert result["status"] == "simulated"
    assert result["selected"] is not None
    assert "Application is enabled" in result["note"]


def test_compensation_config_is_loaded_and_defaults_to_preview_only():
    config = volume_budget.BudgetConfig.load()
    assert config.compensation_enabled is True
    assert config.compensation_apply is True
    assert config.compensation_floor == 0.1
    assert config.compensation_similarity["squat"]["hinge"] == 0.7
    assert config.compensation_slots["squat"][0]["exercise_id"] == (
        "dumbbell_bench_press"
    )


def test_compensation_applies_the_selected_slot_with_a_real_load():
    rows = [
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(10)
    ] + [
        {"Date": "2026-10-26", "Exercise": "Dumbbell Bench Press", "Weight_Used": "20",
         "RIR": "2", "Reps_Done": "10"}
        for _ in range(2)
    ]
    store = store_with(rows)
    try:
        _profile(store.connection, enabled=True, policy="preserve", sessions=1)
        prescription = build_prescription(
            store.connection, for_date="2026-10-29", session_type="hinge",
        )
    finally:
        store.close()
    added = [
        item for item in prescription.items
        if item.exercise_id == "dumbbell_bench_press"
    ]
    assert len(added) == 1
    selected = prescription.notes["compensation"]["selected"]
    # The slot is capped by the candidate's configured sets, the cross-group shortfall and the
    # weekly headroom; a later under-MEV rule may then add a set to the item.
    assert 1 <= selected["sets"] <= 3
    assert added[0].sets >= selected["sets"]
    assert "MOD-VOL-004" in added[0].rationale_refs
    assert prescription.notes["compensation"]["status"] == "applied"


def test_compensation_refuses_without_an_executable_load():
    rows = [
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(10)
    ]
    store = store_with(rows)
    try:
        _profile(store.connection, enabled=True, policy="preserve", sessions=1)
        prescription = build_prescription(
            store.connection, for_date="2026-10-29", session_type="hinge",
        )
    finally:
        store.close()
    assert not any(
        item.exercise_id == "dumbbell_bench_press" for item in prescription.items
    )
    assert prescription.notes["compensation"]["status"] == "refused"
    assert any("MOD-VOL-004" in warning for warning in prescription.warnings)


def test_compensation_falls_back_to_a_recorded_e1rm():
    rows = [
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(10)
    ]
    store = store_with(rows)
    try:
        repositories.append_e1rm_override(
            store.connection, exercise_id="dumbbell_bench_press", e1rm_kg=30.0,
            effective_from="2026-10-26", reason="test compensation",
        )
        _profile(store.connection, enabled=True, policy="preserve", sessions=1)
        prescription = build_prescription(
            store.connection, for_date="2026-10-29", session_type="hinge",
        )
    finally:
        store.close()
    added = [
        item for item in prescription.items
        if item.exercise_id == "dumbbell_bench_press"
    ]
    assert len(added) == 1
    assert added[0].load_kg is not None
    assert "MOD-VOL-004" in added[0].rationale_refs
    assert prescription.notes["compensation"]["status"] == "applied"


def test_drop_config_is_loaded():
    config = volume_budget.BudgetConfig.load()
    assert config.drop_enabled is True
    assert config.drop_competition_confirm_days == 7
    assert config.drop_max_slots_per_group == 1
    assert config.drop_slots["horizontal_push"][0]["exercise_id"] == (
        "dumbbell_bench_press"
    )


def test_drop_uses_a_technique_session_at_the_high_band():
    rows = [
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(63)
    ]
    store = store_with(rows)
    try:
        _profile(store.connection, enabled=True, policy="drop", sessions=1)
        prescription = build_prescription(
            store.connection, for_date="2026-10-29", session_type="hinge",
        )
    finally:
        store.close()
    assert prescription.session_type == "technique"
    assert prescription.items == ()
    assert any("MOD-VOL-005" in warning for warning in prescription.warnings)


def test_drop_builds_a_volume_fill_session():
    rows = [
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(10)
    ] + [
        {"Date": "2026-10-26", "Exercise": "Dumbbell Bench Press", "Weight_Used": "20",
         "RIR": "2", "Reps_Done": "10"}
        for _ in range(2)
    ]
    store = store_with(rows)
    try:
        _profile(store.connection, enabled=True, policy="drop", sessions=1)
        prescription = build_prescription(
            store.connection, for_date="2026-10-29", session_type="hinge",
        )
    finally:
        store.close()
    assert prescription.session_type == "volume_fill_hinge"
    assert not any(item.exercise_id == "split_squat" for item in prescription.items)
    assert any(
        item.exercise_id == "dumbbell_bench_press" for item in prescription.items
    )
    assert prescription.notes["drop"]["original_session_type"] == "hinge"
    assert any("MOD-VOL-005" in warning for warning in prescription.warnings)


def test_drop_window_is_inclusive_and_shared_with_the_ui():
    cfg = volume_budget.BudgetConfig()
    profile = {
        "volume_budget_enabled": 1,
        "main_lift_policy": "drop",
        "competition_date": "2026-11-01",
    }
    assert volume_budget.drop_mode_active(profile, cfg) is True
    assert volume_budget.drop_competition_window(profile, "2026-10-25", 7)["in_window"] is True
    assert volume_budget.drop_competition_window(profile, "2026-10-24", 7)["in_window"] is False
    assert volume_budget.drop_competition_window(profile, "2026-11-01", 7)["in_window"] is True
    assert volume_budget.drop_competition_window(profile, "2026-11-02", 7)["in_window"] is False
    assert volume_budget.drop_competition_window(
        {**profile, "competition_date": None}, "2026-10-25", 7
    )["in_window"] is False
    assert volume_budget.drop_mode_active({**profile, "volume_budget_enabled": 0}, cfg) is False
    assert volume_budget.drop_mode_active({**profile, "main_lift_policy": "preserve"}, cfg) is False


def test_drop_requires_confirmation_in_the_competition_window():
    rows = [
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(10)
    ]
    store = store_with(rows)
    try:
        _profile(
            store.connection, enabled=True, policy="drop", sessions=1,
            competition="2026-11-01",
        )
        held = build_prescription(
            store.connection, for_date="2026-10-29", session_type="hinge",
        )
        confirmed = build_prescription(
            store.connection, for_date="2026-10-29", session_type="hinge",
            drop_confirmed=True,
        )
    finally:
        store.close()
    assert held.session_type == "hinge"
    assert any("drop held" in warning for warning in held.warnings)
    assert confirmed.session_type == "volume_fill_hinge"


def test_schedule_maps_a_volume_fill_to_its_original_family():
    from strength_coach.prescribe import schedule
    assert schedule._family("volume_fill_squat") == "squat"
    assert schedule._family("volume_fill_bench_hinge") == "bench"
    assert schedule._family("technique") is None


def test_programme_forecast_uses_the_derived_type():
    rows = [
        {"Date": "2026-10-26", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
         "RIR": "2", "Reps_Done": "5"}
        for _ in range(10)
    ]
    store = store_with(rows)
    try:
        _profile(store.connection, enabled=True, policy="drop", sessions=1)
        entries = programme.build_programme(
            store.connection, start="2026-10-29", weeks=1, per_week=1,
            start_session_type="hinge",
        )
    finally:
        store.close()
    assert len(entries) == 1
    assert entries[0].session_type == entries[0].prescription.session_type


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


def test_report_includes_the_compensation_preview():
    store = store_with()
    try:
        report = volume_budget.report(store.connection, TODAY)
    finally:
        store.close()
    assert "compensation" in report
    assert "status" in report["compensation"]


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
    assert "compensation" in out