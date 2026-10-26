"""Read-only weekly volume budget (step 1 of the volume-modulation plan)."""

from __future__ import annotations

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.features import programme
from strength_coach.prescribe import volume_budget
from strength_coach.store import db, importer, repositories
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
