"""Advisory recent-stress decay per lift (option B, docs/FATIGUE-FITNESS.md).

This is not a fitness-fatigue fit. It counts working sets weighted by an exponential decay so
the Prescribe page can say "this lift has had a lot of recent work". It never changes a load;
the constants are explicit assumptions in `config/stress.v1.yaml`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from strength_coach.utils import exercises, paths

STATUSES = ("high", "normal", "low")


@dataclass(frozen=True)
class StressConfig:
    half_life_hours: float
    window_days: int
    high_decayed_sets: float
    normal_decayed_sets: float
    warning_within_hours: float
    effort_max_rir: int
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "StressConfig":
        source = Path(path or paths.stress_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        return cls(
            half_life_hours=float(raw.get("half_life_hours", 48)),
            window_days=int(raw.get("window_days", 10)),
            high_decayed_sets=float(raw.get("high_decayed_sets", 6)),
            normal_decayed_sets=float(raw.get("normal_decayed_sets", 3)),
            warning_within_hours=float(raw.get("warning_within_hours", 48)),
            effort_max_rir=int(raw.get("effort_max_rir", 4)),
            source_path=source,
        )


@dataclass(frozen=True)
class StressEntry:
    exercise_id: str
    status: str                 # high | normal | low
    decayed_sets: float
    set_count: int
    last_date: str
    last_hours: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "status": self.status,
            "decayed_sets": round(self.decayed_sets, 2),
            "set_count": self.set_count,
            "last_date": self.last_date,
            "last_hours": self.last_hours,
        }


def _canonical_id(exercise_id: str, entities: Mapping[str, Mapping[str, Any]]) -> str:
    # Hyperextension rows count as back-extension history (DEC-BACKEXT-02); stress follows
    # the same equivalence so a recent back-extension session is not split across two ids.
    return str(entities.get(exercise_id, {}).get("history_equivalent_of") or exercise_id)


def compute(
    sets: pd.DataFrame,
    on_date: str | pd.Timestamp,
    config: StressConfig | None = None,
) -> dict[str, StressEntry]:
    cfg = config or StressConfig.load()
    day = pd.Timestamp(on_date)
    if sets is None or sets.empty:
        return {}

    frame = sets[["date", "exercise_id", "is_working_set", "rir"]].copy()
    frame = frame[frame["is_working_set"].astype(bool)]
    frame = frame[frame["rir"].isna() | (frame["rir"] <= cfg.effort_max_rir)]
    frame = frame[frame["date"] <= day]
    if frame.empty:
        return {}
    frame = frame[frame["date"] >= day - pd.Timedelta(days=cfg.window_days)]
    if frame.empty:
        return {}

    entities = exercises.taxonomy().entities
    frame["canonical"] = [
        _canonical_id(str(value), entities) for value in frame["exercise_id"]
    ]
    frame["age_hours"] = (day - frame["date"]).dt.total_seconds() / 3600.0
    frame["weight"] = 0.5 ** (frame["age_hours"] / cfg.half_life_hours)

    out: dict[str, StressEntry] = {}
    for exercise_id, group in frame.groupby("canonical", sort=True):
        decayed = float(group["weight"].sum())
        if decayed >= cfg.high_decayed_sets:
            status = "high"
        elif decayed >= cfg.normal_decayed_sets:
            status = "normal"
        else:
            status = "low"
        last = group["date"].max()
        out[str(exercise_id)] = StressEntry(
            exercise_id=str(exercise_id),
            status=status,
            decayed_sets=decayed,
            set_count=int(len(group)),
            last_date=last.date().isoformat(),
            last_hours=float((day - last).total_seconds() / 3600.0),
        )
    return out


def advisories(
    report: Mapping[str, StressEntry],
    exercise_ids: tuple[str, ...],
    config: StressConfig | None = None,
) -> list[str]:
    """Warnings for a high-stress lift scheduled inside the warning window.

    Advisory only: it never edits a load. An exercise absent from the report has no recent
    work and produces no warning.
    """
    cfg = config or StressConfig.load()
    warnings: list[str] = []
    seen: set[str] = set()
    for exercise_id in exercise_ids:
        entry = report.get(str(exercise_id))
        if entry is None or exercise_id in seen:
            continue
        seen.add(str(exercise_id))
        if entry.status != "high" or entry.last_hours >= cfg.warning_within_hours:
            continue
        warnings.append(
            f"recent stress: {exercise_id} high ({entry.decayed_sets:.1f} decayed hard sets, "
            f"last {entry.last_hours:.0f}h ago); consider extra recovery or RIR "
            f"(advisory, load unchanged)"
        )
    return warnings


def as_dict(report: Mapping[str, StressEntry]) -> dict[str, dict[str, Any]]:
    return {key: entry.as_dict() for key, entry in report.items()}
