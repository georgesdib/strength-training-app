"""AFC-4 coaching nudges: at most one review category, suppressed by human action.

A nudge is an AFC-3 observation promoted to Today. It never changes a prescription, never
carries a causal claim, and is never stacked: `current()` returns one nudge or none. Display
and suppression reuse the append-only `maintenance_review` pattern (DEC-AFC-05): a dismissal is
a completed review of that evidence window, and a snooze hides the key for 14 days.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from strength_coach.features import observations
from strength_coach.store import repositories

KEY_PREFIX = "nudge:"
SNOOZE_DAYS = 14
ACTIONS = ("dismiss", "snooze")


def current(conn, *, on_date: str) -> dict[str, Any] | None:
    """The one nudge that may be shown today, or None."""
    payload = observations.analyse(conn, as_of=on_date, persist=True)
    for observation in payload["observations"]:
        key = _key(observation)
        if _suppressed(conn, key, observation, on_date):
            continue
        return _nudge(observation, key)
    return None


def record(
    conn,
    *,
    key: str,
    action: str,
    on_date: str,
    evidence_id: str | None = None,
) -> dict[str, Any]:
    """Append a dismissal or a 14-day snooze for `key`, then return today's nudge."""
    key = str(key).strip()
    _validate_key(key)
    action = str(action).strip().lower()
    if action not in ACTIONS:
        raise ValueError("nudge action must be dismiss or snooze")
    if action == "dismiss":
        if not evidence_id:
            raise ValueError("a dismissal needs the observation's evidence id")
        repositories.append_maintenance_review(
            conn,
            task_key=key,
            action="completed",
            reviewed_on=on_date,
            decision="not_applicable",
            note=str(evidence_id),
        )
    else:
        until = dt.date.fromisoformat(on_date) + dt.timedelta(days=SNOOZE_DAYS)
        repositories.append_maintenance_review(
            conn,
            task_key=key,
            action="snoozed",
            reviewed_on=on_date,
            snoozed_until=until.isoformat(),
        )
    return current(conn, on_date=on_date)


def _nudge(observation: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {
        "key": key,
        "family": observation["family"],
        "statement": observation["statement"],
        "gate": observation["gate"],
        "n": observation["n"],
        "evidence_id": observation["evidence_id"],
        "observation_id": observation["observation_id"],
        "window": observation["window"],
        "evidence": observation["evidence"],
        "category": "review",
        "source": "AFC-3 longitudinal observation",
    }


def _key(observation: Mapping[str, Any]) -> str:
    value = observation.get("value") or {}
    scope = str(value.get("exercise_id") or "session")
    return f"{KEY_PREFIX}{observation['family']}:{scope}"


def _validate_key(key: str) -> None:
    if not key.startswith(KEY_PREFIX):
        raise ValueError("nudge key must start with nudge:")
    parts = key[len(KEY_PREFIX):].split(":")
    if len(parts) != 2 or parts[0] not in observations.FAMILIES or not parts[1]:
        raise ValueError("nudge key must be nudge:<family>:<scope>")


def _suppressed(conn, key: str, observation: Mapping[str, Any], on_date: str) -> bool:
    rows = conn.execute(
        "SELECT action, note, snoozed_until FROM maintenance_review "
        "WHERE task_key = ? ORDER BY reviewed_on DESC, rowid DESC",
        (key,),
    ).fetchall()
    for row in rows:
        if (
            row["action"] == "snoozed"
            and row["snoozed_until"]
            and str(row["snoozed_until"]) >= on_date
        ):
            return True
        if row["action"] == "completed" and str(row["note"] or "") in {
            str(observation["observation_id"]),
            str(observation["evidence_id"]),
        }:
            return True
    return False
