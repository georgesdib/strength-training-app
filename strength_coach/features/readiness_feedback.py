"""Readiness-reduction feedback: descriptive follow-up, never a tuning signal.

Reads `prescription_modifier` rows for MOD-FAT-001 and compares the next observed session with
the athlete's own previous session. This is association-only: reductions were not randomised,
the athlete may have ignored them, and the sample is small.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
from typing import Any

from strength_coach.domain import e1rm as e1rm_mod
from strength_coach.domain.symptoms import flare_from
from strength_coach.store import queries

FOLLOW_UP_DAYS = 14
WINDOW_DAYS = 7


def _window(on_date: str | None, weeks: int) -> tuple[dt.date, dt.date]:
    end = dt.date.fromisoformat(on_date) if on_date else dt.date.today()
    return end - dt.timedelta(days=7 * weeks - 1), end


def _sessions(conn, start: dt.date, end: dt.date):
    return queries.sessions(conn, start=start.isoformat(), end=end.isoformat())


def _feedback_map(conn) -> dict[str, dict]:
    return {str(row["session_id"]): row for row in queries.session_feedback_all(conn)}


def _session_metrics(conn, session_id: str, feedback: dict[str, dict]) -> dict:
    row = feedback.get(str(session_id)) or {}
    sets = conn.execute(
        "SELECT rir FROM clean_set WHERE session_id = ? AND is_working_set = 1",
        (str(session_id),),
    ).fetchall()
    rirs = [float(r["rir"]) for r in sets if r["rir"] is not None]
    return {
        "srpe": None if row.get("srpe") is None else float(row["srpe"]),
        "duration_min": None if row.get("duration_min") is None else float(row["duration_min"]),
        "rir_adherence": (
            round(sum(1 for value in rirs if 1 <= value <= 4) / len(rirs), 3)
            if rirs else None
        ),
    }


def _e1rm_at(conn, exercise_id: str, on_or_before: str | None = None,
             after: str | None = None, until: str | None = None) -> float | None:
    sql = "SELECT load_kg, reps, rir FROM clean_set WHERE exercise_id = ? AND is_working_set = 1"
    params: list[Any] = [str(exercise_id)]
    if on_or_before is not None:
        sql += " AND occurred_on <= ?"
        params.append(str(on_or_before))
    if after is not None:
        sql += " AND occurred_on >= ?"
        params.append(str(after))
    if until is not None:
        sql += " AND occurred_on <= ?"
        params.append(str(until))
    sql += " ORDER BY occurred_on, set_id"
    values = []
    for row in conn.execute(sql, params).fetchall():
        estimate = e1rm_mod.estimate_e1rm(
            row["load_kg"], row["reps"], row["rir"] if row["rir"] is not None else None
        )
        if estimate is not None and estimate.is_usable:
            values.append(float(estimate.value_kg))
    return values[-1] if values else None


def _next_session(conn, applied_on: str, until: str):
    row = conn.execute(
        "SELECT session_id, occurred_on FROM session "
        "WHERE occurred_on > ? AND occurred_on <= ? ORDER BY occurred_on LIMIT 1",
        (applied_on, until),
    ).fetchone()
    return dict(row) if row else None


def _previous_session(conn, applied_on: str):
    row = conn.execute(
        "SELECT session_id, occurred_on FROM session "
        "WHERE occurred_on < ? ORDER BY occurred_on DESC LIMIT 1",
        (applied_on,),
    ).fetchone()
    return dict(row) if row else None


def _symptom_flare(conn, start: str, end: str) -> bool | None:
    rows = queries.symptom_entries(conn, since=start)
    rows = [row for row in rows if start <= str(row["logged_on"]) <= end]
    if not rows:
        return None
    return any(
        flare_from(int(row["level"]), row.get("settled_within_48h")) is True
        for row in rows
    )


def _event(conn, row, feedback) -> dict:
    detail = json.loads(row["detail_json"] or "{}")
    applied_on = str(row["applied_on"])
    until = (dt.date.fromisoformat(applied_on) + dt.timedelta(days=FOLLOW_UP_DAYS)).isoformat()
    next_session = _next_session(conn, applied_on, until)
    previous = _previous_session(conn, applied_on)
    item_ids = [str(v) for v in (detail.get("items") or [])]
    before_e1rm = _e1rm_at(conn, item_ids[0], on_or_before=applied_on) if item_ids else None
    after_e1rm = (
        _e1rm_at(conn, item_ids[0], after=next_session["occurred_on"],
                 until=next_session["occurred_on"])
        if item_ids and next_session else None
    )
    change = (
        round(100 * (after_e1rm - before_e1rm) / before_e1rm, 1)
        if before_e1rm and after_e1rm else None
    )
    return {
        "modifier_id": row["modifier_id"],
        "prescription_id": row["prescription_id"],
        "applied_on": applied_on,
        "item_ids": item_ids,
        "next_session_on": next_session["occurred_on"] if next_session else None,
        "completed_within_7d": (
            None if not next_session else
            (dt.date.fromisoformat(next_session["occurred_on"])
             - dt.date.fromisoformat(applied_on)).days <= WINDOW_DAYS
        ),
        "previous": _session_metrics(conn, previous["session_id"], feedback) if previous else {},
        "next": _session_metrics(conn, next_session["session_id"], feedback) if next_session else {},
        "e1rm_before": round(before_e1rm, 1) if before_e1rm else None,
        "e1rm_after": round(after_e1rm, 1) if after_e1rm else None,
        "e1rm_change_pct": change,
        "symptom_flare_7d": (
            _symptom_flare(
                conn, applied_on,
                (dt.date.fromisoformat(applied_on)
                 + dt.timedelta(days=WINDOW_DAYS)).isoformat(),
            ) if next_session else None
        ),
    }


def report(conn, *, weeks: int = 12, on_date: str | None = None) -> dict:
    if weeks <= 0 or weeks > 52:
        raise ValueError("weeks must be between 1 and 52")
    start, end = _window(on_date, weeks)
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prescription_modifier'"
    ).fetchone()
    if exists is None:
        return {"window": {"weeks": weeks, "from": start.isoformat(),
                           "to": end.isoformat()}, "events": [], "aggregate": {},
                "warnings": ["modifier provenance table absent"]}
    rows = conn.execute(
        "SELECT modifier_id, prescription_id, applied_on, detail_json "
        "FROM prescription_modifier WHERE modifier_key = 'MOD-FAT-001' "
        "AND applied_on BETWEEN ? AND ? ORDER BY applied_on",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    feedback = _feedback_map(conn)
    events = [_event(conn, row, feedback) for row in rows]

    completed = [e for e in events if e["completed_within_7d"] is not None]
    srpe = [e["next"]["srpe"] for e in events
            if e["next"].get("srpe") is not None]
    rir = [e["next"]["rir_adherence"] for e in events
           if e["next"].get("rir_adherence") is not None]
    changes = [e["e1rm_change_pct"] for e in events
               if e["e1rm_change_pct"] is not None]
    flares = [e for e in events if e["symptom_flare_7d"] is True]
    aggregate = {
        "n_events": len(events),
        "n_with_next_session": sum(1 for e in events if e["next_session_on"]),
        "completion_within_7d": (
            round(sum(1 for e in completed if e["completed_within_7d"]) / len(completed), 3)
            if completed else None
        ),
        "mean_srpe": round(statistics.mean(srpe), 2) if srpe else None,
        "mean_rir_adherence": round(statistics.mean(rir), 3) if rir else None,
        "mean_e1rm_change_pct": round(statistics.mean(changes), 1) if changes else None,
        "n_symptom_flares": len(flares) if any(
            e["symptom_flare_7d"] is not None for e in events
        ) else None,
    }
    warnings = [
        "Observational and confounded: reductions were not randomised and may have been ignored.",
        "Small sample; no causal or validated effect is claimed.",
        "Web prescriptions are not persisted, so only CLI-stored modifiers appear.",
    ]
    if len(events) < 8:
        warnings.append("Fewer than 8 events: descriptive only, not an estimate.")
    return {
        "window": {"weeks": weeks, "from": start.isoformat(), "to": end.isoformat()},
        "events": events,
        "aggregate": aggregate,
        "warnings": warnings,
        "note": "Association only. No readiness weight, threshold or prescription change.",
    }
