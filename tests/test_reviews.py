"""Periodic review reminders are prompts; only human acknowledgements are written."""

from __future__ import annotations

import datetime as dt

from strength_coach.features import reviews
from strength_coach.store import db, repositories


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


def test_volume_review_reminder_appears_only_after_budget_is_enabled():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        assert not any(
            t["key"] == "volume_review" for t in reviews.status(conn, "2026-10-26")["tasks"]
        )
        repositories.append_athlete_profile(
            conn, effective_from="2026-10-26",
            volume_budget_enabled=True,
        )
        task = next(
            t for t in reviews.status(conn, "2026-10-26")["tasks"]
            if t["key"] == "volume_review"
        )
    finally:
        store.close()
    assert task["status"] == "attention"
    assert task["periodic"] is False
    assert "standing" in task["why"].lower()
    assert "closed" in task["why"].lower()


def test_review_status_reports_data_gaps_without_writing():
    store = db.Store(":memory:")
    try:
        report = reviews.status(store.connection, "2024-01-01")
    finally:
        store.close()
    tasks = {task["key"]: task for task in report["tasks"]}
    assert tasks["rubric_labels"]["status"] == "attention"
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
