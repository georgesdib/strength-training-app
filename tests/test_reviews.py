"""Periodic review reminders are prompts; only human acknowledgements are written."""

from __future__ import annotations

import datetime as dt

from conftest import make_readiness, make_training

from strength_coach import history
from strength_coach.features import reviews
from strength_coach.store import db, importer, repositories


def test_phase3_research_is_a_visible_planned_follow_up():
    store = db.Store(":memory:")
    try:
        tasks = reviews.status(store.connection, "2024-01-01")["tasks"]
        task = next(t for t in tasks if t["key"] == "injury_attribution_phase3")
        assert task["status"] == "planned"
        assert task["kind"] == "roadmap"
        assert task["periodic"] is False
        assert "Phase 3" in task["label"]
        assert any("pre-register" in step.lower() for step in task["steps"])
    finally:
        store.close()


def test_readiness_review_is_due_then_completed_and_snoozed():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        initial = reviews.status(conn, "2024-01-01")
        readiness = next(t for t in initial["tasks"] if t["key"] == "readiness_thresholds")
        assert readiness["status"] == "due"
        assert readiness["periodic"] is True

        repositories.append_maintenance_review(
            conn, task_key="readiness_thresholds", action="completed",
            reviewed_on="2024-01-01", decision="kept", note="no change",
        )
        after = next(
            t for t in reviews.status(conn, "2024-01-02")["tasks"]
            if t["key"] == "readiness_thresholds"
        )
        assert after["status"] == "not_due"
        assert after["due_on"] == (dt.date(2024, 1, 1) + dt.timedelta(weeks=12)).isoformat()

        repositories.append_maintenance_review(
            conn, task_key="readiness_thresholds", action="snoozed",
            reviewed_on="2024-01-02", snoozed_until="2024-01-16",
        )
        snoozed = next(
            t for t in reviews.status(conn, "2024-01-10")["tasks"]
            if t["key"] == "readiness_thresholds"
        )
        assert snoozed["status"] == "snoozed"
    finally:
        store.close()


def test_enabling_the_volume_budget_adds_no_standing_review_reminder():
    # The "Volume review (standing)" card was removed from Today on 2026-11-22: it had no clock
    # and no acknowledgement, so it read as a permanent warning. The budget is inspected in the
    # Prescribe volume panels, and enabling it must not resurrect the reminder.
    store = db.Store(":memory:")
    try:
        conn = store.connection
        before = [t["key"] for t in reviews.status(conn, "2026-10-26")["tasks"]]
        repositories.append_athlete_profile(
            conn, effective_from="2026-10-26",
            volume_budget_enabled=True,
        )
        after = [t["key"] for t in reviews.status(conn, "2026-10-26")["tasks"]]
    finally:
        store.close()
    assert "volume_review" not in before
    assert after == before


def test_review_status_reports_data_gaps_without_writing():
    store = db.Store(":memory:")
    try:
        report = reviews.status(store.connection, "2024-01-01")
    finally:
        store.close()
    tasks = {task["key"]: task for task in report["tasks"]}
    # The rubric calibration prompt is retired (DEC-EVAL-08); its absence is the contract.
    assert "rubric_labels" not in tasks
    assert tasks["srpe_coverage"]["status"] == "attention"
    assert tasks["readiness_baseline"]["status"] == "insufficient"
    assert tasks["back_pattern"]["status"] == "ok"


def test_back_pattern_review_only_fires_on_an_actual_flare():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        repositories.append_symptom(
            conn, logged_on="2024-01-10", timing="pre_session", region="low_back", level=0,
        )
        task = next(
            item for item in reviews.status(conn, "2024-01-10")["tasks"]
            if item["key"] == "back_pattern"
        )
        assert task["status"] == "ok"
        assert task["doc"] == "docs/SYMPTOM-LOGGING.md"

        repositories.append_symptom(
            conn, logged_on="2024-01-11", timing="pre_session", region="low_back", level=2,
        )
        task = next(
            item for item in reviews.status(conn, "2024-01-11")["tasks"]
            if item["key"] == "back_pattern"
        )
        assert task["status"] == "attention"
        assert "flare" in task["summary"].lower()
    finally:
        store.close()


def test_substitution_review_is_a_periodic_task():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        report = reviews.status(conn, "2024-01-01")
        task = next(t for t in report["tasks"] if t["key"] == "exercise_substitution")
        assert task["status"] == "due"
        assert task["periodic"] is True
        repositories.append_maintenance_review(
            conn, task_key="exercise_substitution", action="completed",
            reviewed_on="2024-01-01", decision="kept", note="suggestions still useful",
        )
        after = next(
            t for t in reviews.status(conn, "2024-01-02")["tasks"]
            if t["key"] == "exercise_substitution"
        )
        assert after["status"] == "not_due"
    finally:
        store.close()

