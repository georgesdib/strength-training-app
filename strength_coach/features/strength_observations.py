"""Raw, uncalibrated performance observations for monitoring.

This module is deliberately separate from the prescription load base. It computes an
Epley/Epley+RIR estimate from a completed set, then applies the monitoring eligibility and
quality rules. It never applies age decay or calibration, and it never reads the load-base
selector or a calibration factor.

Why a separate module: the prescription selector answers "what load should be prescribed?"
and includes overrides, decay and calibration. Monitoring answers "what did the athlete
actually lift?" and must remain a plain formula-derived observation. Mixing the two would
make a performance series move when prescription configuration changes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.domain import rir as rir_mod
from strength_coach.features import derived
from strength_coach.utils import exercises

# Raw observations are always tagged with the formula used. The separate version constant
# belongs to the later monitoring-core phase; this module only needs a stable method name.
METHOD_EPLEY_RIR = "epley_plus_rir"
METHOD_EPLEY = "epley"

QUALITY_OK = "ok"
QUALITY_DEGRADED = "degraded"

STATUS_ESTIMATED = "estimated"
STATUS_UNAVAILABLE = "unavailable"
STATUS_INVALID = "invalid"
STATUS_NOT_APPLICABLE = "not_applicable"

# Explicit exclusion reasons. The audit groups these rather than inferring an exclusion from
# a generic "invalid" bucket.
REASON_POWER = "power-classified exercise (pattern=power_jump)"
REASON_EXPOSURE_PREFIX = "linked to high-intensity exposure: "


@dataclass(frozen=True)
class RawEstimate:
    """One eligible set-level raw e1RM, with provenance required to interpret it."""

    kg: float
    method: str
    quality: str
    session_id: str
    occurred_on: str
    exercise_id: str
    set_id: int | None
    load_kg: float
    total_load_kg: float
    reps: int
    rir: int
    flags: tuple[str, ...]
    method_version: str = e1rm_mod.E1RM_METHOD_VERSION
    status: str = STATUS_ESTIMATED

    @property
    def is_ok(self) -> bool:
        return self.quality == QUALITY_OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "kg": round(self.kg, 3),
            "method": self.method,
            "method_version": self.method_version,
            "quality": self.quality,
            "session_id": self.session_id,
            "occurred_on": self.occurred_on,
            "exercise_id": self.exercise_id,
            "set_id": self.set_id,
            "load_kg": round(self.load_kg, 3),
            "total_load_kg": round(self.total_load_kg, 3),
            "reps": self.reps,
            "rir": self.rir,
            "flags": list(self.flags),
            "status": self.status,
        }


@dataclass(frozen=True)
class Unavailable:
    """A value that cannot be computed, with the reason rather than an invented zero."""

    reason: str
    status: str = STATUS_UNAVAILABLE

    def as_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "status": self.status}


@dataclass(frozen=True)
class SessionObservation:
    """The best eligible raw estimate for one exercise in one session."""

    exercise_id: str
    session_id: str
    occurred_on: str
    estimate: RawEstimate


@dataclass(frozen=True)
class Reference:
    """Median of recent eligible session bests, with its own sufficiency status."""

    kg: float
    n: int
    status: str
    observations: tuple[SessionObservation, ...]
    as_of: str
    max_age_days: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kg": round(self.kg, 3),
            "n": self.n,
            "status": self.status,
            "as_of": self.as_of,
            "max_age_days": self.max_age_days,
            "dates": [observation.occurred_on for observation in self.observations],
        }


@dataclass(frozen=True)
class Difference:
    """Post-session best minus the recent reference; never a significance claim."""

    kg: float | None
    pct: float | None
    status: str
    reason: str
    post: RawEstimate | None
    reference: Reference | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kg": None if self.kg is None else round(self.kg, 3),
            "pct": None if self.pct is None else round(self.pct, 3),
            "status": self.status,
            "reason": self.reason,
            "post": None if self.post is None else self.post.as_dict(),
            "reference": None if self.reference is None else self.reference.as_dict(),
        }


def _value(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    value = row.get(key, default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(round(number))


def _flags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(";") if part.strip()]
    else:
        parts = [str(part).strip() for part in value if str(part).strip()]
    return tuple(sorted(set(parts)))


def _date(value: Any) -> str:
    if value is None:
        return ""
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _props_for(exercise_id: str) -> dict[str, Any]:
    return dict(exercises.taxonomy().entities.get(exercise_id, {}))


def _raw_load(row: Mapping[str, Any]) -> tuple[float, float] | Unavailable:
    """Return (load, total load) or explain why total load cannot be resolved.

    The cleaner's total_load_kg is authoritative when present. queries.clean_sets currently
    collapses added-load total mass to load_kg; that is rejected here rather than silently
    turning an added plate into a total-load e1RM.
    """
    load = _number(_value(row, "load_kg"))
    if load is None or load <= 0:
        return Unavailable("missing or non-positive load", STATUS_INVALID)

    basis = str(_value(row, "load_basis", "") or "")
    total = _number(_value(row, "total_load_kg"))

    if basis in {"external", "bodyweight_total"}:
        return load, load if total is None or total <= 0 else total
    if basis == "added":
        if total is None or total <= load:
            return Unavailable(
                "added-load total mass is unresolved; e1RM would omit bodyweight",
                STATUS_UNAVAILABLE,
            )
        return load, total
    return Unavailable("load basis is unknown", STATUS_INVALID)


def _exclusion_kind(
    set_row: Mapping[str, Any],
    excluded_set_kinds: Mapping[int, str] | None,
) -> str | None:
    if not excluded_set_kinds:
        return None
    set_id = _integer(_value(set_row, "set_id"))
    if set_id is None:
        return None
    return excluded_set_kinds.get(int(set_id))


def raw_set_e1rm(
    set_row: Mapping[str, Any],
    taxonomy_props: Mapping[str, Any] | None = None,
    *,
    excluded_set_kinds: Mapping[int, str] | None = None,
) -> RawEstimate | Unavailable:
    """Compute one eligible raw e1RM from a completed set.

    Eligibility is intentionally strict: working set, reps unit, RIR 0-5, usable load,
    reps+rir <= 20, and e1rm_applicable. Missing RIR is not replaced by plain Epley in the
    monitoring series; a missing observation stays missing.
    """
    exercise_id = str(_value(set_row, "exercise_id", "") or "")
    props = dict(taxonomy_props) if taxonomy_props is not None else _props_for(exercise_id)

    # Power/plyometric work is not a strength e1RM observation, even if a loadable variant
    # would otherwise pass the structural e1rm_applicable rule.
    if str(props.get("pattern") or "") == "power_jump":
        return Unavailable(REASON_POWER, STATUS_INVALID)

    exposure_kind = _exclusion_kind(set_row, excluded_set_kinds)
    if exposure_kind is not None:
        return Unavailable(f"{REASON_EXPOSURE_PREFIX}{exposure_kind}", STATUS_INVALID)

    if not derived.e1rm_applicable(props):
        return Unavailable("e1RM is not applicable to this exercise", STATUS_NOT_APPLICABLE)

    flags = _flags(_value(set_row, "flags"))
    if any(flag in flags for flag in ("WARMUP", "REPS_TYPO", "SECONDS_NOT_REPS", "LOAD_BASIS_UNKNOWN")):
        return Unavailable("set is a warm-up or has a disqualifying data flag", STATUS_INVALID)

    working = _value(set_row, "is_working_set")
    if working is not None and not bool(working):
        return Unavailable("set is not a working set", STATUS_INVALID)

    reps_unit = str(_value(set_row, "reps_unit", "reps") or "reps")
    if reps_unit != "reps":
        return Unavailable("set is time-based, not rep-based", STATUS_INVALID)

    reps = _integer(_value(set_row, "reps"))
    if reps is None or reps <= 0:
        return Unavailable("missing or non-positive reps", STATUS_INVALID)
    if reps > e1rm_mod.MAX_USABLE_REPS:
        return Unavailable("reps exceed the usable e1RM cap", STATUS_INVALID)

    rir_value = _value(set_row, "rir")
    rir_reading = rir_mod.classify(rir_value)
    if rir_reading.klass != "effort" or rir_reading.value is None:
        return Unavailable("RIR is missing, warm-up or off-scale", STATUS_INVALID)
    rir = int(rir_reading.value)
    if reps + rir > e1rm_mod.MAX_USABLE_REPS:
        return Unavailable("reps + RIR exceed the usable e1RM cap", STATUS_INVALID)

    load_pair = _raw_load(set_row)
    if isinstance(load_pair, Unavailable):
        return load_pair
    load, total = load_pair

    estimate = e1rm_mod.estimate_e1rm(total, reps, rir, use_rir=True)
    if estimate is None or estimate.method != METHOD_EPLEY_RIR:
        return Unavailable("domain formula could not produce an RIR-adjusted estimate", STATUS_INVALID)

    session_id = str(_value(set_row, "session_id", "") or "")
    occurred_on = _date(_value(set_row, "date"))
    if not session_id or not occurred_on:
        return Unavailable("session id or date is missing", STATUS_INVALID)

    set_id_value = _integer(_value(set_row, "set_id"))
    # Phase 0 quality is deliberately explicit: domain.e1rm classifies by reps only,
    # while monitoring also treats RIR 4-5 as degraded. Invalid RIR/reps were rejected above.
    quality = (
        QUALITY_OK
        if reps <= e1rm_mod.MAX_RELIABLE_REPS and rir <= 3
        else QUALITY_DEGRADED
    )
    return RawEstimate(
        kg=float(estimate.value_kg),
        method=estimate.method,
        quality=quality,
        session_id=session_id,
        occurred_on=occurred_on,
        exercise_id=exercise_id,
        set_id=set_id_value,
        load_kg=load,
        total_load_kg=total,
        reps=reps,
        rir=rir,
        flags=flags,
        method_version=e1rm_mod.E1RM_METHOD_VERSION,
    )


def session_best(
    frame: pd.DataFrame,
    session_id: str,
    exercise_id: str,
    taxonomy_props: Mapping[str, Any] | None = None,
    *,
    excluded_set_kinds: Mapping[int, str] | None = None,
) -> RawEstimate | Unavailable:
    """Highest eligible *ok* set-level raw e1RM in one session/exercise.

    Degraded estimates are intentionally excluded from the headline and from the reference
    series. They are still available from raw_set_e1rm for separate display.
    """
    if frame is None or frame.empty:
        return Unavailable("no sets in frame", STATUS_UNAVAILABLE)
    mask = (
        frame["session_id"].astype(str).eq(str(session_id))
        & frame["exercise_id"].astype(str).eq(str(exercise_id))
    )
    rows = frame.loc[mask].to_dict("records")
    if not rows:
        return Unavailable("session/exercise has no sets", STATUS_UNAVAILABLE)

    props = dict(taxonomy_props) if taxonomy_props is not None else _props_for(exercise_id)
    best: RawEstimate | None = None
    degraded = False
    for row in rows:
        result = raw_set_e1rm(row, props, excluded_set_kinds=excluded_set_kinds)
        if isinstance(result, Unavailable):
            continue
        if result.quality != QUALITY_OK:
            degraded = True
            continue
        if best is None or (result.kg, result.set_id or -1) > (best.kg, best.set_id or -1):
            best = result
    if best is not None:
        return best
    if degraded:
        return Unavailable("only degraded estimates; no ok estimate", STATUS_UNAVAILABLE)
    return Unavailable("no eligible estimate", STATUS_UNAVAILABLE)


def session_observations(
    frame: pd.DataFrame,
    exercise_id: str,
    before_date: str,
    cutoff_session_id: str | None = None,
    *,
    excluded_set_kinds: Mapping[int, str] | None = None,
) -> list[SessionObservation]:
    """Eligible session bests for one exercise strictly before the given date.

    The cutoff is exclusive, so same-date sessions are excluded rather than ordered by an
    assumption. The caller must pass the next session's date.
    """
    if frame is None or frame.empty:
        return []
    try:
        cutoff = pd.Timestamp(before_date)
    except (TypeError, ValueError):
        return []

    work = frame.copy()
    work["_date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work[
        work["exercise_id"].astype(str).eq(str(exercise_id))
        & work["_date"].notna()
        & (work["_date"] < cutoff)
    ]
    if cutoff_session_id is not None:
        work = work[work["session_id"].astype(str).ne(str(cutoff_session_id))]
    if work.empty:
        return []

    props = _props_for(exercise_id)
    observations: list[SessionObservation] = []
    for session_id, group in work.groupby("session_id", sort=True):
        best = session_best(
            group,
            str(session_id),
            exercise_id,
            props,
            excluded_set_kinds=excluded_set_kinds,
        )
        if isinstance(best, Unavailable):
            continue
        observations.append(
            SessionObservation(
                exercise_id=exercise_id,
                session_id=str(session_id),
                occurred_on=best.occurred_on,
                estimate=best,
            )
        )
    observations.sort(key=lambda item: (item.occurred_on, item.session_id))
    return observations


def recent_reference(
    observations: Sequence[SessionObservation],
    n: int = 3,
    max_age_days: int = 84,
    as_of: str | None = None,
) -> Reference | Unavailable:
    """Median of the last n eligible session bests within the age window."""
    if not observations:
        return Unavailable("no eligible observations", STATUS_UNAVAILABLE)
    ordered = sorted(observations, key=lambda item: (item.occurred_on, item.session_id))
    anchor_value = as_of or ordered[-1].occurred_on
    try:
        anchor = pd.Timestamp(anchor_value)
    except (TypeError, ValueError):
        return Unavailable("invalid as-of date", STATUS_INVALID)
    cutoff = anchor - pd.Timedelta(days=max_age_days)
    recent = [
        item
        for item in ordered
        if cutoff <= pd.Timestamp(item.occurred_on) <= anchor
    ][-max(1, int(n)):]
    if not recent:
        return Unavailable("no observation inside the age window", STATUS_UNAVAILABLE)
    count = len(recent)
    status = "descriptive" if count >= 3 else ("limited" if count == 2 else "single_prior")
    values = sorted(item.estimate.kg for item in recent)
    middle = len(values) // 2
    median_kg = (
        values[middle]
        if len(values) % 2
        else (values[middle - 1] + values[middle]) / 2.0
    )
    return Reference(
        kg=float(median_kg),
        n=count,
        status=status,
        observations=tuple(recent),
        as_of=anchor.date().isoformat(),
        max_age_days=max_age_days,
    )


def best_recent(
    observations: Sequence[SessionObservation],
    max_age_days: int = 84,
    as_of: str | None = None,
) -> RawEstimate | Unavailable:
    """Highest eligible session best inside the recent age window."""
    if not observations:
        return Unavailable("no eligible observations", STATUS_UNAVAILABLE)
    ordered = sorted(observations, key=lambda item: (item.occurred_on, item.session_id))
    anchor_value = as_of or ordered[-1].occurred_on
    try:
        anchor = pd.Timestamp(anchor_value)
    except (TypeError, ValueError):
        return Unavailable("invalid as-of date", STATUS_INVALID)
    cutoff = anchor - pd.Timedelta(days=max_age_days)
    recent = [
        item for item in ordered
        if cutoff <= pd.Timestamp(item.occurred_on) <= anchor
    ]
    if not recent:
        return Unavailable("no observation inside the age window", STATUS_UNAVAILABLE)
    return max(
        (item.estimate for item in recent),
        key=lambda estimate: (estimate.kg, estimate.set_id or -1),
    )


def personal_best(observations: Sequence[SessionObservation]) -> RawEstimate | Unavailable:
    """Highest eligible session best in the full observation history."""
    if not observations:
        return Unavailable("no eligible observations", STATUS_UNAVAILABLE)
    return max(
        (item.estimate for item in observations),
        key=lambda estimate: (estimate.kg, estimate.set_id or -1),
    )


def difference_vs_recent(
    post: RawEstimate | Unavailable,
    reference: Reference | Unavailable,
) -> Difference:
    """Descriptive post minus recent median; no significance or meaningfulness claim."""
    if isinstance(post, Unavailable):
        return Difference(None, None, post.status, post.reason, None, None)
    if isinstance(reference, Unavailable):
        return Difference(None, None, reference.status, reference.reason, post, None)
    if post.quality != QUALITY_OK:
        return Difference(
            None,
            None,
            "insufficient_quality",
            "post-session estimate is degraded",
            post,
            reference,
        )
    if reference.n < 2:
        return Difference(
            None,
            None,
            "single_prior",
            "at least two recent observations are required for a difference",
            post,
            reference,
        )
    delta = post.kg - reference.kg
    pct = (delta / reference.kg * 100.0) if reference.kg else None
    status = "descriptive" if reference.n >= 3 else "limited"
    return Difference(delta, pct, status, "", post, reference)
