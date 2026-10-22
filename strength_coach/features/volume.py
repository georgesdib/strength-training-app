"""Weekly hard-set ledger by movement pattern.

This is a report, not a prescription controller. It answers "how much did each pattern get?"
and compares the average to a broad config range, so volume drift is visible without inventing
automatic set caps. The set valve under poor readiness remains a separate, explicit rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from strength_coach.utils import exercises, paths


@dataclass(frozen=True)
class VolumeConfig:
    window_weeks: int = 4
    targets: dict[str, tuple[float, float]] | None = None
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "VolumeConfig":
        source = Path(path or paths.config_dir("volume.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        targets = {
            str(key): (float(value[0]), float(value[1]))
            for key, value in (raw.get("targets") or {}).items()
        }
        return cls(
            window_weeks=int(raw.get("window_weeks", 4)),
            targets=targets,
            source_path=source,
        )


@dataclass(frozen=True)
class PatternVolume:
    pattern: str
    weeks: tuple[int, ...]
    total: int
    average: float
    target: tuple[float, float] | None
    status: str

    def as_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "weeks": list(self.weeks),
            "total": self.total,
            "average": round(self.average, 2),
            "target": list(self.target) if self.target else None,
            "status": self.status,
        }


def compute(sets: pd.DataFrame, *, on_date: str | None = None,
            config: VolumeConfig | None = None) -> dict:
    cfg = config or VolumeConfig.load()
    if sets.empty or "date" not in sets or "exercise_id" not in sets:
        return {"from": on_date, "to": on_date, "weeks": [], "patterns": []}
    frame = sets.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    end = pd.Timestamp(on_date) if on_date else frame["date"].max()
    start = end - pd.Timedelta(days=cfg.window_weeks * 7)
    if "is_working_set" in frame:
        frame = frame[frame["is_working_set"].astype(bool)]
    frame = frame[(frame["date"] > start) & (frame["date"] <= end)]
    if frame.empty:
        return {"from": start.date().isoformat(), "to": end.date().isoformat(),
                "weeks": [], "patterns": []}

    taxonomy = exercises.taxonomy()
    frame["pattern"] = frame["exercise_id"].map(
        lambda value: (taxonomy.entities.get(str(value), {}) or {}).get("pattern")
    )
    frame = frame[frame["pattern"].notna()]
    frame["iso_week"] = frame["date"].dt.isocalendar().week.astype(int)
    week_labels = sorted(frame["iso_week"].unique().tolist())
    rows: list[PatternVolume] = []
    for pattern, group in frame.groupby("pattern"):
        counts = [int((group["iso_week"] == week).sum()) for week in week_labels]
        total = sum(counts)
        average = total / max(1, len(week_labels))
        raw_pattern = str(pattern)
        target_key = raw_pattern
        if raw_pattern.startswith("horizontal_push"):
            target_key = "horizontal_push"
        elif raw_pattern.startswith("vertical_"):
            target_key = raw_pattern
        elif raw_pattern.startswith("hinge"):
            target_key = "hinge" if raw_pattern != "hinge_unilateral" else raw_pattern
        elif raw_pattern.startswith("core_") or raw_pattern == "carry":
            target_key = "core"
        elif raw_pattern == "squat_unilateral":
            target_key = "squat"
        target = (cfg.targets or {}).get(target_key)
        if target is None:
            status = "untargeted"
        elif average < target[0]:
            status = "under"
        elif average > target[1]:
            status = "over"
        else:
            status = "within"
        rows.append(PatternVolume(str(pattern), tuple(counts), total, average, target, status))
    rows.sort(key=lambda row: (-row.total, row.pattern))
    return {
        "from": start.date().isoformat(),
        "to": end.date().isoformat(),
        "weeks": week_labels,
        "patterns": [row.as_dict() for row in rows],
    }
