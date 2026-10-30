"""Phase 5A prospective-validation follow-up task."""

from __future__ import annotations

from strength_coach.features import reviews
from strength_coach.store import db, repositories


def _task(conn, on_date):
    tasks = reviews.status(conn, on_date)["tasks"]
    return next(item for item in tasks if item["key"] == "phase5a_review")


def test_phase5a_task_dates_and_status_transition():
    with db.Store(":memory:") as store:
        conn = store.connection
        planned = _task(conn, "2026-10-29")
        active = _task(conn, "2026-10-30")
        due = _task(conn, "2027-01-22")

    assert planned["status"] == "planned"
    assert active["status"] == "due"
    assert active["due_on"] == "2027-01-22"
    assert active["details"]["start_date"] == "2026-10-30"
    assert active["label"] == "Phase 5A — Prospective validation review"
    assert due["status"] == "attention"
    assert reviews.snooze_days("phase5a_review") == 14
    assert "Do not begin Phase 5B" in " ".join(active["dont"])


def test_phase5a_completion_is_persisted_with_decision():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_maintenance_review(
            conn, task_key="phase5a_review", action="completed",
            reviewed_on="2027-01-22", decision="changed", note="proceed",
        )
        completed = _task(conn, "2027-01-23")
        assert completed["status"] == "completed"
        assert completed["details"]["decision"] == "changed"
        assert completed["details"]["last_completed"] == "2027-01-22"