def test_the_fatigue_signal_review_is_periodic_and_points_at_the_adr():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        task = next(
            t for t in reviews.status(conn, "2024-01-01")["tasks"]
            if t["key"] == "fatigue_signals"
        )
        assert task["periodic"] is True
        assert task["status"] == "due"
        assert task["doc"] == "docs/FATIGUE-SIGNALS.md"
        assert any("Shadow review" in step for step in task["steps"])
        repositories.append_maintenance_review(
            conn, task_key="fatigue_signals", action="completed",
            reviewed_on="2024-01-01", decision="kept", note="no change",
        )
        after = next(
            t for t in reviews.status(conn, "2024-01-02")["tasks"]
            if t["key"] == "fatigue_signals"
        )
        assert after["status"] == "not_due"
        assert after["due_on"] == (dt.date(2024, 1, 1) + dt.timedelta(weeks=8)).isoformat()
        assert reviews.snooze_days("fatigue_signals") == 14
    finally:
        store.close()


def test_afc_followups_are_tracked_and_wait_for_the_gate():
    from strength_coach.store import repositories

    store = db.Store(":memory:")
    try:
        conn = store.connection
        tasks = {task["key"]: task for task in reviews.status(conn, "2026-11-13")["tasks"]}
        assert tasks["afc_device_acceptance"]["status"] == "attention"
        assert tasks["afc_device_acceptance"]["periodic"] is True
        assert tasks["afc_5a_historical"]["status"] == "waiting"
        assert tasks["afc_5a_historical"]["due_on"] == "2027-01-23"

        after_gate = {
            task["key"]: task for task in reviews.status(conn, "2027-02-01")["tasks"]
        }
        assert after_gate["afc_5a_historical"]["status"] == "due"

        repositories.append_maintenance_review(
            conn, task_key="afc_device_acceptance", action="completed",
            reviewed_on="2026-11-13", decision="not_applicable",
        )
        done = {
            task["key"]: task for task in reviews.status(conn, "2026-11-14")["tasks"]
        }
        assert done["afc_device_acceptance"]["status"] == "done"
    finally:
        store.close()


def _one_telemetry_session(conn):
    """One imported session carrying a watch execution event and a linked workout.

    The app creates the session and the workout under the same identifier, so the fixture does
    too; a made-up workout id would test a shape production never writes.
    """
    imported = history.list_sessions(conn)["sessions"][0]["session_id"]
    conn.execute(
        "INSERT INTO workout_session (workout_id, for_date, plan_json, readiness_json, started_at)"
        " VALUES (?, '2024-01-01', '{}', '{}', '2024-01-01T18:00:00+00:00')",
        (imported,),
    )
    conn.execute(
        "INSERT INTO workout_execution_event (event_id, workout_id, event_type, occurred_at,"
        " received_at, device_id) VALUES ('ev-1', ?, 'set_completed',"
        " '2024-01-01T18:05:00+00:00', '2024-01-01T18:05:00+00:00', 'watch')",
        (imported,),
    )
    conn.execute(
        "INSERT INTO external_workout (external_workout_id, external_key, origin, activity_type,"
        " started_at, ended_at, duration_s, source_name, imported_at)"
        " VALUES ('w-1', ?, 'healthkit', 'HKWorkoutActivityTypeTraditionalStrengthTraining',"
        " '2024-01-01T18:00:00+00:00', '2024-01-01T19:00:00+00:00', 3600, 'Apple Watch',"
        " '2024-01-01T19:05:00+00:00')",
        (b"\x02" * 16,),
    )
    conn.execute(
        "INSERT INTO workout_link (link_id, external_workout_id, session_id, action, method,"
        " band_version) VALUES ('l-1', 'w-1', ?, 'link', 'manual', 'link_v1')",
        (imported,),
    )


def test_hr_probe_review_waits_for_sessions_then_repeats_on_a_cadence(monkeypatch):
    # The prompt must not nag: below the session threshold it stays out of the Today list, and it
    # returns only after the 12-week interval once reviewed.
    store = db.Store(":memory:")
    try:
        conn = store.connection
        monkeypatch.setattr(
            reviews, "_config",
            lambda: {"hr_recovery_probe": {
                "min_sessions": 1, "interval_weeks": 12, "snooze_days": 90,
                "label": "Re-run the heart-rate recovery probe",
            }},
        )
        quiet = next(
            t for t in reviews.status(conn, "2024-01-01")["tasks"]
            if t["key"] == "hr_recovery_probe"
        )
        # Visible but not actionable: the prompt exists on Today before the threshold, so the
        # owner can see the counter rather than wondering where it went.
        assert quiet["status"] == "waiting" and quiet["details"]["watch_sessions"] == 0
        assert quiet["snooze_days"] == 90

        training = make_training([{
            "Date": "2024-01-01", "Exercise": "Competition Bench Press",
            "Weight_Used": "80", "RIR": "2", "Reps_Done": "5",
        }])
        readiness = make_readiness([{"Date": "2024-01-01"}])
        importer.import_export(
            conn, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        _one_telemetry_session(conn)
        due = next(
            t for t in reviews.status(conn, "2024-01-02")["tasks"]
            if t["key"] == "hr_recovery_probe"
        )
        assert due["status"] == "due"
        assert due["periodic"] is True
        assert "watch sessions" in due["summary"]

        repositories.append_maintenance_review(
            conn, task_key="hr_recovery_probe", action="completed",
            reviewed_on="2024-01-02", decision="kept", note="re-ran the probe",
        )
        after = next(
            t for t in reviews.status(conn, "2024-01-03")["tasks"]
            if t["key"] == "hr_recovery_probe"
        )
        assert after["status"] == "not_due"
        assert after["due_on"] == "2024-03-26"
    finally:
        store.close()

