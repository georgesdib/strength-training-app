"""Weekly hard-set ledger by movement pattern.

This is a report, not a prescription controller. It answers "how much did each pattern get?"
and compares the average to a broad config range, so volume drift is visible without inventing
automatic set caps. The set valve under poor readiness remains a separate, explicit rule.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from strength_coach.utils import exercises, paths


@dataclass(frozen=True)
class VolumeConfig:
    window_weeks: int = 4
    ledger_coverage: str = "unknown"
    set_accounting: str = "hard"
    indirect_by_group: Mapping[str, Mapping[str, float]] | None = None
    targets: dict[str, tuple[float, float]] | None = None
    landmarks: dict[str, tuple[float, float, float, float]] | None = None
    apply_mrv_cap: bool = True
    under_mev_enabled: bool = True
    under_mev_weeks: int = 3
    under_mev_add_sets: int = 1
    under_mev_max_sets: int = 8
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> VolumeConfig:
        source = Path(path or paths.config_dir("volume.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        targets = {
            str(key): (float(value[0]), float(value[1]))
            for key, value in (raw.get("targets") or {}).items()
        }
        under = raw.get("under_mev") or {}
        landmarks = {}
        for key, value in (raw.get("landmarks") or {}).items():
            mav = value.get("mav") or [value.get("mev", 0), value.get("mrv", 0)]
            landmarks[str(key)] = (
                float(value.get("mev", 0)),
                float(mav[0]),
                float(mav[1]),
                float(value.get("mrv", mav[1])),
            )
        coverage = str((raw.get("ledger") or {}).get("coverage", "unknown"))
        if coverage not in ("unknown", "complete"):
            raise ValueError("volume ledger coverage must be unknown or complete")
        accounting = str((raw.get("ledger") or {}).get("set_accounting", "hard"))
        if accounting not in ("hard", "effective"):
            raise ValueError("volume ledger set_accounting must be hard or effective")
        indirect_source = paths.config_dir("volume-indirect.v1.yaml")
        indirect_raw = yaml.safe_load(
            indirect_source.read_text(encoding="utf-8")
        ) if indirect_source.exists() else {}
        indirect = {
            str(group): {str(target): float(weight) for target, weight in (targets or {}).items()}
            for group, targets in ((indirect_raw or {}).get("by_group") or {}).items()
        }
        return cls(
            window_weeks=int(raw.get("window_weeks", 4)),
            ledger_coverage=coverage,
            set_accounting=accounting,
            indirect_by_group=indirect,
            targets=targets,
            landmarks=landmarks,
            apply_mrv_cap=bool(raw.get("apply_mrv_cap", True)),
            under_mev_enabled=bool(under.get("enabled", True)),
            under_mev_weeks=max(1, int(under.get("weeks", 3))),
            under_mev_add_sets=max(1, int(under.get("add_sets", 1))),
            under_mev_max_sets=max(1, int(under.get("max_sets_per_item", 8))),
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
    # The landmark key this pattern is judged under. Several raw patterns can share one
    # (core_anti_extension and core_flexion both count as "core"), so the status belongs to
    # the group, not to the row: a sub-pattern below MEV must not add volume to its sibling.
    group: str = ""
    group_average: float = 0.0
    effective_total: float = 0.0

    def as_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "group": self.group or self.pattern,
            "weeks": list(self.weeks),
            "total": self.total,
            "average": round(self.average, 2),
            "group_average": round(self.group_average, 2),
            "effective_total": round(self.effective_total, 2),
            "raw_total": self.total,
            "raw_average": round(self.average, 2),
            "indirect_total": round(max(0.0, self.effective_total - self.total), 2),
            "effective_average": round(self.group_average, 2),
            "target": list(self.target) if self.target else None,
            "status": self.status,
            "mev": self.mev,
            "mav": list(self.mav) if self.mav else None,
            "mrv": self.mrv,
        }


def volume_target_key(pattern: str) -> str:
    """Map a taxonomy pattern to the configured landmark key.

    The mapping is a decision, not an accident, and it is deliberately asymmetric:

    * `squat_unilateral` joins `squat` because split squats load the same quad and glute
      tissue as the bilateral lift and the config gives them no separate landmark;
    * `hinge_unilateral` stays separate because the config *does* carry a
      `hinge_unilateral` landmark, and a single-leg RDL is a low-axial-load accessory that
      should not consume the trap bar's recovery budget;
    * `erector_extension` stays under its own key, which has no landmark at all: direct
      erector work is dosed by PRG-EREC-001 and capped by PRG-SPINE-001, not by MEV/MRV;
    * `hamstring_eccentric` joins `knee_flexion` because a Nordic curl trains the same
      knee-flexion hamstring tissue as a leg curl; without the mapping those sets would fall
      outside every target key and silently vanish from the ledger (DEC-KNEEFLEX-01).

    `tests/test_volume.py` asserts all four, so changing the mapping without changing the
    configured volumes is a test failure rather than a silent drift.
    """
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
    if raw == "hamstring_eccentric":
        return "knee_flexion"
    return raw


def compute(
    sets: pd.DataFrame, *, on_date: str | None = None,
    config: VolumeConfig | None = None,
    excluded_weeks: Iterable[int] = (),
    reset_weeks: Iterable[int] = (),
) -> dict:
    cfg = config or VolumeConfig.load()
    if sets.empty or "date" not in sets or "exercise_id" not in sets:
        return {"from": on_date, "to": on_date, "weeks": [], "patterns": []}
    frame = sets.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    end = pd.Timestamp(on_date) if on_date else frame["date"].max()
    # Calendar-window denominator: the current (possibly partial) ISO week counts as a full
    # week under complete coverage; otherwise the old observed-week denominator is kept.
    current_week_start = end.normalize() - pd.Timedelta(days=end.weekday())
    start = current_week_start - pd.Timedelta(weeks=cfg.window_weeks - 1)
    calendar_labels = [
        int((current_week_start - pd.Timedelta(weeks=offset)).isocalendar().week)
        for offset in range(cfg.window_weeks - 1, -1, -1)
    ]
    if "is_working_set" in frame:
        frame = frame[frame["is_working_set"].astype(bool)]
    frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
    if frame.empty:
        return {"from": start.date().isoformat(), "to": end.date().isoformat(),
                "weeks": [], "patterns": []}

    taxonomy = exercises.taxonomy()
    frame["pattern"] = frame["exercise_id"].map(
        lambda value: (taxonomy.entities.get(str(value), {}) or {}).get("pattern")
    )
    frame = frame[frame["pattern"].notna()]
    frame["iso_week"] = frame["date"].dt.isocalendar().week.astype(int)
    observed = sorted(frame["iso_week"].unique().tolist())
    excluded = {int(week) for week in excluded_weeks}
    resets = {int(week) for week in reset_weeks}
    labels = [week for week in calendar_labels if week not in excluded]
    if cfg.ledger_coverage == "unknown":
        labels = [week for week in observed if week not in excluded]
    training_weeks = len((set(observed) - resets) & set(labels))
    denominator = max(1, len(labels))
    # Two passes: collect the raw patterns, then judge each *landmark group* as a whole.
    # Judging a raw pattern against a merged landmark is what made a low hanging_leg_raise
    # add a set to a well-trained ab_wheel (DEC-VOLUME-05).
    week_positions = {week: index for index, week in enumerate(labels)}
    indirect: dict[str, list[float]] = {}
    if cfg.set_accounting == "effective":
        for row in frame.itertuples(index=False):
            direct = volume_target_key(str(row.pattern))
            for target, weight in (cfg.indirect_by_group or {}).get(direct, {}).items():
                if target == direct or target not in (cfg.landmarks or {}):
                    continue
                indirect.setdefault(target, [0.0] * len(labels))[
                    week_positions[int(row.iso_week)]
                ] += float(weight)
    grouped: dict[str, list[dict]] = {}
    for pattern, group in frame.groupby("pattern"):
        counts = [int((group["iso_week"] == week).sum()) for week in labels]
        total = sum(counts)
        grouped.setdefault(volume_target_key(str(pattern)), []).append({
            "pattern": str(pattern),
            "counts": tuple(counts),
            "total": total,
            "average": total / denominator,
        })

    for target_key, _counts in indirect.items():
        if target_key not in grouped:
            grouped[target_key] = [{
                "pattern": f"indirect:{target_key}",
                "counts": tuple(0 for _ in labels),
                "total": 0,
                "average": 0.0,
            }]
    rows: list[PatternVolume] = []
    for target_key, members in grouped.items():
        landmark = cfg.landmark(target_key) if target_key else None
        target = (landmark[0], landmark[3]) if landmark else None
        indirect_total = sum(indirect.get(target_key, [0.0] * len(labels)))
        group_average = (
            sum(member["total"] for member in members) + indirect_total
        ) / denominator
        if landmark is None:
            status = "untargeted"
        elif training_weeks < len(labels):
            # A zero/missed/break week resets the under-MEV clock; do not add sets on stale evidence.
            status = "insufficient_training"
        elif group_average < landmark[0]:
            status = "under"
        elif group_average > landmark[3]:
            status = "over"
        elif group_average > landmark[2]:
            status = "high"
        else:
            status = "within"
        for member in members:
            rows.append(PatternVolume(
                member["pattern"], member["counts"], member["total"], member["average"],
                target, status,
                mev=landmark[0] if landmark else None,
                mav=(landmark[1], landmark[2]) if landmark else None,
                mrv=landmark[3] if landmark else None,
                group=target_key,
                group_average=group_average,
                effective_total=float(sum(member["total"] for member in members) + indirect_total),
            ))
    rows.sort(key=lambda row: (-row.total, row.pattern))
    zero_weeks = [week for week in labels if week not in set(observed)]
    return {
        "from": start.date().isoformat(),
        "to": end.date().isoformat(),
        "weeks": labels,
        "patterns": [row.as_dict() for row in rows],
        "coverage": {
            "mode": cfg.ledger_coverage,
            "accounting": cfg.set_accounting,
            "window_weeks": cfg.window_weeks,
            "denominator": len(labels),
            "observed_weeks": len(set(observed) & set(labels)),
            "zero_weeks": zero_weeks,
            "excluded_weeks": sorted(excluded),
            "reset_weeks": sorted(resets),
            "training_weeks": training_weeks,
            "complete": training_weeks == len(labels),
        },
    }
