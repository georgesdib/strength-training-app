"""Rolling hard-set exposure: a descriptive acute-vs-chronic ratio.

This is the arithmetic family of ACWR, which the project already rejected as an injury-risk
rule (DEC-ACWR-01). It is therefore kept descriptive: it counts hard sets, compares the last
seven days with the preceding four weeks, abstains whenever the data cannot support the
comparison, and never changes a prescription unless the athlete explicitly enables the
accessory trim (DEC-EXPOSURE-01, docs/FATIGUE-SIGNALS.md).

Definitions:
* hard set = a working set with RIR <= effort_max_rir, or a max/test exposure;
* exposures that reference a counted set are deduped by set_id;
* the chronic window is the 28 days immediately before the acute window (non-overlapping);
* a missing RIR is unknown, never easy and never hard: it lowers coverage instead.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from strength_coach.features import breaks as breaks_feature
from strength_coach.features import volume as volume_feature
from strength_coach.store import queries
from strength_coach.utils import exercises, paths

SIGNALS = ("high", "normal", "low", "unknown")
ABSTAIN_REASONS = (
    "break_in_window",
    "deload_in_window",
    "insufficient_sessions",
    "low_coverage",
    "zero_baseline",
    "gap_in_window",
)


@dataclass(frozen=True)
class ExposureConfig:
    acute_days: int = 7
    chronic_days: int = 28
    effort_max_rir: int = 4
    min_sessions: int = 8
    min_coverage: float = 0.80
    high_ratio: float = 1.3
    low_ratio: float = 0.7
    gap_days: int = 10
    trim_max_sets_per_session: int = 2
    trim_max_sets_per_item: int = 1
    trim_floor_sets: int = 1
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> ExposureConfig:
        source = Path(path or paths.exposure_yaml())
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) if source.is_file() else {}
        raw = raw or {}
        trim = raw.get("trim") or {}
        return cls(
            acute_days=int(raw.get("acute_days", 7)),
            chronic_days=int(raw.get("chronic_days", 28)),
            effort_max_rir=int(raw.get("effort_max_rir", 4)),
            min_sessions=int(raw.get("min_sessions", 8)),
            min_coverage=float(raw.get("min_coverage", 0.80)),
            high_ratio=float(raw.get("high_ratio", 1.3)),
            low_ratio=float(raw.get("low_ratio", 0.7)),
            gap_days=int(raw.get("gap_days", 10)),
            trim_max_sets_per_session=int(trim.get("max_sets_per_session", 2)),
            trim_max_sets_per_item=int(trim.get("max_sets_per_item", 1)),
            trim_floor_sets=int(trim.get("floor_sets", 1)),
            source_path=source,
        )


@dataclass(frozen=True)
class GroupExposure:
    group: str
    acute_hard_sets: int
    chronic_hard_sets: int
    baseline: float
    ratio: float | None
    signal: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "acute_hard_sets": self.acute_hard_sets,
            "chronic_hard_sets": self.chronic_hard_sets,
            "baseline": round(self.baseline, 2),
            "ratio": None if self.ratio is None else round(self.ratio, 2),
            "signal": self.signal,
        }


@dataclass(frozen=True)
class ExposureReport:
    on_date: str
    acute_start: str
    acute_end: str
    chronic_start: str
    chronic_end: str
    acute_hard_sets: int
    chronic_hard_sets: int
    baseline: float
    ratio: float | None
    previous_ratio: float | None
    coverage: float
    sessions: int
    signal: str
    abstain: tuple[str, ...]
    flags: dict[str, Any]
    groups: tuple[GroupExposure, ...]
    advisories: tuple[str, ...]

    @property
    def active(self) -> bool:
        return self.signal in {"high", "low"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "on_date": self.on_date,
            "windows": {
                "acute": {"start": self.acute_start, "end": self.acute_end},
                "chronic": {"start": self.chronic_start, "end": self.chronic_end},
            },
            "acute_hard_sets": self.acute_hard_sets,
            "chronic_hard_sets": self.chronic_hard_sets,
            "baseline": round(self.baseline, 2),
            "ratio": None if self.ratio is None else round(self.ratio, 2),
            "previous_ratio": (
                None if self.previous_ratio is None else round(self.previous_ratio, 2)
            ),
            "coverage": round(self.coverage, 3),
            "sessions": self.sessions,
            "signal": self.signal,
            "active": self.active,
            "abstain": list(self.abstain),
            "flags": dict(self.flags),
            "groups": [group.as_dict() for group in self.groups],
            "advisories": list(self.advisories),
        }


def _window(day: dt.date, config: ExposureConfig) -> tuple[dt.date, dt.date, dt.date, dt.date]:
    acute_end = day
    acute_start = day - dt.timedelta(days=config.acute_days - 1)
    chronic_end = acute_start - dt.timedelta(days=1)
    chronic_start = chronic_end - dt.timedelta(days=config.chronic_days - 1)
    return acute_start, acute_end, chronic_start, chronic_end


def _dates(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["date"]).dt.date


def _hard(frame: pd.DataFrame, config: ExposureConfig) -> pd.DataFrame:
    return frame[frame["rir"].notna() & (frame["rir"] <= config.effort_max_rir)]


def _count(frame: pd.DataFrame, start: dt.date, end: dt.date,
           config: ExposureConfig) -> int:
    if frame.empty:
        return 0
    hard = _hard(frame, config)
    if hard.empty:
        return 0
    dates = _dates(hard)
    return int(((dates >= start) & (dates <= end)).sum())


def _sessions_in(frame: pd.DataFrame, start: dt.date, end: dt.date) -> int:
    if frame.empty:
        return 0
    dates = _dates(frame)
    inside = frame[(dates >= start) & (dates <= end)]
    return int(inside["session_id"].nunique())


def _coverage_in(frame: pd.DataFrame, start: dt.date, end: dt.date) -> float:
    if frame.empty:
        return 0.0
    dates = _dates(frame)
    inside = frame[(dates >= start) & (dates <= end)]
    if inside.empty:
        return 0.0
    return float(inside["rir"].notna().mean())


def _ratio(acute_hard: int, chronic_hard: int, config: ExposureConfig) -> float | None:
    weeks = config.chronic_days / 7.0
    if chronic_hard <= 0 or weeks <= 0:
        return None
    return acute_hard / (chronic_hard / weeks)


def _gap_days(frame: pd.DataFrame, start: dt.date, end: dt.date) -> int:
    if frame.empty:
        return 0
    dates = sorted({value for value in _dates(frame) if start <= value <= end})
    points = [start, *dates, end]
    return max((b - a).days for a, b in zip(points, points[1:], strict=False))


def _group_for(exercise_id: str, entities: dict[str, dict[str, Any]]) -> str:
    pattern = str(entities.get(str(exercise_id), {}).get("pattern") or "")
    return volume_feature.volume_target_key(pattern) if pattern else "unknown"


def compute(conn, on_date: str, config: ExposureConfig | None = None) -> ExposureReport:
    """The rolling exposure report for one date. Read-only; writes nothing."""
    cfg = config or ExposureConfig.load()
    day = dt.date.fromisoformat(str(on_date)[:10])
    acute_start, acute_end, chronic_start, chronic_end = _window(day, cfg)
    prev_start, prev_end, prev_chronic_start, prev_chronic_end = _window(
        day - dt.timedelta(days=7), cfg
    )

    # Load back to the earlier chronic window as well: the previous-week ratio compares
    # against its own four-week baseline, which starts a week before this one.
    load_start = min(chronic_start, prev_chronic_start)
    frame = queries.clean_sets(
        conn, start=load_start.isoformat(), end=acute_end.isoformat()
    )
    if not frame.empty:
        frame = frame[frame["is_working_set"]].copy()

    acute_hard = _count(frame, acute_start, acute_end, cfg)
    chronic_hard = _count(frame, chronic_start, chronic_end, cfg)
    sessions = _sessions_in(frame, chronic_start, chronic_end)
    coverage = _coverage_in(frame, chronic_start, chronic_end)

    # Max/test exposures are hard work; a row pointing at an already-counted set is skipped
    # so one set is never counted twice.
    known_sets = {int(value) for value in frame["set_id"]} if not frame.empty else set()
    for row in queries.high_intensity_exposures(
        conn, end=acute_end.isoformat(), days=(acute_end - chronic_start).days + 1,
    ):
        performed = dt.date.fromisoformat(str(row["performed_on"])[:10])
        if not (chronic_start <= performed <= acute_end):
            continue
        if row.get("set_id") is not None and int(row["set_id"]) in known_sets:
            continue
        chronic_hard += 1
        if acute_start <= performed <= acute_end:
            acute_hard += 1

    ratio = _ratio(acute_hard, chronic_hard, cfg)
    baseline = chronic_hard / (cfg.chronic_days / 7.0) if chronic_hard else 0.0

    abstain: list[str] = []
    if any(
        not item.cancelled
        and item.starts_on <= acute_end.isoformat()
        and item.ends_on >= chronic_start.isoformat()
        for item in breaks_feature.all_breaks(conn)
    ):
        abstain.append("break_in_window")
    deload_rows = conn.execute(
        "SELECT COUNT(*) FROM prescription_modifier WHERE modifier_key = 'MOD-DELOAD-001' "
        "AND applied_on BETWEEN ? AND ?",
        (chronic_start.isoformat(), acute_end.isoformat()),
    ).fetchone()[0]
    if int(deload_rows) > 0:
        abstain.append("deload_in_window")
    if sessions < cfg.min_sessions:
        abstain.append("insufficient_sessions")
    if coverage < cfg.min_coverage:
        abstain.append("low_coverage")
    if chronic_hard <= 0:
        abstain.append("zero_baseline")
    gap = _gap_days(frame, chronic_start, chronic_end)
    if gap > cfg.gap_days:
        abstain.append("gap_in_window")

    signal = "unknown"
    if not abstain and ratio is not None:
        if ratio >= cfg.high_ratio:
            signal = "high"
        elif ratio <= cfg.low_ratio:
            signal = "low"
        else:
            signal = "normal"

    # The previous week's ratio supports the two-week low-exposure advisory. It is advisory,
    # so its own coverage is not re-gated.
    previous_ratio = _ratio(
        _count(frame, prev_start, prev_end, cfg),
        _count(frame, prev_chronic_start, prev_chronic_end, cfg),
        cfg,
    )

    entities = exercises.taxonomy().entities
    groups: list[GroupExposure] = []
    if not frame.empty:
        frame = frame.assign(
            group=[_group_for(value, entities) for value in frame["exercise_id"]]
        )
        for group, part in frame.groupby("group", sort=True):
            acute_group = _count(part, acute_start, acute_end, cfg)
            chronic_group = _count(part, chronic_start, chronic_end, cfg)
            group_ratio = _ratio(acute_group, chronic_group, cfg)
            if group_ratio is None:
                group_signal = "unknown"
            elif group_ratio >= cfg.high_ratio:
                group_signal = "high"
            elif group_ratio <= cfg.low_ratio:
                group_signal = "low"
            else:
                group_signal = "normal"
            groups.append(GroupExposure(
                str(group), acute_group, chronic_group,
                chronic_group / (cfg.chronic_days / 7.0) if chronic_group else 0.0,
                group_ratio, group_signal,
            ))

    advisories: list[str] = []
    if signal == "low" and previous_ratio is not None and previous_ratio <= cfg.low_ratio:
        advisories.append(
            "low exposure: the last two weeks are at or below "
            f"{cfg.low_ratio:g} of the preceding four-week average. This may reflect missed "
            "sessions, a deload or intentional rest; low exposure alone is not evidence of "
            "under-stimulation"
        )

    return ExposureReport(
        on_date=day.isoformat(),
        acute_start=acute_start.isoformat(),
        acute_end=acute_end.isoformat(),
        chronic_start=chronic_start.isoformat(),
        chronic_end=chronic_end.isoformat(),
        acute_hard_sets=acute_hard,
        chronic_hard_sets=chronic_hard,
        baseline=baseline,
        ratio=ratio,
        previous_ratio=previous_ratio,
        coverage=coverage,
        sessions=sessions,
        signal=signal,
        abstain=tuple(abstain),
        flags={
            "gap_days": gap,
            "effort_max_rir": cfg.effort_max_rir,
            "high_ratio": cfg.high_ratio,
            "low_ratio": cfg.low_ratio,
            "min_sessions": cfg.min_sessions,
            "min_coverage": cfg.min_coverage,
        },
        groups=tuple(groups),
        advisories=tuple(advisories),
    )
