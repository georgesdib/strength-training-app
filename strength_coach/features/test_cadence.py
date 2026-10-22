"""3RM/5RM test cadence.

A reminder only: it never writes an override or changes a prescription. The next scheme
alternates by the number of distinct prior test dates, and the interval starts from the last
test date, not from a calendar block.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from strength_coach.store import queries
from strength_coach.utils import paths


@dataclass(frozen=True)
class CadenceConfig:
    enabled: bool = True
    every_weeks: int = 10
    schemes: tuple[str, ...] = ("3RM", "5RM")
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "CadenceConfig":
        source = Path(path or paths.config_dir("test-cadence.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        schemes = tuple(str(x) for x in raw.get("schemes", ["3RM", "5RM"]))
        if not schemes:
            raise ValueError("test cadence needs at least one scheme")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            every_weeks=max(1, int(raw.get("every_weeks", 10))),
            schemes=schemes,
            source_path=source,
        )


def status(conn, on_date: str, *, config: CadenceConfig | None = None) -> dict:
    cfg = config or CadenceConfig.load()
    if not cfg.enabled:
        return {"enabled": False, "due": False, "reason": "cadence disabled"}
    dates = sorted({
        str(row["effective_from"])
        for row in queries.e1rm_overrides(conn)
        if row.get("source") == "measured" and str(row["effective_from"]) <= on_date
    })
    if not dates:
        return {
            "enabled": True, "due": True, "last_test": None,
            "next_due": on_date, "next_scheme": cfg.schemes[0],
            "reason": "no measured test recorded",
        }
    last = dates[-1]
    from datetime import date, timedelta
    last_date = date.fromisoformat(last)
    due = last_date + timedelta(weeks=cfg.every_weeks)
    scheme = cfg.schemes[len(dates) % len(cfg.schemes)]
    return {
        "enabled": True,
        "due": date.fromisoformat(on_date) >= due,
        "last_test": last,
        "next_due": due.isoformat(),
        "next_scheme": scheme,
        "reason": f"last measured test {last}; every {cfg.every_weeks} weeks",
    }
