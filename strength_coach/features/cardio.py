"""Cardio capture summary: what was done, how much, and against a public-health reference.

Cardio is a separate exposure from resistance training (ROADMAP §4.13). This module does the
smallest useful thing: count the sessions, add up the minutes, show the weekly distribution and
the modality mix, and state the WHO reference **as context**. It does not prescribe, does not
change a load, and does not attempt a fatigue model — the roadmap's impulse model stays
planned. Keeping the summary purely descriptive is deliberate: there is no evidence that the
population guideline is the right individual dose, and `docs/LONGEVITY-REVIEW.md` says so.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from strength_coach.store import queries
from strength_coach.utils import paths

DEFAULT_REFERENCE_MIN = 150
DEFAULT_REFERENCE_MAX = 300
DEFAULT_REFERENCE_NOTE = (
    "WHO 2020 guidance for adults: 150-300 min/week of moderate aerobic activity (or 75-150 "
    "min vigorous). Context, not a personal prescription."
)


@dataclass(frozen=True)
class CardioSummary:
    weeks: int
    from_date: str
    to_date: str
    sessions: int
    total_minutes: float
    average_weekly_minutes: float
    weekly_minutes: Mapping[str, float]
    by_modality: Mapping[str, int]
    average_srpe: float | None
    reference_min: int
    reference_max: int
    reference_note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "weeks": self.weeks,
            "from_date": self.from_date,
            "to_date": self.to_date,
            "sessions": self.sessions,
            "total_minutes": self.total_minutes,
            "average_weekly_minutes": self.average_weekly_minutes,
            "weekly_minutes": dict(self.weekly_minutes),
            "by_modality": dict(self.by_modality),
            "average_srpe": self.average_srpe,
            "reference_min": self.reference_min,
            "reference_max": self.reference_max,
            "reference_note": self.reference_note,
        }


def _reference(path: Path | None = None) -> tuple[int, int, str]:
    source = Path(path or paths.cardio_yaml())
    if not source.exists():
        return DEFAULT_REFERENCE_MIN, DEFAULT_REFERENCE_MAX, DEFAULT_REFERENCE_NOTE
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    block = raw.get("reference") or {}
    low = int(block.get("weekly_minutes_min", DEFAULT_REFERENCE_MIN))
    high = int(block.get("weekly_minutes_max", DEFAULT_REFERENCE_MAX))
    note = str(block.get("note") or DEFAULT_REFERENCE_NOTE).strip()
    if low <= 0 or high < low:
        raise ValueError(
            f"cardio reference must satisfy 0 < min <= max, got {low}-{high}"
        )
    return low, high, note


def _week_label(day: str) -> str:
    stamp = dt.date.fromisoformat(day[:10]).isocalendar()
    return f"{stamp.year}-W{stamp.week:02d}"


def compute(conn, *, on_date: str | None = None, weeks: int = 12,
            path: str | Path | None = None) -> CardioSummary:
    """Summarise the last `weeks` weeks ending on `on_date` (default: today)."""
    if weeks <= 0:
        raise ValueError("weeks must be positive")
    end = dt.date.fromisoformat(on_date) if on_date else dt.date.today()
    start = end - dt.timedelta(days=7 * weeks)
    entries = queries.cardio_entries(
        conn, since=start.isoformat(), until=end.isoformat()
    )

    weekly: dict[str, float] = {}
    modalities: dict[str, int] = {}
    total_seconds = 0
    srpe_values: list[int] = []
    for entry in entries:
        minutes = float(entry["duration_s"]) / 60.0
        total_seconds += int(entry["duration_s"])
        week = _week_label(str(entry["performed_on"]))
        weekly[week] = round(weekly.get(week, 0.0) + minutes, 1)
        modality = str(entry["modality"])
        modalities[modality] = modalities.get(modality, 0) + 1
        if entry["srpe"] is not None:
            srpe_values.append(int(entry["srpe"]))

    low, high, note = _reference(path)
    total_minutes = round(total_seconds / 60.0, 1)
    return CardioSummary(
        weeks=weeks,
        from_date=start.isoformat(),
        to_date=end.isoformat(),
        sessions=len(entries),
        total_minutes=total_minutes,
        average_weekly_minutes=round(total_minutes / weeks, 1),
        weekly_minutes=dict(sorted(weekly.items())),
        by_modality=dict(sorted(modalities.items())),
        average_srpe=(
            round(sum(srpe_values) / len(srpe_values), 1) if srpe_values else None
        ),
        reference_min=low,
        reference_max=high,
        reference_note=note,
    )
