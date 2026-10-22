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
from dataclasses import dataclass

from strength_coach.features import deload as deload_feature
from strength_coach.features import readiness as readiness_mod
from strength_coach.features import vbt_calibration
from strength_coach.prescribe import build_prescription, deload as deload_mod, schedule
from strength_coach.prescribe import config as thresholds_mod
from strength_coach.prescribe import templates, undulation as undulation_mod
from strength_coach.rules import History, load_document
from strength_coach.store import queries

WEEKDAYS = (0, 2, 4)          # Monday, Wednesday, Friday
DAYS = ("A", "B", "C")


@dataclass(frozen=True)
class ProgrammeEntry:
    on_date: str
    day: str
    prescription: object
    deload_reason: str | None = None
    session_type: str | None = None


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
    """Deprecated compatibility wrapper; policy now lives in `features.deload`."""
    return deload_feature.reactive_reason(conn, as_of, history=history)


def build_programme(conn, *, start: str | None = None, weeks: int = 4,
                    per_week: int = 3, start_day: str | None = None,
                    start_session_type: str | None = None,
                    apply_deload: bool = True) -> list[ProgrammeEntry]:
    if weeks <= 0:
        raise ValueError("weeks must be positive")
    if not 1 <= per_week <= len(WEEKDAYS):
        raise ValueError("per_week must be 1-3 for the A/B/C programme")
    first = dt.date.fromisoformat(start) if start else dt.date.today()
    dates = _dates(first, weeks, per_week)
    prior: list[str] = []
    if start_session_type and start_session_type != "auto":
        if start_session_type not in templates.SESSION_TYPES:
            raise ValueError(
                f"start_session_type must be one of {templates.SESSION_TYPES} or auto"
            )
        start_type = start_session_type
    elif start_day:
        # Deprecated A/B/C compatibility; C maps to bench+squat because the legacy label had
        # no bench+hinge distinction.
        legacy = {"A": "squat", "B": "hinge", "C": "bench_squat"}
        if start_day.upper() not in legacy:
            raise ValueError("start_day must be A, B or C")
        start_type = legacy[start_day.upper()]
    else:
        start_type = schedule.next_session_type(conn, first.isoformat())
    # The past does not change across a forward horizon, so load it once. Rebuilding the
    # enriched history and the VBT calibration for every projected session made a four-week
    # forecast take over two minutes; the date-dependent inputs are still derived per date.
    history = History.load(conn, end=dates[-1].isoformat())
    deload_cfg = deload_feature.DeloadConfig.load() if apply_deload else None
    document = load_document()
    thresholds = thresholds_mod.Thresholds.load()
    session_types = {name: templates.SessionTemplate.load(name)
                     for name in templates.SESSION_TYPES}
    readiness_config = readiness_mod.ReadinessConfig.load()
    undulation = undulation_mod.Undulation.load()
    # No history means no calibration to reuse; `calibrate` expects enriched columns that an
    # empty frame does not have, and the engine already reports VBT as unavailable.
    vbt = vbt_calibration.calibrate(history.sets) if not history.sets.empty else None
    out: list[ProgrammeEntry] = []
    current_type = start_type
    for index, date in enumerate(dates):
        prescription = build_prescription(
            conn,
            for_date=date.isoformat(),
            session_day=schedule.legacy_day(current_type),
            session_type=current_type,
            document=document,
            thresholds=thresholds,
            template=session_types[current_type],
            readiness_config=readiness_config,
            undulation=undulation,
            history=history,
            vbt=vbt,
        )
        # Scheduled deloads apply on every projected date in the deload week; reactive
        # triggers are evaluated once against the current state and apply to the first entry.
        decision = (
            deload_feature.decision(
                conn, date.isoformat(), history=history,
                include_reactive=(index == 0), config=deload_cfg,
            )
            if deload_cfg is not None else None
        )
        if decision is not None:
            prescription = deload_mod.apply(prescription, decision, config=deload_cfg)
        out.append(ProgrammeEntry(
            date.isoformat(), prescription.session_day, prescription,
            decision.reason if decision else None, current_type
        ))
        prior.append(current_type)
        current_type = schedule.next_session_type(
            conn, date.isoformat(), prior_types=prior
        )
    return out
