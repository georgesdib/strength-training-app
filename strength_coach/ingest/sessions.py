"""Session reconstruction.

The export has no timestamps and no session id (DQ-SESSION-01), so a session is one
calendar date. This is a real limitation, not a stylistic choice: two sessions on the same
day are indistinguishable, and the only defence is to flag the implausible cases rather than
pretend they do not exist.

Session-type inference is a heuristic and is labelled as such: a session is assigned
squat/hinge/bench_squat/bench_hinge only when the lifts present distinguish it. Otherwise it is
`unknown`, and type-specific rules are not scored.
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
FLAG_AMBIGUOUS_SESSION_TYPE = "AMBIGUOUS_DAY"
FLAG_OFF_PROGRAMME = "OFF_PROGRAMME_SESSION"
FLAG_HIGH_WARMUP_SHARE = "HIGH_WARMUP_SHARE"

# Above this share of warm-up rows a session is worth surfacing: it is legal, but it means
# most of the logged rows were ramp-up work, which changes what the session actually was.
HIGH_WARMUP_SHARE = 0.6


@dataclass(frozen=True)
class SessionInference:
    """Which lifts distinguish a session type."""

    hinge_lift: str
    hinge_support_lifts: tuple[str, ...]
    squat_lifts: tuple[str, ...]
    bench_lifts: tuple[str, ...]
    double_session_set_threshold: int
    version: str = "unversioned"

    @classmethod
    def load(cls, path: str | Path | None = None) -> "SessionInference":
        source = Path(path or paths.config_dir("templates", "inference.v1.yaml"))
        with source.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        return cls(
            hinge_lift=str(raw.get("hinge_lift", "trap_bar_deadlift")),
            hinge_support_lifts=tuple(raw.get("hinge_support_lifts", ())),
            squat_lifts=tuple(raw.get("squat_lifts", ())),
            bench_lifts=tuple(raw.get("bench_lifts", ())),
            double_session_set_threshold=int(raw.get("double_session_set_threshold", 35)),
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
    session_type: str       # squat | hinge | bench_squat | bench_hinge | unknown
    tonnage_kg: float | None
    warmup_share: float
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_ambiguous_session(self) -> bool:
        return self.session_type == "unknown"


@lru_cache(maxsize=1)
def session_inference() -> SessionInference:
    return SessionInference.load()


def build_sessions(
    clean_sets: pd.DataFrame,
    *,
    templates: SessionInference | None = None,
) -> list[Session]:
    """Group clean sets into sessions and infer the canonical session type for each."""
    templates = templates or session_inference()
    if clean_sets.empty:
        return []

    sessions: list[Session] = []
    for date, group in clean_sets.groupby("date", sort=True):
        sessions.append(_build_one(date, group, templates))
    return sessions


def _build_one(date, group: pd.DataFrame, templates: SessionInference) -> Session:
    exercise_ids = tuple(sorted(set(group["exercise_id"].dropna())))
    main_lifts = tuple(sorted({eid for eid in exercise_ids if _has_prop(eid, "main_lift")}))
    primary = tuple(
        sorted({eid for eid in exercise_ids if _has_prop(eid, "primary_compound")})
    )

    working = group[group["is_working_set"]]
    tonnage = physical_tonnage(working)

    session_type = infer_session_type(group, exercise_ids, templates)

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
    if session_type == "unknown":
        flags.append(FLAG_AMBIGUOUS_SESSION_TYPE)
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
        session_type=session_type,
        tonnage_kg=tonnage,
        warmup_share=round(warmup_share, 2),
        flags=tuple(flags),
    )


def infer_session_type(
    group: pd.DataFrame,
    exercise_ids: tuple[str, ...],
    templates: SessionInference,
) -> str:
    """Infer one of the four canonical types from the exercises present, or unknown."""
    present = set(exercise_ids)
    if templates.hinge_lift in present:
        return "hinge"

    has_squat = bool(present & set(templates.squat_lifts))
    has_bench = bool(present & set(templates.bench_lifts))
    has_hinge_support = bool(present & set(templates.hinge_support_lifts))

    if has_bench and has_hinge_support and not has_squat:
        return "bench_hinge"
    if has_squat and has_bench:
        counts = group.groupby("exercise_id").size()
        squat_sets = int(sum(counts.get(lift, 0) for lift in templates.squat_lifts))
        bench_sets = int(sum(counts.get(lift, 0) for lift in templates.bench_lifts))
        if squat_sets > bench_sets:
            return "squat"
        if bench_sets > squat_sets:
            return "bench_squat"
    return "unknown"


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
