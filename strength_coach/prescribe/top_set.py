"""Optional main-lift top-set/back-off structure.

This module owns only the set arithmetic and RIR resolution. It does not choose exercises,
apply readiness/deload, run the volume budget or write persistence; those remain in the engine
and the existing pipeline. The structure is intentionally a set-group on one item, never two
same-exercise item rows.
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
        return None, f"resolved top-set RIR {value} is above the fallback threshold"
    return value, f"DUP {scheme or 'off'}: RIR {value}"


def eligible(
    item: PrescriptionItem,
    *,
    primary_exercise: str | None,
    eligible_lifts: tuple[str, ...],
    settings: ResolverSettings,
    requested: bool | None,
) -> tuple[bool, str]:
    """Whether this item is the opted-in top-set main lift."""
    if settings.top_set_mode == "off":
        return False, "top set mode is off"
    if item.effort_model != "rir" or not item.essential:
        return False, "not an essential RIR main lift"
    if settings.top_set_eligible == "session_main" and item.exercise_id != primary_exercise:
        return False, "not the session primary main lift"
    if item.exercise_id not in eligible_lifts:
        return False, "lift is not top-set eligible in the resolver policy"
    if requested is False:
        return False, "athlete declined the top set"
    if requested is None and settings.top_set_mode == "ask":
        return False, "top set offered; awaiting confirmation"
    return True, "top set requested"


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
    requested: bool | None,
    rir_bump: int = 0,
) -> TopSetPlan:
    """Build one top set plus back-offs, or return a transparent non-application reason."""
    is_eligible, reason = eligible(
        item,
        primary_exercise=primary_exercise,
        eligible_lifts=eligible_lifts,
        settings=settings,
        requested=requested,
    )
    if not is_eligible:
        return TopSetPlan(False, "not_applied", reason)
    if deload:
        return TopSetPlan(False, "not_applied", "deload week: straight sets")
    window = competition_window(competition_date, for_date, settings)
    rir, rir_reason = resolved_top_set_rir(
        scheme=scheme, window=window, settings=settings
    )
    if rir is None:
        return TopSetPlan(False, "not_applied", rir_reason)
    rir = max(1, int(rir) + int(rir_bump))
    if rir > settings.top_set_fallback_above_rir:
        return TopSetPlan(
            False,
            "not_applied",
            f"resolved top-set RIR {rir} after modifiers is above the fallback threshold",
        )
    rir_reason = f"{rir_reason}; final RIR {rir}"
    if item.load_kg is None or item.load_kg <= 0:
        return TopSetPlan(False, "not_applied", "no usable main-lift load")
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
        return TopSetPlan(False, "not_applied", "no usable main-lift e1RM")
    if item.sets < 2:
        return TopSetPlan(False, "not_applied", "one working set cannot form top plus back-off")
    top_load = loads.solve_load(
        float(e1rm_kg), int(item.reps_low), rir, item.rounding_increment_kg
    )
    backoff_sets = item.sets - 1 if settings.top_set_preserve_total_sets else item.sets
    if backoff_sets < 1:
        return TopSetPlan(False, "not_applied", "no set left for back-off work")
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
