"""Append-only ledger of manual e1RM overrides and their withdrawals.

An override row supplies a manual e1RM; a withdrawal row is a dated tombstone that says "from
this date no override applies". Both are append-only, so the ledger can show what was entered,
what was withdrawn, and which row is currently in force without deleting history.

This module is display/audit state only. It reads the store and never changes a prescription;
the engine's load-base lookup is `store.queries.e1rm_override`.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from strength_coach.store import queries

KIND_OVERRIDE = "override"
KIND_WITHDRAWAL = "withdrawal"


@dataclass(frozen=True)
class LedgerRow:
    kind: str
    record_id: int
    exercise_id: str
    e1rm_kg: float | None
    effective_from: str
    expires_on: str | None
    reason: str | None
    source: str
    created_at: str
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "record_id": self.record_id,
            "exercise_id": self.exercise_id,
            "e1rm_kg": self.e1rm_kg,
            "effective_from": self.effective_from,
            "expires_on": self.expires_on,
            "reason": self.reason,
            "source": self.source,
            "created_at": self.created_at,
            "status": self.status,
        }


def _sort_key(row: dict[str, Any]) -> tuple[str, str, int, int]:
    """Newest effective record first; on an exact tie the explicit withdrawal wins."""
    return (
        str(row["effective_from"]),
        str(row["created_at"]),
        1 if row["kind"] == KIND_WITHDRAWAL else 0,
        int(row["record_id"]),
    )


def _is_winner(row: dict[str, Any], winner: dict[str, Any] | None) -> bool:
    return (
        winner is not None
        and row["kind"] == winner["kind"]
        and row["record_id"] == winner["record_id"]
    )


def _status(
    row: dict[str, Any], winner: dict[str, Any] | None, day: str
) -> str:
    """Status relative to `day`; future/expired rows never compete for the active slot."""
    if row["kind"] == KIND_WITHDRAWAL:
        if str(row["effective_from"]) > day:
            return "future withdrawal"
        return "withdrawn" if _is_winner(row, winner) else "superseded"
    expires_on = row.get("expires_on")
    if expires_on is not None and str(expires_on) < day:
        return "expired"
    if str(row["effective_from"]) > day:
        return "future"
    return "active" if _is_winner(row, winner) else "superseded"


def build(conn, *, on_date: str | None = None) -> list[LedgerRow]:
    """All override and withdrawal rows with a status, grouped by exercise newest first."""
    day = str(on_date or dt.date.today().isoformat())
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in queries.e1rm_overrides(conn):
        groups[str(row["exercise_id"])].append(
            {
                "kind": KIND_OVERRIDE,
                "record_id": int(row["override_id"]),
                "exercise_id": str(row["exercise_id"]),
                "e1rm_kg": float(row["e1rm_kg"]),
                "effective_from": str(row["effective_from"]),
                "expires_on": None if row.get("expires_on") is None else str(row["expires_on"]),
                "reason": row.get("reason"),
                "source": str(row.get("source") or "user"),
                "created_at": str(row["created_at"]),
            }
        )
    for row in queries.e1rm_override_withdrawals(conn):
        groups[str(row["exercise_id"])].append(
            {
                "kind": KIND_WITHDRAWAL,
                "record_id": int(row["withdrawal_id"]),
                "exercise_id": str(row["exercise_id"]),
                "e1rm_kg": None,
                "effective_from": str(row["effective_from"]),
                "expires_on": None,
                "reason": row.get("reason"),
                "source": str(row.get("source") or "user"),
                "created_at": str(row["created_at"]),
            }
        )

    out: list[LedgerRow] = []
    for exercise_id in sorted(groups):
        items = sorted(groups[exercise_id], key=_sort_key, reverse=True)
        applicable = [
            row
            for row in items
            if str(row["effective_from"]) <= day
            and (
                row["kind"] == KIND_WITHDRAWAL
                or row.get("expires_on") is None
                or str(row["expires_on"]) >= day
            )
        ]
        winner = applicable[0] if applicable else None
        for row in items:
            out.append(
                LedgerRow(
                    kind=str(row["kind"]),
                    record_id=int(row["record_id"]),
                    exercise_id=str(row["exercise_id"]),
                    e1rm_kg=row["e1rm_kg"],
                    effective_from=str(row["effective_from"]),
                    expires_on=row["expires_on"],
                    reason=row.get("reason"),
                    source=str(row["source"]),
                    created_at=str(row["created_at"]),
                    status=_status(row, winner, day),
                )
            )
    return out
