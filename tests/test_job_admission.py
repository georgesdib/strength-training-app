"""Concurrent CPU-heavy job admission for resolver preview and Workflow prescription."""

from __future__ import annotations

import threading

import pytest

from strength_coach.web import server


def _clear_jobs() -> None:
    for jobs, lock in (
        (server._RESOLVER_PREVIEW_JOBS, server._RESOLVER_PREVIEW_JOBS_LOCK),
        (server._PRESCRIBE_JOBS, server._PRESCRIBE_JOBS_LOCK),
    ):
        with lock:
            jobs.clear()


@pytest.mark.parametrize(
    ("start_name", "runner_name", "jobs", "lock", "error_text"),
    [
        (
            "start_resolver_preview_job", "_run_resolver_preview_job",
            server._RESOLVER_PREVIEW_JOBS, server._RESOLVER_PREVIEW_JOBS_LOCK,
            "resolver preview",
        ),
        (
            "start_prescribe_job", "_run_prescribe_job",
            server._PRESCRIBE_JOBS, server._PRESCRIBE_JOBS_LOCK,
            "prescription build",
        ),
    ],
)
def test_concurrent_job_admission_allows_exactly_one(
    monkeypatch, start_name, runner_name, jobs, lock, error_text,
):
    _clear_jobs()
    started = threading.Event()
    release = threading.Event()

    def blocked(*args, **kwargs):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(server, runner_name, blocked)
    start = getattr(server, start_name)
    barrier = threading.Barrier(8)
    outcomes: list[str] = []

    def attempt() -> None:
        barrier.wait(timeout=5)
        try:
            start(":memory:", {})
            outcomes.append("ok")
        except server.RequestError as exc:
            outcomes.append(str(exc.status))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert started.wait(timeout=5)
    assert outcomes.count("ok") == 1
    assert outcomes.count("409") == 7
    with lock:
        assert len(jobs) == 1

    release.set()
    # The blocked test runner bypasses the runner's normal finally block.
    server._CPU_JOB_SLOTS.release()
    _clear_jobs()


def test_resolver_and_workflow_share_one_cpu_slot(monkeypatch) -> None:
    _clear_jobs()
    started = threading.Event()
    release = threading.Event()

    def blocked(*args, **kwargs):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(server, "_run_resolver_preview_job", blocked)
    server.start_resolver_preview_job(":memory:", {})
    assert started.wait(timeout=5)
    with pytest.raises(server.RequestError) as caught:
        server.start_prescribe_job(":memory:", {})
    assert caught.value.status == 409
    assert "CPU-heavy job" in str(caught.value)
    with server._PRESCRIBE_JOBS_LOCK:
        assert not server._PRESCRIBE_JOBS

    release.set()
    server._CPU_JOB_SLOTS.release()
    _clear_jobs()
