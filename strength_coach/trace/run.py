"""Run tracing: one row per attempt, plus an ordered event log.

The trace is what makes a past decision explainable after recalibration or a rule-version
bump. It deliberately records *what was used* (input hash, config hash, code version) rather
than only the outcome, because "same inputs, different answer" is the question a backtest
asks.

`store.repositories` owns the SQL; this module only supplies the lifecycle so a pipeline
cannot leave a run open when it raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from strength_coach import __version__
from strength_coach.store import repositories as repo


@dataclass
class RunTrace:
    conn: object
    run_id: str
    status: str = "running"
    events: list[tuple[int, str]] = field(default_factory=list)
    llm_tokens: int = 0

    @classmethod
    def start(
        cls,
        conn,
        *,
        input_hash: str,
        config_hash: str | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
        code_version: str | None = None,
    ) -> "RunTrace":
        run = repo.start_run(
            conn,
            input_hash=input_hash,
            code_version=code_version or __version__,
            config_hash=config_hash,
            window_start=window_start,
            window_end=window_end,
        )
        return cls(conn=conn, run_id=run.run_id)

    def event(self, kind: str, payload=None) -> int:
        seq = repo.log_event(self.conn, self.run_id, kind, payload)
        self.events.append((seq, kind))
        return seq

    def add_tokens(self, tokens: int) -> None:
        """Accumulate model usage so the run row reports what the narrative cost."""
        if tokens:
            self.llm_tokens += int(tokens)

    def finish(self, status: str = "ok") -> None:
        repo.finish_run(
            self.conn,
            self.run_id,
            status=status,
            llm_tokens=self.llm_tokens or None,
        )
        self.status = status

    def __enter__(self) -> "RunTrace":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # A failed run must still be closed, or the trace claims a run is still in progress.
        # An explicit finish() wins: the caller may know the run ended in llm_failed.
        if self.status != "running":
            return
        self.finish(status="error" if exc_type is not None else "ok")
