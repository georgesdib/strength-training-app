"""Rolling programme forecast, not a committed block.

The athlete has no fixed block. `programme` projects the A/B/C rotation over a horizon, using
the same deterministic engine as `run`; it persists nothing. The day's prescription is rebuilt
when the day arrives, so a forecast row is never edited.

Defaults: three sessions per week (Mon/Wed/Fri). The programme is the existing three-session
full-body rotation; a different frequency would need a scheduling decision, not a silent guess.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from strength_coach.domain.symptoms import flare_from
from strength_coach.features import readiness as readiness_mod
from strength_coach.features import vbt_calibration
from strength_coach.prescribe import build_prescription, fallback
from strength_coach.prescribe import config as thresholds_mod
from strength_coach.prescribe import templates, undulation as undulation_mod
from strength_coach.rules import History, RuleContext, evaluate, load_document
from strength_coach.store import queries

WEEKDAYS = (0, 2, 4)          # Monday, Wednesday, Friday
DAYS = ("A", "B", "C")


@dataclass(frozen=True)
class ProgrammeEntry:
    on_date: str
    day: str
    prescription: object
    deload_reason: str | None = None


def _next_day(conn, before: str, start_day: str | None) -> str:
    if start_day:
        return start_day.upper()
    sessions = queries.sessions(conn, end=before)
    if not sessions.empty:
        last = str(sessions.iloc[-1]["day_guess"])
        if last in DAYS:
            return DAYS[(DAYS.index(last) + 1) % len(DAYS)]
    return "A"


def _dates(start: dt.date, weeks: int, per_week: int) -> list[dt.date]:
    """Exactly weeks*per_week session dates from start, on the selected weekdays."""
    selected = WEEKDAYS[:per_week]
    out: list[dt.date] = []
    cursor = start
    while len(out) < weeks * per_week:
        if cursor.weekday() in selected:
            out.append(cursor)
        cursor += dt.timedelta(days=1)
    return out


def reactive_deload_reason(conn, as_of: str, *,
                           history: History | None = None) -> str | None:
    """The two configured triggers: two consecutive weeks over the cap, or two flares.

    `history` is passed by `build_programme` so the enriched frame is not rebuilt just to
    look at the last two sessions.
    """
    try:
        document = load_document()
        context = RuleContext.from_store(conn, end=as_of, history=history)
        verdict = evaluate(document, context).verdict("PRG-SPINE-001")
        costs = verdict.details.get("weighted_costs", {}) if verdict.details else {}
        cap = float(verdict.details.get("cap", 3)) if verdict.details else 3.0
        weeks = sorted(costs)
        if len(weeks) >= 2:
            last_two = weeks[-2:]
            consecutive = (
                dt.date.fromisocalendar(int(last_two[1][:4]), int(last_two[1][6:]), 1)
                - dt.date.fromisocalendar(int(last_two[0][:4]), int(last_two[0][6:]), 1)
            ).days == 7
            if consecutive and all(float(costs[w]) > cap for w in last_two):
                return (
                    f"two consecutive weeks over the spinal cap "
                    f"({last_two[0]}={costs[last_two[0]]:g}, {last_two[1]}={costs[last_two[1]]:g}; "
                    f"cap {cap:g})"
                )
    except Exception:
        # A forecast must not fail because an optional safety input is unavailable.
        pass

    sessions = queries.sessions(conn, end=as_of)
    if len(sessions) >= 2:
        # Only the flare flag is needed, so read the symptom directly instead of building a
        # full rule context per session (that was most of the foreground cost).
        flares = []
        for occurred_on in sessions.tail(2)["occurred_on"]:
            entry = queries.latest_symptom(conn, str(occurred_on))
            flares.append(
                entry is not None
                and flare_from(int(entry["level"]), entry["settled_within_48h"]) is True
            )
        if all(flares):
            return "two consecutive flaring sessions"
    return None


def build_programme(conn, *, start: str | None = None, weeks: int = 4,
                    per_week: int = 3, start_day: str | None = None,
                    apply_deload: bool = True) -> list[ProgrammeEntry]:
    if weeks <= 0:
        raise ValueError("weeks must be positive")
    if not 1 <= per_week <= len(WEEKDAYS):
        raise ValueError("per_week must be 1-3 for the A/B/C programme")
    first = dt.date.fromisoformat(start) if start else dt.date.today()
    day = _next_day(conn, first.isoformat(), start_day)
    dates = _dates(first, weeks, per_week)
    # The past does not change across a forward horizon, so load it once. Rebuilding the
    # enriched history and the VBT calibration for every projected session made a four-week
    # forecast take over two minutes; the date-dependent inputs are still derived per date.
    history = History.load(conn, end=dates[-1].isoformat())
    reason = (
        reactive_deload_reason(conn, first.isoformat(), history=history)
        if apply_deload else None
    )
    document = load_document()
    thresholds = thresholds_mod.Thresholds.load()
    templates_by_day = {name: templates.DayTemplate.load(name) for name in DAYS}
    readiness_config = readiness_mod.ReadinessConfig.load()
    undulation = undulation_mod.Undulation.load()
    # No history means no calibration to reuse; `calibrate` expects enriched columns that an
    # empty frame does not have, and the engine already reports VBT as unavailable.
    vbt = vbt_calibration.calibrate(history.sets) if not history.sets.empty else None
    out: list[ProgrammeEntry] = []
    for index, date in enumerate(dates):
        prescription = build_prescription(
            conn,
            for_date=date.isoformat(),
            session_day=day,
            document=document,
            thresholds=thresholds,
            template=templates_by_day[day],
            readiness_config=readiness_config,
            undulation=undulation,
            history=history,
            vbt=vbt,
        )
        trigger = reason if reason and index == 0 else None
        if trigger and prescription.fallback_level == "full":
            prescription = fallback.reduced_prescription(
                prescription, factor=0.90, reason=f"reactive deload: {reason}"
            )
        out.append(ProgrammeEntry(date.isoformat(), day, prescription, trigger))
        day = DAYS[(DAYS.index(day) + 1) % len(DAYS)]
    return out
