"""Session reconstruction.

The export has no timestamps and no session id (DQ-SESSION-01), so a session is one
calendar date. This is a real limitation, not a stylistic choice: two sessions on the same
day are indistinguishable, and the only defence is to flag the implausible cases rather than
pretend they do not exist.

Day inference is a heuristic and is labelled as such: a session is assigned A/B/C only when
the main lift present, and for the squat/bench pair the emphasis, support it. Otherwise it is
`unknown`, and day-specific rules are not scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from strength_coach.utils import paths

FLAG_DOUBLE_SESSION = "POSSIBLE_DOUBLE_SESSION"
FLAG_NO_MAIN_LIFT = "NO_MAIN_LIFT"
FLAG_SUBSTITUTED_MAIN_LIFT = "SUBSTITUTED_MAIN_LIFT"
FLAG_AMBIGUOUS_DAY = "AMBIGUOUS_DAY"
FLAG_OFF_PROGRAMME = "OFF_PROGRAMME_SESSION"
FLAG_HIGH_WARMUP_SHARE = "HIGH_WARMUP_SHARE"

# Above this share of warm-up rows a session is worth surfacing: it is legal, but it means
# most of the logged rows were ramp-up work, which changes what the session actually was.
HIGH_WARMUP_SHARE = 0.6


@dataclass(frozen=True)
class DayTemplates:
    """Which lifts characterise each day, and how to infer the day from a session."""

    days: dict
    hinge_lift: str
    squat_lifts: tuple[str, ...]
    bench_lifts: tuple[str, ...]
    double_session_set_threshold: int
    version: str = "unversioned"

    @classmethod
    def load(cls, path: str | Path | None = None) -> DayTemplates:
        source = Path(path or paths.config_dir("templates", "days.v1.yaml"))
        with source.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        inference = raw.get("inference", {}) or {}
        return cls(
            days=raw.get("days", {}) or {},
            hinge_lift=str(inference.get("hinge_lift", "trap_bar_deadlift")),
            squat_lifts=tuple(inference.get("squat_lifts", ("ssb_squat",))),
            bench_lifts=tuple(inference.get("bench_lifts", ("bench_press",))),
            double_session_set_threshold=int(
                inference.get("double_session_set_threshold", 35)
            ),
            version=str(raw.get("schema_version", "unversioned")),
        )


@dataclass(frozen=True)
class Session:
    """One reconstructed session."""

    session_id: str
    date: str
    workout_label: str | None
    set_count: int
    working_set_count: int
    exercise_count: int
    main_lifts: tuple[str, ...]
    primary_compounds: tuple[str, ...]
    day: str                # "A" | "B" | "C" | "unknown"
    day_confidence: float   # 0.0-1.0; heuristic, never presented as certainty
    day_reason: str         # why the day was assigned or left unknown
    tonnage_kg: float | None
    warmup_share: float
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_ambiguous_day(self) -> bool:
        return self.day == "unknown"


@lru_cache(maxsize=1)
def day_templates() -> DayTemplates:
    return DayTemplates.load()


def build_sessions(
    clean_sets: pd.DataFrame,
    *,
    templates: DayTemplates | None = None,
) -> list[Session]:
    """Group clean sets into sessions and infer the programme day for each."""
    templates = templates or day_templates()
    if clean_sets.empty:
        return []

    sessions: list[Session] = []
    for date, group in clean_sets.groupby("date", sort=True):
        sessions.append(_build_one(date, group, templates))
    return sessions


def _build_one(date, group: pd.DataFrame, templates: DayTemplates) -> Session:
    exercise_ids = tuple(sorted(set(group["exercise_id"].dropna())))
    main_lifts = tuple(sorted({eid for eid in exercise_ids if _has_prop(eid, "main_lift")}))
    primary = tuple(
        sorted({eid for eid in exercise_ids if _has_prop(eid, "primary_compound")})
    )

    working = group[group["is_working_set"]]
    tonnage = physical_tonnage(working)

    day, confidence, reason = infer_day(group, exercise_ids, templates)

    flags: list[str] = []
    if len(group) > templates.double_session_set_threshold:
        # A single session this large is implausible for this programme; most likely two
        # sessions merged by the missing timestamp (DQ-SESSION-01).
        flags.append(FLAG_DOUBLE_SESSION)
    if not main_lifts:
        # Distinguish "trained a heavy compound instead of the named lift" from "trained no
        # heavy compound at all". The former is a programme substitution worth flagging; the
        # latter is usually an accessory-only session.
        flags.append(
            FLAG_SUBSTITUTED_MAIN_LIFT if primary else FLAG_NO_MAIN_LIFT
        )
    if day == "unknown":
        flags.append(FLAG_AMBIGUOUS_DAY)
        if reason in {"bench_only", "squat_only", "no_primary"}:
            flags.append(FLAG_OFF_PROGRAMME)

    warmup_share = float((~group["is_working_set"]).mean()) if len(group) else 0.0
    if warmup_share > HIGH_WARMUP_SHARE:
        flags.append(FLAG_HIGH_WARMUP_SHARE)

    labels = group["workout_label"].dropna().unique()
    return Session(
        session_id=pd.Timestamp(date).date().isoformat(),
        date=pd.Timestamp(date).date().isoformat(),
        workout_label=str(labels[0]) if len(labels) == 1 else None,
        set_count=int(len(group)),
        working_set_count=int(len(working)),
        exercise_count=len(exercise_ids),
        main_lifts=main_lifts,
        primary_compounds=primary,
        day=day,
        day_confidence=confidence,
        day_reason=reason,
        tonnage_kg=tonnage,
        warmup_share=round(warmup_share, 2),
        flags=tuple(flags),
    )


def infer_day(
    group: pd.DataFrame,
    exercise_ids: tuple[str, ...],
    templates: DayTemplates,
) -> tuple[str, float]:
    """Infer A/B/C from the main lifts present, with a confidence.

    Order matters: the hinge is decisive because the programme only puts it on day B. A and C
    both contain squat and bench, so they are separated by which lift got more sets — a
    heuristic, hence the confidence value rather than a boolean.
    """
    present = set(exercise_ids)

    if templates.hinge_lift in present:
        return "B", 0.95, "hinge"

    has_squat = bool(present & set(templates.squat_lifts))
    has_bench = bool(present & set(templates.bench_lifts))

    if not has_squat and not has_bench:
        return "unknown", 0.0, "no_primary"

    counts = group.groupby("exercise_id").size()
    squat_sets = int(sum(counts.get(lift, 0) for lift in templates.squat_lifts))
    bench_sets = int(sum(counts.get(lift, 0) for lift in templates.bench_lifts))

    if has_squat and not has_bench:
        # Squat-only is not one of the programme's three days, so it stays unassigned rather
        # than being forced into A. Every programme day contains a press.
        return "unknown", 0.2, "squat_only"

    if has_bench and has_squat:
        if squat_sets > bench_sets:
            margin = (squat_sets - bench_sets) / max(squat_sets + bench_sets, 1)
            return "A", round(0.5 + 0.5 * margin, 2), "squat_emphasis"
        margin = (bench_sets - squat_sets) / max(squat_sets + bench_sets, 1)
        return "C", round(0.5 + 0.5 * margin, 2), "bench_emphasis"

    # Bench-only sessions are not one of the three programme days either.
    return "unknown", 0.3, "bench_only"


def _has_prop(exercise_id: str, prop: str) -> bool:
    from strength_coach.utils import exercises

    entity = exercises.taxonomy().entities.get(exercise_id) or {}
    return bool(entity.get(prop, False))


def physical_tonnage(working_sets: pd.DataFrame) -> float | None:
    """Total added load moved on working, rep-based sets.

    Bodyweight mass is excluded on purpose: including it would let pull-ups out-tonnage a
    deadlift session and destroy week-on-week comparability. Warm-ups are excluded because
    DEC-RIR-01 makes them visible and separable.
    """
    valid = working_sets.dropna(subset=["tonnage_kg"])
    if valid.empty:
        return None
    return float(valid["tonnage_kg"].sum())
