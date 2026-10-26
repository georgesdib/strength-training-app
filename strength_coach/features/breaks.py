"""Declared breaks: holiday, deload and test weeks.

A break exists for one job: a week that was trained but must **not** advance the DUP cycle or
the erector ramp (ROADMAP 4.6, `DEC-CONTINUITY-04`). Untrained weeks are already skipped by the
trained-week count, so declaring a holiday changes the record and the display rather than the
maths; declaring a test or deload week with training in it is what actually freezes the cycle.

Two design choices are recorded as assumptions:
* any ISO week containing a break day is frozen, so a one-day break freezes its whole week;
* cancelling is a new row that names the row it cancels. Nothing is edited or deleted.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from strength_coach.store import queries, repositories

REASONS = ("holiday", "deload", "test", "other")


@dataclass(frozen=True)
class DeclaredBreak:
    break_id: int
    starts_on: str
    ends_on: str
    reason: str
    note: str | None
    cancelled: bool = False
    cancels_break_id: int | None = None

    def covers(self, on_date: str) -> bool:
        return self.starts_on <= str(on_date)[:10] <= self.ends_on

    @property
    def days(self) -> int:
        first = dt.date.fromisoformat(self.starts_on)
        last = dt.date.fromisoformat(self.ends_on)
        return (last - first).days + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "break_id": self.break_id,
            "starts_on": self.starts_on,
            "ends_on": self.ends_on,
            "reason": self.reason,
            "note": self.note,
            "cancelled": self.cancelled,
            "days": self.days,
        }


def _date(value: str, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


def record(
    conn,
    *,
    starts_on: str,
    ends_on: str,
    reason: str,
    note: str | None = None,
) -> int:
    """Append a break. Validates the date order and the reason, and stores nothing else."""
    first = _date(starts_on, "starts_on")
    last = _date(ends_on, "ends_on")
    if last < first:
        raise ValueError("ends_on must be on or after starts_on")
    if reason not in REASONS:
        raise ValueError(f"reason must be one of {', '.join(REASONS)}")
    return repositories.append_declared_break(
        conn, starts_on=first.isoformat(), ends_on=last.isoformat(),
        reason=reason, note=note,
    )


def cancel(conn, break_id: int, *, note: str | None = None) -> int:
    """Cancel a break by appending a row that names it; the original row stays visible."""
    target = next(
        (item for item in all_breaks(conn) if item.break_id == int(break_id)), None
    )
    if target is None:
        raise ValueError(f"no declared break with id {break_id}")
    if target.cancelled:
        raise ValueError(f"declared break {break_id} is already cancelled")
    return repositories.append_declared_break(
        conn,
        starts_on=target.starts_on,
        ends_on=target.ends_on,
        reason=target.reason,
        note=note or f"cancels {target.break_id}",
        cancels_break_id=target.break_id,
    )


def all_breaks(conn) -> list[DeclaredBreak]:
    """Every break, newest record included, with the cancelled flag resolved.

    Rows that exist only to cancel another row are audit records, not breaks, so they are not
    listed as intervals of their own.
    """
    rows = queries.declared_breaks(conn)
    cancelled_ids = {
        int(row["cancels_break_id"]) for row in rows if row["cancels_break_id"]
    }
    out: list[DeclaredBreak] = []
    for row in rows:
        if row["cancels_break_id"]:
            continue
        out.append(DeclaredBreak(
            break_id=int(row["break_id"]),
            starts_on=str(row["starts_on"])[:10],
            ends_on=str(row["ends_on"])[:10],
            reason=str(row["reason"]),
            note=row["note"],
            cancelled=int(row["break_id"]) in cancelled_ids,
            cancels_break_id=None,
        ))
    return out


def active_on(conn, on_date: str) -> list[DeclaredBreak]:
    return [
        item for item in all_breaks(conn)
        if not item.cancelled and item.covers(on_date)
    ]


def break_weeks(conn, start: str, end: str) -> set[tuple[int, int]]:
    """ISO (year, week) keys of every week that contains a break day inside [start, end]."""
    first = _date(start, "start")
    last = _date(end, "end")
    weeks: set[tuple[int, int]] = set()
    for item in all_breaks(conn):
        if item.cancelled:
            continue
        day = max(_date(item.starts_on, "starts_on"), first)
        stop = min(_date(item.ends_on, "ends_on"), last)
        while day <= stop:
            iso = day.isocalendar()
            weeks.add((iso[0], iso[1]))
            day += dt.timedelta(days=1)
    return weeks


def as_dict(items: list[DeclaredBreak]) -> list[dict[str, Any]]:
    return [item.as_dict() for item in items]
