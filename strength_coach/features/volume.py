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
    landmarks: dict[str, tuple[float, float, float, float]] | None = None
    apply_mrv_cap: bool = True
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "VolumeConfig":
        source = Path(path or paths.config_dir("volume.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        targets = {
            str(key): (float(value[0]), float(value[1]))
            for key, value in (raw.get("targets") or {}).items()
        }
        landmarks = {}
        for key, value in (raw.get("landmarks") or {}).items():
            mav = value.get("mav") or [value.get("mev", 0), value.get("mrv", 0)]
            landmarks[str(key)] = (
                float(value.get("mev", 0)),
                float(mav[0]),
                float(mav[1]),
                float(value.get("mrv", mav[1])),
            )
        return cls(
            window_weeks=int(raw.get("window_weeks", 4)),
            targets=targets,
            landmarks=landmarks,
            apply_mrv_cap=bool(raw.get("apply_mrv_cap", True)),
            source_path=source,
        )

    def landmark(self, pattern: str) -> tuple[float, float, float, float] | None:
        if self.landmarks:
            return self.landmarks.get(str(pattern))
        if self.targets and str(pattern) in self.targets:
            low, high = self.targets[str(pattern)]
            return (low, low, high, high)
        return None


@dataclass(frozen=True)
class PatternVolume:
    pattern: str
    weeks: tuple[int, ...]
    total: int
    average: float
    target: tuple[float, float] | None
    status: str
    mev: float | None = None
    mav: tuple[float, float] | None = None
    mrv: float | None = None

    def as_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "weeks": list(self.weeks),
            "total": self.total,
            "average": round(self.average, 2),
            "target": list(self.target) if self.target else None,
            "status": self.status,
            "mev": self.mev,
            "mav": list(self.mav) if self.mav else None,
            "mrv": self.mrv,
        }


def volume_target_key(pattern: str) -> str:
    """Map a taxonomy pattern to the configured landmark key."""
    raw = str(pattern)
    if raw.startswith("horizontal_push"):
        return "horizontal_push"
    if raw.startswith("vertical_"):
        return raw
    if raw.startswith("hinge"):
        return raw if raw == "hinge_unilateral" else "hinge"
    if raw.startswith("core_") or raw == "carry":
        return "core"
    if raw == "squat_unilateral":
        return "squat"
    return raw


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
        target_key = volume_target_key(str(pattern))
        landmark = cfg.landmark(target_key) if target_key else None
        target = (landmark[0], landmark[3]) if landmark else None
        if landmark is None:
            status = "untargeted"
        elif average < landmark[0]:
            status = "under"
        elif average > landmark[3]:
            status = "over"
        elif average > landmark[2]:
            status = "high"
        else:
            status = "within"
        rows.append(PatternVolume(
            str(pattern), tuple(counts), total, average, target, status,
            mev=landmark[0] if landmark else None,
            mav=(landmark[1], landmark[2]) if landmark else None,
            mrv=landmark[3] if landmark else None,
        ))
    rows.sort(key=lambda row: (-row.total, row.pattern))
    return {
        "from": start.date().isoformat(),
        "to": end.date().isoformat(),
        "weeks": week_labels,
        "patterns": [row.as_dict() for row in rows],
    }
