"""The plan dispatcher must follow the database it was started for.

Regression: the singleton kept one set of wake/stop events for the whole process. Every test
opens its own temporary database, so a retired thread that was still finishing a build could
swallow the wake meant for its successor, or be revived when the shared stop flag was cleared.
A queued request then sat unbuilt for the client's whole wait while an idle thread watched a
database nobody was using.
"""

from __future__ import annotations

import time

from strength_coach.web import ios_plan_worker


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _quiet_drain(db_path=None, slot=None) -> bool:
    return False


def test_start_for_the_same_database_reuses_the_running_dispatcher(monkeypatch, tmp_path):
    monkeypatch.setattr(ios_plan_worker, "drain_once", _quiet_drain)
    database = tmp_path / "coach.db"
    ios_plan_worker.stop_dispatcher()
    try:
        ios_plan_worker.start_dispatcher(database)
        first = ios_plan_worker._dispatcher
        ios_plan_worker.start_dispatcher(database)
        assert ios_plan_worker._dispatcher is first
    finally:
        ios_plan_worker.stop_dispatcher()


def test_start_for_a_new_database_retires_the_previous_dispatcher(monkeypatch, tmp_path):
    monkeypatch.setattr(ios_plan_worker, "IDLE_WAIT_SECONDS", 0.1)
    seen: list[str] = []

    def drain(db_path=None, slot=None) -> bool:
        seen.append(str(db_path))
        return False

    monkeypatch.setattr(ios_plan_worker, "drain_once", drain)
    first_db = str(tmp_path / "first.db")
    second_db = str(tmp_path / "second.db")
    ios_plan_worker.stop_dispatcher()
    try:
        ios_plan_worker.start_dispatcher(first_db)
        assert _wait_until(lambda: first_db in seen)
        retired = ios_plan_worker._dispatcher

        ios_plan_worker.start_dispatcher(second_db)
        assert _wait_until(lambda: second_db in seen)
        assert ios_plan_worker._dispatcher is not retired
        assert not retired.thread.is_alive()

        mark = len(seen)
        time.sleep(0.4)
        assert first_db not in seen[mark:]
        assert second_db in seen[mark:]
    finally:
        ios_plan_worker.stop_dispatcher()


def test_a_slow_retired_dispatcher_does_not_starve_the_next_database(monkeypatch, tmp_path):
    monkeypatch.setattr(ios_plan_worker, "IDLE_WAIT_SECONDS", 0.1)
    seen: list[str] = []
    first_db = str(tmp_path / "first.db")
    second_db = str(tmp_path / "second.db")

    def drain(db_path=None, slot=None) -> bool:
        seen.append(str(db_path))
        if str(db_path) == first_db:
            time.sleep(1.5)  # outlives the bounded join in start_dispatcher
        return False

    monkeypatch.setattr(ios_plan_worker, "drain_once", drain)
    ios_plan_worker.stop_dispatcher()
    try:
        ios_plan_worker.start_dispatcher(first_db)
        assert _wait_until(lambda: first_db in seen)
        retired = ios_plan_worker._dispatcher

        started = time.monotonic()
        ios_plan_worker.start_dispatcher(second_db)
        # The join really timed out, so the old thread was still alive when the new one began.
        assert time.monotonic() - started >= 1.0
        assert _wait_until(lambda: second_db in seen, timeout=2.0)
        assert ios_plan_worker._dispatcher is not retired
        assert _wait_until(lambda: not retired.thread.is_alive(), timeout=3.0)
    finally:
        ios_plan_worker.stop_dispatcher()
