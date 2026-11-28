"""Rolling programme forecast, not a committed block.

The athlete has no fixed block. `programme` projects the rolling session-type sequence over a
horizon, using the same deterministic engine as `run`; it persists nothing. The day's
prescription is rebuilt when the day arrives, so a forecast row is never edited. Scheduled and
reactive deloads are applied per projected date.

Defaults: three sessions per week (Mon/Wed/Fri). The programme is the existing three-session
full-body rotation; a different frequency would need a scheduling decision, not a silent guess.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from strength_coach import settings_profile
from strength_coach.features import deload as deload_feature
from strength_coach.features import vbt_calibration
from strength_coach.prescribe import build_prescription, schedule, templates
from strength_coach.prescribe import deload as deload_mod
from strength_coach.prescribe import volume_budget as volume_budget_mod
from strength_coach.rules import History, load_document

WEEKDAYS_BY_FREQUENCY = {
    1: (0,),                   # Mon
    2: (0, 3),                # Mon, Thu
    3: (0, 2, 4),             # Mon, Wed, Fri
    4: (0, 2, 4, 6),          # Mon, Wed, Fri, Sun
    5: (0, 1, 3, 4, 6),       # Mon, Tue, Thu, Fri, Sun; rest Wed/Sat
}


@dataclass(frozen=True)
class ProgrammeEntry:
    on_date: str
    prescription: object
    session_type: str
    deload_reason: str | None = None
    deload_suggestion: str | None = None
    deload_applied: bool = False


def _dates(start: dt.date, weeks: int, per_week: int) -> list[dt.date]:
    """Exactly weeks*per_week session dates from start, on the selected weekdays."""
    selected = WEEKDAYS_BY_FREQUENCY[per_week]
    out: list[dt.date] = []
    cursor = start
    while len(out) < weeks * per_week:
        if cursor.weekday() in selected:
            out.append(cursor)
        cursor += dt.timedelta(days=1)
    return out


def reactive_deload_reason(conn, as_of: str, *,
                           history: History | None = None) -> str | None:
    """Deprecated compatibility wrapper; policy now lives in `features.deload`."""
    return deload_feature.reactive_reason(conn, as_of, history=history)


def build_programme(conn, *, start: str | None = None, weeks: int = 4,
                    per_week: int = 3, start_session_type: str | None = None,
                    apply_deload: bool = True, apply_selection: bool = False,
                    selection_confirmed: bool = False) -> list[ProgrammeEntry]:
    # The UI and API bound the horizon; the core enforces the same limit so a direct call
    # cannot start an unbounded forecast (DEC-PROGRAMME-09).
    if not 1 <= weeks <= 26:
        raise ValueError("weeks must be between 1 and 26")
    if per_week not in WEEKDAYS_BY_FREQUENCY:
        raise ValueError("per_week must be 1-5 for the programme forecast")
    first = dt.date.fromisoformat(start) if start else dt.date.today()
    dates = _dates(first, weeks, per_week)
    prior: list[str] = []
    if start_session_type and start_session_type != "auto":
        if start_session_type not in templates.SESSION_TYPES:
            raise ValueError(
                f"start_session_type must be one of {templates.SESSION_TYPES} or auto"
            )
        start_type = start_session_type
    else:
        start_type = schedule.next_session_type(conn, first.isoformat())
    # The past does not change across a forward horizon, so load it once. Rebuilding the
    # enriched history and the VBT calibration for every projected session made a four-week
    # forecast take over two minutes; the date-dependent inputs are still derived per date.
    history = History.load(conn, end=dates[-1].isoformat())
    document = load_document()
    session_types = {name: templates.SessionTemplate.load(name)
                     for name in templates.SESSION_TYPES}
    # No history means no calibration to reuse; `calibrate` expects enriched columns that an
    # empty frame does not have, and the engine already reports VBT as unavailable.
    vbt = vbt_calibration.calibrate(history.sets) if not history.sets.empty else None
    out: list[ProgrammeEntry] = []
    current_type = start_type
    projected_items: dict[str, list[dict]] = {}
    projected_dates: dict[str, set[str]] = {}
    for index, date in enumerate(dates):
        week_start, _week_end = volume_budget_mod.week_bounds(date.isoformat())
        prior_items = projected_items.get(week_start, [])
        prior_sessions = len(projected_dates.get(week_start, set()))
        # Resolve per date: a profile version effective mid-forecast changes later entries.
        resolved = settings_profile.feature_settings(conn, date.isoformat())
        # Reactive triggers are automatic and are evaluated once against current state.
        # A scheduled deload is only a suggestion in the forecast; it is never applied here.
        reactive = None
        scheduled = None
        if apply_deload:
            reactive = (
                deload_feature.reactive_decision(
                    conn, date.isoformat(), history=history, config=resolved.deload,
                )
                if index == 0 else None
            )
            scheduled = deload_feature.scheduled_decision(
                conn, date.isoformat(), config=resolved.deload,
            )
        prescription = build_prescription(
            conn,
            for_date=date.isoformat(),
            session_type=current_type,
            document=document,
            thresholds=resolved.thresholds,
            template=session_types[current_type],
            readiness_config=resolved.readiness,
            undulation=resolved.undulation,
            history=history,
            vbt=vbt,
            apply_selection=apply_selection,
            selection_confirmed=selection_confirmed,
            deload_decision=reactive,
            use_resolver=False,
            projected_items=tuple(prior_items),
            projected_sessions=prior_sessions,
        )
        # A deferral is not presentable here: this forecast is not a prescription request, so
        # it has no issuance to spend on it. Issuance asks again (deferral_reconsiderable).
        suggests_deload = (
            reactive is None
            and scheduled is not None
            and scheduled.owner_decision is None
        )
        if suggests_deload:
            prescription = deload_mod.suggest(prescription, scheduled)
        out.append(ProgrammeEntry(
            date.isoformat(), prescription, prescription.session_type,
            reactive.reason if reactive else None,
            deload_suggestion=scheduled.reason if suggests_deload else None,
            deload_applied=reactive is not None,
        ))
        for item in prescription.items:
            projected_items.setdefault(week_start, []).append({
                "exercise_id": item.exercise_id,
                "sets": int(item.sets),
                "date": date.isoformat(),
            })
        projected_dates.setdefault(week_start, set()).add(date.isoformat())
        prior.append(prescription.session_type)
        current_type = schedule.next_session_type(
            conn, date.isoformat(), prior_types=prior
        )
    return out

def header(
    conn, on_date: str, *, live_plan: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Read-only programme context for Today and intelligence (WP4).

    Uses the profile anchor, the trained-week query, effective settings and the deload
    decisions only: no full history or rule-context load, and it is never an evaluator input.
    """
    from strength_coach.prescribe import top_set as top_set_mod
    from strength_coach.prescribe.resolver_settings import ResolverSettings
    from strength_coach.rules.context import trained_week_index
    from strength_coach.store import queries

    profile = queries.athlete_profile(conn) or {}
    anchor_raw = profile.get("block_start_date")
    resolved = settings_profile.feature_settings(conn, on_date)

    anchor: dt.date | None = None
    if anchor_raw:
        try:
            anchor = dt.date.fromisoformat(str(anchor_raw)[:10])
        except ValueError:
            anchor = None

    trained_week = (
        trained_week_index(conn, str(anchor_raw), on_date) if anchor else None
    )
    out: dict[str, Any] = {"trained_week": trained_week}

    undulation = resolved.undulation
    if (
        anchor is not None
        and trained_week is not None
        and trained_week >= 1
        and undulation.enabled
        and undulation.cycle_weeks > 0
    ):
        schemes = undulation.for_week(trained_week)
        if schemes:
            out["dup"] = {
                "enabled": True,
                "cycle_weeks": int(undulation.cycle_weeks),
                "cycle_week": ((trained_week - 1) % undulation.cycle_weeks) + 1,
                "main_scheme": schemes.get("main"),
                "accessory_scheme": schemes.get("accessory"),
            }

    reactive = deload_feature.reactive_decision(
        conn, on_date, config=resolved.deload
    )
    scheduled = deload_feature.scheduled_decision(
        conn, on_date, config=resolved.deload, include_deferred=True
    )
    live_notes = (live_plan or {}).get("notes") or {}
    live_deload = live_notes.get("deload") if isinstance(live_notes, Mapping) else None
    if reactive is not None:
        status: str | None = "active"
        trigger = reactive.trigger
        reason = reactive.reason
    elif isinstance(live_deload, Mapping) and live_deload:
        status = "active"
        trigger = live_deload.get("trigger")
        reason = live_deload.get("reason")
    elif scheduled is not None and scheduled.owner_decision == "accepted":
        status = "active"
        trigger = scheduled.trigger
        reason = scheduled.reason
    elif scheduled is not None:
        # One rule with issuance and the nudge: a deferral is not an actionable suggestion while
        # it is in force; the next prescription issuance presents it again.
        suggested = scheduled.owner_decision is None
        status = "suggested" if suggested else "none"
        trigger = scheduled.trigger if suggested else None
        reason = scheduled.reason if suggested else None
    else:
        status = "none"
        trigger = None
        reason = None

    calendar_week = None
    if anchor is not None:
        try:
            current = dt.date.fromisoformat(str(on_date)[:10])
        except ValueError:
            current = None
        if current is not None and current >= anchor:
            calendar_week = (current - anchor).days // 7 + 1
    out["deload"] = {
        "calendar_week": calendar_week,
        "status": status,
        "trigger": trigger,
        "reason": reason,
        "event_id": scheduled.event_id if scheduled is not None else None,
        "decision": (
            scheduled.owner_decision if scheduled is not None else None
        ),
    }

    competition_raw = profile.get("competition_date")
    if competition_raw:
        try:
            competition = dt.date.fromisoformat(str(competition_raw)[:10])
            current = dt.date.fromisoformat(str(on_date)[:10])
        except ValueError:
            competition = None
            current = None
        if competition is not None and current is not None:
            days = (competition - current).days
            window = top_set_mod.competition_window(
                competition.isoformat(), on_date, ResolverSettings.load(conn, on_date)
            )
            out["competition"] = {
                "date": competition.isoformat(),
                "days_until": days if days >= 0 else None,
                "window": window,
            }
    return out

