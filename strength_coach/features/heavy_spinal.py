"""Display-only heavy spinal exposure advisory.

The weekly spinal cap is load-blind by design. This module adds the missing visibility without
changing the cap: it counts working sets on high-fatigue spinal exercises at RIR <= 1, grouped
by ISO week, over a short window. It is context only; no prescription or cap reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from strength_coach.utils import exercises, paths


@dataclass(frozen=True)
class HeavySpinalConfig:
    window_weeks: int = 4
    rir_max: int = 1
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "HeavySpinalConfig":
        source = Path(path or paths.config_dir("spinal-heavy-exposure.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        return cls(
            window_weeks=int(raw.get("window_weeks", 4)),
            rir_max=int(raw.get("rir_max", 1)),
            source_path=source,
        )


def _iso_week(value) -> str:
    date = pd.Timestamp(value)
    year, week, _ = date.isocalendar()
    return f"{int(year)}-W{int(week):02d}"


def compute(sets: pd.DataFrame, *, on_date: str,
            config: HeavySpinalConfig | None = None) -> dict:
    """Return a small, descriptive report; never a pass/fail verdict."""
    cfg = config or HeavySpinalConfig.load()
    if sets is None or sets.empty or "rir" not in sets.columns:
        return {
            "window_weeks": cfg.window_weeks,
            "rir_max": cfg.rir_max,
            "total_sets": 0,
            "weeks": [],
            "note": "No heavy spinal sets in the window; advisory only.",
        }
    frame = sets.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    cutoff = pd.Timestamp(on_date) - pd.Timedelta(days=cfg.window_weeks * 7)
    frame = frame[(frame["date"] > cutoff) & (frame["date"] <= pd.Timestamp(on_date))]
    if frame.empty:
        return {
            "window_weeks": cfg.window_weeks,
            "rir_max": cfg.rir_max,
            "total_sets": 0,
            "weeks": [],
            "note": "No heavy spinal sets in the window; advisory only.",
        }
    working = frame[frame["is_working_set"].astype(bool)]
    heavy = working[
        working["rir"].notna() & (working["rir"] <= cfg.rir_max)
    ].copy()
    entities = exercises.taxonomy().entities
    heavy = heavy[
        heavy["exercise_id"].astype(str).map(
            lambda exercise_id: bool(
                entities.get(exercise_id, {}).get("high_fatigue_spinal", False)
            )
        )
    ]
    weeks = []
    if not heavy.empty:
        heavy["week"] = heavy["date"].map(_iso_week)
        for week, group in heavy.groupby("week", sort=True):
            weeks.append({
                "week": str(week),
                "sets": int(len(group)),
                "sessions": int(group["session_id"].nunique()),
                "exercises": {
                    str(exercise_id): int(count)
                    for exercise_id, count in group["exercise_id"].value_counts().items()
                },
            })
    total = int(len(heavy))
    return {
        "window_weeks": cfg.window_weeks,
        "rir_max": cfg.rir_max,
        "total_sets": total,
        "weeks": weeks,
        "note": (
            "Heavy spinal sets are context only; they are not load-weighted and do not "
            "change the weekly cap or prescription."
        ),
    }
