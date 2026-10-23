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
                    per_week: int = 3, start_session_type: str | None = None,
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
            session_type=current_type,
            document=document,
            thresholds=thresholds,
            template=session_types[current_type],
            readiness_config=readiness_config,
            undulation=undulation,
            history=history,
            vbt=vbt,
        )
        # Reactive triggers are automatic and are evaluated once against current state.
        # A scheduled deload is only a suggestion in the forecast; it is never applied here.
        reactive = None
        scheduled = None
        if deload_cfg is not None:
            reactive = (
                deload_feature.reactive_decision(
                    conn, date.isoformat(), history=history, config=deload_cfg,
                )
                if index == 0 else None
            )
            scheduled = deload_feature.scheduled_decision(
                conn, date.isoformat(), config=deload_cfg,
            )
        if reactive is not None:
            prescription = deload_mod.apply(prescription, reactive, config=deload_cfg)
        elif scheduled is not None:
            prescription = deload_mod.suggest(prescription, scheduled)
        out.append(ProgrammeEntry(
            date.isoformat(), prescription, current_type,
            reactive.reason if reactive else None,
            deload_suggestion=scheduled.reason if scheduled and reactive is None else None,
            deload_applied=reactive is not None,
        ))
        prior.append(current_type)
        current_type = schedule.next_session_type(
            conn, date.isoformat(), prior_types=prior
        )
    return out
