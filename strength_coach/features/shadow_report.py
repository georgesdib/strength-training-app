"""Phase 6: the shadow review report and its activation gate (DEC-SHADOW-01).

The report is deliberately advisory. Nothing here can switch a behaviour on: it only says
whether the recorded evidence is thick enough to justify asking the athlete for an explicit
decision.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from strength_coach.store import queries
from strength_coach.utils import paths


@dataclass(frozen=True)
class ShadowConfig:
    window_days: int = 84
    min_shadow_days: int = 56
    min_high_signal_days: int = 3
    min_exposure_evaluations: int = 10
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> ShadowConfig:
        source = Path(path or paths.shadow_yaml())
        if not source.is_file():
            return cls(source_path=source)
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        return cls(
            window_days=int(raw.get("window_days", 84)),
            min_shadow_days=int(raw.get("min_shadow_days", 56)),
            min_high_signal_days=int(raw.get("min_high_signal_days", 3)),
            min_exposure_evaluations=int(raw.get("min_exposure_evaluations", 10)),
            source_path=source,
        )


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class ShadowReport:
    on_date: str
    window_days: int
    rows: int
    by_component: dict[str, int]
    by_action: dict[str, int]
    applied: int
    suggestions: int
    high_signal_days: int
    shadow_days: int
    abstentions: tuple[str, ...]
    checks: tuple[GateCheck, ...]
    ready: bool
    activation_allowed: bool = False
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "on_date": self.on_date,
            "window_days": self.window_days,
            "rows": self.rows,
            "by_component": self.by_component,
            "by_action": self.by_action,
            "applied": self.applied,
            "suggestions": self.suggestions,
            "high_signal_days": self.high_signal_days,
            "shadow_days": self.shadow_days,
            "abstentions": list(self.abstentions),
            "checks": [check.as_dict() for check in self.checks],
            "ready": self.ready,
            "activation_allowed": self.activation_allowed,
            "notes": list(self.notes),
        }


def _json(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def report(
    conn,
    on_date: str,
    *,
    window_days: int | None = None,
    config: ShadowConfig | None = None,
) -> ShadowReport:
    cfg = config or ShadowConfig.load()
    days = int(window_days or cfg.window_days)
    day = dt.date.fromisoformat(str(on_date)[:10])
    since = (day - dt.timedelta(days=days - 1)).isoformat()
    rows = queries.shadow_decisions(conn, since=since, limit=5000)

    by_component = Counter(str(row["component"]) for row in rows)
    by_action = Counter(str(row["action"]) for row in rows)
    applied = sum(int(row["applied"]) for row in rows)
    suggestions = sum(1 for row in rows if row["action"] == "suggest_substitution")

    high_days = {
        str(row["evaluated_on"]) for row in rows
        if row["component"] == "exposure"
        and _json(row["signal_json"]).get("signal") == "high"
    }
    evaluations = by_component.get("exposure", 0)
    dates = sorted({str(row["evaluated_on"]) for row in rows})
    shadow_days = 0
    if dates:
        first = dt.date.fromisoformat(dates[0])
        last = dt.date.fromisoformat(dates[-1])
        shadow_days = (last - first).days + 1

    # One signal, one action: a date must not both trim and substitute.
    trimmed_dates = {
        str(row["evaluated_on"]) for row in rows
        if row["component"] == "exposure" and int(row["applied"])
    }
    suggested_dates = {
        str(row["evaluated_on"]) for row in rows
        if row["action"] == "suggest_substitution"
    }
    conflicts = sorted(trimmed_dates & suggested_dates)

    abstention_reasons = Counter(
        str(row["reason"]) for row in rows
        if row["action"] == "none" and row["reason"]
    )
    abstentions = tuple(
        f"{reason} ({count})" for reason, count in abstention_reasons.most_common(5)
    )

    checks = (
        GateCheck(
            "shadow span", shadow_days >= cfg.min_shadow_days,
            f"{shadow_days} days of records; need {cfg.min_shadow_days}",
        ),
        GateCheck(
            "exposure evaluations", evaluations >= cfg.min_exposure_evaluations,
            f"{evaluations} evaluations; need {cfg.min_exposure_evaluations}",
        ),
        GateCheck(
            "high-signal days", len(high_days) >= cfg.min_high_signal_days,
            f"{len(high_days)} days; need {cfg.min_high_signal_days}",
        ),
        GateCheck(
            "no conflicts", not conflicts,
            "none" if not conflicts else "trim and substitution on " + ", ".join(conflicts),
        ),
    )
    ready = all(check.passed for check in checks)
    notes = (
        "The gate only says the report is substantive enough for a decision; it does not "
        "enable anything.",
        "Enabling the trim stays a recorded profile change after an explicit decision "
        "(DEC-SHADOW-01).",
    )
    return ShadowReport(
        on_date=day.isoformat(),
        window_days=days,
        rows=len(rows),
        by_component=dict(by_component),
        by_action=dict(by_action),
        applied=applied,
        suggestions=suggestions,
        high_signal_days=len(high_days),
        shadow_days=shadow_days,
        abstentions=abstentions,
        checks=checks,
        ready=ready,
        activation_allowed=False,
        notes=notes,
    )
