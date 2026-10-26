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
