"""Optional main-lift top-set/back-off structure.

This module owns only the set arithmetic and RIR resolution. It does not choose exercises,
apply readiness/deload, run the volume budget or write persistence; those remain in the engine
and the existing pipeline. The structure is intentionally a set-group on one item, never two
same-exercise item rows. `SetGroup.role` here is an internal build-time tag: the wire, the
stored plan and analysis see only the ordered groups (DEC-RESOLVER-18).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.prescribe import loads
from strength_coach.prescribe.models import PrescriptionItem, SetGroup
from strength_coach.prescribe.resolver_settings import ResolverSettings

TOP_SET = "top_set"
BACK_OFF = "back_off"


@dataclass(frozen=True)
class TopSetPlan:
    applied: bool
    status: str
    reason_code: str
    reason: str
    groups: tuple[SetGroup, ...] = ()
    top_set_rir: int | None = None
    top_set_load: float | None = None
    backoff_load: float | None = None


def competition_window(
    competition_date: str | None,
    for_date: str,
    settings: ResolverSettings,
) -> str:
    """Return none, peak or taper for the configured competition date."""
    if not competition_date or not settings.competition_override_enabled:
        return "none"
    try:
        competition = dt.date.fromisoformat(str(competition_date))
        day = dt.date.fromisoformat(str(for_date))
    except ValueError:
        return "none"
    days = (competition - day).days
    if days < 0:
        return "none"
    if days <= settings.competition_taper_days:
        return "taper"
    if days <= settings.competition_peak_weeks * 7:
        return "peak"
    return "none"


def resolved_top_set_rir(
    *,
    scheme: str | None,
    window: str,
    settings: ResolverSettings,
) -> tuple[int | None, str]:
    """Resolve the top-set RIR from the applied DUP scheme and competition window."""
    if window == "taper":
        return None, "competition taper: straight sets"
    if window == "peak":
        return 1, "competition peak: RIR 1"
    if scheme == "maximal":
        value = settings.top_set_rir_maximal
    elif scheme == "strength":
        value = settings.top_set_rir_strength
    else:
        value = settings.top_set_rir_off
    value = max(1, int(value))
    if value > settings.top_set_fallback_above_rir:
        return None, (
            f"configured top-set RIR {value} is above the RIR ceiling "
            f"{settings.top_set_fallback_above_rir}"
        )
    return value, f"DUP {scheme or 'off'}: RIR {value}"


def _classify(
    item: PrescriptionItem,
    *,
    primary_exercise: str | None,
    eligible_lifts: tuple[str, ...],
    settings: ResolverSettings,
) -> tuple[str, str, str]:
    """Classify the primary item as eligible, by-design blocked or unexpectedly blocked."""
    if settings.top_set_eligible == "session_main" and item.exercise_id != primary_exercise:
        return "by_design", "blocked_by_design", "not the session primary main lift"
    if item.effort_model != "rir" or not item.essential:
        return "unexpected", "not_eligible", "not an essential RIR main lift"
    if item.exercise_id not in eligible_lifts:
        return "unexpected", "outside_policy", (
            "lift is not top-set eligible in the resolver policy"
        )
    return "eligible", "applied", "top set requested"


def _blocked(intent: str, verdict: str, reason_code: str, reason: str) -> TopSetPlan:
    """A by-design block is not_applicable; an unexpected one depends on the intent."""
    if verdict == "by_design":
        return TopSetPlan(False, "not_applicable", "blocked_by_design", reason)
    status = "fallback" if intent == "preferred" else "unsatisfied"
    return TopSetPlan(False, status, reason_code, reason)


def plan_top_set(
    item: PrescriptionItem,
    *,
    settings: ResolverSettings,
    eligible_lifts: tuple[str, ...],
    primary_exercise: str | None,
    scheme: str | None,
    competition_date: str | None,
    for_date: str,
    deload: bool,
    intent: str,
    readiness_bump: int = 0,
    blocked_reason: str | None = None,
) -> TopSetPlan:
    """Build one top set plus back-offs, or return a transparent non-application reason.

    One readiness step is absorbed by the ceiling: the top set stays the hardest set of the
    session and the back-offs take the raised RIR. A two-step readiness drop, a continuity gap
    or a back flare keeps the straight-set fallback (DEC-RESOLVER-14).
    """
    if intent == "off":
        return TopSetPlan(False, "not_applicable", "intent_off", "top-set intent is off")
    if intent not in ("preferred", "required"):
        raise ValueError("top-set intent must be off, preferred or required")
    verdict, reason_code, reason = _classify(
        item,
        primary_exercise=primary_exercise,
        eligible_lifts=eligible_lifts,
        settings=settings,
    )
    if verdict != "eligible":
        return _blocked(intent, verdict, reason_code, reason)
    if deload:
        return _blocked(
            intent, "by_design", "blocked_by_design", "deload week: straight sets"
        )
    if blocked_reason is not None:
        return _blocked(intent, "by_design", "blocked_by_design", blocked_reason)
    if readiness_bump > 1:
        return _blocked(
            intent,
            "by_design",
            "blocked_by_design",
            f"readiness lowered the working RIR by {readiness_bump} steps; straight sets",
        )
    window = competition_window(competition_date, for_date, settings)
    if window == "taper":
        return _blocked(
            intent, "by_design", "blocked_by_design", "competition taper: straight sets"
        )
    rir, rir_reason = resolved_top_set_rir(
        scheme=scheme, window=window, settings=settings
    )
    if rir is None:
        return _blocked(intent, "unexpected", "outside_policy", rir_reason)
    rir = min(
        max(1, int(rir) + int(readiness_bump)),
        settings.top_set_fallback_above_rir,
    )
    if readiness_bump:
        rir_reason = (
            f"{rir_reason}; readiness +{readiness_bump} absorbed by the ceiling, RIR {rir}"
        )
    else:
        rir_reason = f"{rir_reason}; final RIR {rir}"
    if item.load_kg is None or item.load_kg <= 0:
        return _blocked(
            intent, "unexpected", "no_usable_load", "no usable main-lift load"
        )
    # Use the item's final load/RIR so readiness, continuity and back-flare reductions are
    # already reflected. The stored e1RM is a fallback when the final RIR is unavailable.
    e1rm_kg = None
    if item.rir_target is not None:
        e1rm_kg = e1rm_mod.epley_rir_adjusted(
            float(item.load_kg), int(item.reps_low), int(item.rir_target)
        )
    if e1rm_kg is None:
        e1rm_kg = item.e1rm_kg
    if e1rm_kg is None:
        return _blocked(
            intent, "unexpected", "no_usable_load", "no usable main-lift e1RM"
        )
    if item.sets < 2:
        return _blocked(
            intent,
            "unexpected",
            "fewer_than_two_sets",
            "one working set cannot form top plus back-off",
        )
    top_load = loads.solve_load(
        float(e1rm_kg), int(item.reps_low), rir, item.rounding_increment_kg
    )
    # The top-set structure is a set-configuration choice, not extra volume: one top set
    # plus back-offs must equal the blueprint's total working sets (DEC-RESOLVER-03).
    backoff_sets = item.sets - 1
    if backoff_sets < 1:
        return _blocked(
            intent, "unexpected", "fewer_than_two_sets", "no set left for back-off work"
        )
    backoff_load = loads.round_down(
        top_load * settings.top_set_backoff_percent, item.rounding_increment_kg
    )
    groups = (
        SetGroup(
            role=TOP_SET,
            sets=1,
            load_kg=top_load,
            reps_low=item.reps_low,
            reps_high=item.reps_high,
            rir_target=rir,
            percent_of_top=None,
        ),
        SetGroup(
            role=BACK_OFF,
            sets=backoff_sets,
            load_kg=backoff_load,
            reps_low=item.reps_low,
            reps_high=item.reps_high,
            rir_target=item.rir_target,
            percent_of_top=settings.top_set_backoff_percent,
        ),
    )
    return TopSetPlan(
        True,
        "applied",
        "applied",
        f"{rir_reason}; top set + {backoff_sets} back-off set(s) at "
        f"{settings.top_set_backoff_percent:.0%}",
        groups=groups,
        top_set_rir=rir,
        top_set_load=top_load,
        backoff_load=backoff_load,
    )


def apply_plan(item: PrescriptionItem, plan: TopSetPlan) -> PrescriptionItem:
    """Attach a plan while keeping the total working-set count and normal summary load."""
    if not plan.applied:
        return item
    from dataclasses import replace

    return replace(
        item,
        set_groups=plan.groups,
        load_kg=plan.backoff_load,
        rir_target=item.rir_target,
    )
