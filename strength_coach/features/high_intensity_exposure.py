"""High-intensity exposure and recovery guard.

Tests and near-max attempts are not working volume. They are appended as exposures and used
only for a conservative time-window guard; this module never changes load, RIR or sets.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from strength_coach.store import queries, repositories
from strength_coach.utils import exercises, paths

KINDS = ("test", "max_attempt", "competition", "unplanned", "other")
REGIONS = ("upper", "lower", "axial", "mixed", "unknown")
INTENSITIES = ("near_max", "high", "moderate", "unknown")
TEST_TYPES = ("1RM", "3RM", "5RM", "other")
SOURCE_TYPES = ("test_record", "set_link", "manual")

AXIAL_PATTERNS = {
    "hinge", "hinge_unilateral", "hinge_ballistic", "squat", "squat_unilateral",
    "erector_extension",
}
UPPER_PATTERNS = {
    "horizontal_push", "horizontal_push_bw", "vertical_push", "horizontal_pull",
    "vertical_pull", "elbow_flexion",
}


@dataclass(frozen=True)
class ExposureConfig:
    lookback_days: int = 7
    active_back_symptom_days: int = 14
    windows: dict[str, int] | None = None
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> ExposureConfig:
        source = Path(path or paths.config_dir("high-intensity-exposure.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        return cls(
            lookback_days=int(raw.get("lookback_days", 7)),
            active_back_symptom_days=int(raw.get("active_back_symptom_days", 14)),
            windows={str(k): int(v) for k, v in (raw.get("windows_hours") or {}).items()},
            source_path=source,
        )

    def hours(self, key: str, default: int) -> int:
        return int((self.windows or {}).get(key, default))


@dataclass(frozen=True)
class ExposureStatus:
    status: str                 # clear | caution | blocked
    reason: str
    next_maximal_on: str | None
    active_back_symptom: bool
    exposures: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "next_maximal_on": self.next_maximal_on,
            "active_back_symptom": self.active_back_symptom,
            "exposures": list(self.exposures),
        }


def test_type_for_reps(reps: int) -> str:
    if reps == 1:
        return "1RM"
    if reps <= 4:
        return "3RM"
    if reps == 5:
        return "5RM"
    return "other"


def region_for_exercise(exercise_id: str | None) -> tuple[str, int | None]:
    if not exercise_id:
        return "unknown", None
    entity = exercises.taxonomy().entities.get(str(exercise_id)) or {}
    pattern = entity.get("pattern")
    if pattern in AXIAL_PATTERNS:
        cost = entity.get("spinal_cost")
        return "axial", int(cost) if cost is not None else None
    if pattern in UPPER_PATTERNS:
        return "upper", 0
    return "unknown", None


def _active_back_symptom(conn, on_date: str, config: ExposureConfig) -> bool:
    symptom = queries.latest_symptom(conn, on_date)
    if not symptom or int(symptom.get("level") or 0) <= 0:
        return False
    try:
        days = (dt.date.fromisoformat(on_date)
                - dt.date.fromisoformat(str(symptom["logged_on"]))).days
    except (TypeError, ValueError):
        return False
    return 0 <= days <= config.active_back_symptom_days


def _window_hours(exposure: dict, config: ExposureConfig, active_back: bool) -> int:
    kind = str(exposure["kind"])
    region = str(exposure["region_load"])
    test_type = exposure.get("test_type")

    if kind == "competition":
        return config.hours("competition", 72)
    if region == "upper":
        return config.hours("upper", 24)
    if region in {"lower", "axial", "mixed"}:
        if active_back:
            return max(config.hours("active_back_symptom", 72),
                       config.hours("lower_1rm", 48))
        if kind == "unplanned":
            return config.hours("unplanned_lower", 72)
        if kind == "test" and test_type == "1RM":
            return config.hours("axial_1rm", 48)
        if kind == "test":
            return config.hours("lower_3rm_5rm", 24)
        if kind == "max_attempt":
            return config.hours("lower_1rm", 48)
        return config.hours("unplanned_lower", 72)
    return config.hours("upper", 24)


def _guard_until(exposure: dict, config: ExposureConfig, active_back: bool) -> str:
    hours = _window_hours(exposure, config, active_back)
    days = max(1, math.ceil(hours / 24))
    return (dt.date.fromisoformat(str(exposure["performed_on"]))
            + dt.timedelta(days=days)).isoformat()


def status(conn, on_date: str,
           config: ExposureConfig | None = None) -> ExposureStatus:
    config = config or ExposureConfig.load()
    active_back = _active_back_symptom(conn, on_date, config)
    recent = queries.high_intensity_exposures(
        conn, end=on_date, days=max(config.lookback_days, 7)
    )
    near = [row for row in recent if row["intensity_class"] == "near_max"]
    blocked = [row for row in near if on_date < _guard_until(row, config, active_back)]
    next_dates = [_guard_until(row, config, active_back) for row in blocked]
    next_maximal_on = max(next_dates) if next_dates else None

    if blocked:
        rows = ", ".join(
            f"{row['kind']} {row.get('exercise_id') or ''} on {row['performed_on']}".strip()
            for row in blocked
        )
        return ExposureStatus(
            "blocked", f"near-max exposure in the guard window: {rows}",
            next_maximal_on, active_back, tuple(recent),
        )
    if near:
        return ExposureStatus(
            "caution", "recent near-max exposure; no further near-max exposure is due yet",
            None, active_back, tuple(recent),
        )
    return ExposureStatus("clear", "no recent near-max exposure", None, active_back,
                          tuple(recent))


def register_test(
    conn,
    *,
    override_id: int,
    exercise_id: str,
    performed_on: str,
    test_type: str,
    note: str | None = None,
) -> str:
    """Auto-register the exposure for a test recorded through the app."""
    region, axial_cost = region_for_exercise(exercise_id)
    return repositories.append_high_intensity_exposure(
        conn,
        performed_on=performed_on,
        kind="test",
        exercise_id=exercise_id,
        region_load=region,
        intensity_class="near_max",
        axial_cost=axial_cost,
        test_type=test_type,
        source="test_record",
        source_id=f"e1rm_override:{int(override_id)}",
        note=note,
    )


def log_manual(
    conn,
    *,
    performed_on: str,
    kind: str,
    region_load: str,
    exercise_id: str | None = None,
    intensity_class: str = "near_max",
    axial_cost: int | None = None,
    test_type: str | None = None,
    session_id: str | None = None,
    set_id: int | None = None,
    note: str | None = None,
) -> str:
    """Record an external exposure; a test must use the test path with its override id."""
    if kind == "test":
        raise ValueError("tests must be recorded through the test path")
    return repositories.append_high_intensity_exposure(
        conn,
        performed_on=performed_on,
        kind=kind,
        exercise_id=exercise_id,
        session_id=session_id,
        set_id=set_id,
        region_load=region_load,
        intensity_class=intensity_class,
        axial_cost=axial_cost,
        test_type=test_type,
        source="set_link" if set_id is not None else "manual",
        source_id=f"set:{set_id}" if set_id is not None else None,
        note=note,
    )
