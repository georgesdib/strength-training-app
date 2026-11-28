"""AFC-4 coaching nudges: at most one review category, suppressed by human action.

A nudge is an AFC-3 observation promoted to Today. It never changes a prescription, never
carries a causal claim, and is never stacked: `current()` returns one nudge or none. Display
and suppression reuse the append-only `maintenance_review` pattern (DEC-AFC-05): a dismissal is
a completed review of that evidence window, and a snooze hides the key for 14 days.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from typing import Any

from strength_coach.features import observations, programme
from strength_coach.store import repositories

KEY_PREFIX = "nudge:"
SNOOZE_DAYS = 14
ACTIONS = ("dismiss", "snooze")
# AFC-4 observation families plus the programme-context source (DEC-RESOLVER-26).
NUDGE_FAMILIES = (*observations.FAMILIES, "programme")


def current(conn, *, on_date: str) -> dict[str, Any] | None:
    """The one nudge that may be shown today, or None.

    A time-sensitive programme fact (a scheduled deload, an active competition window) is
    promoted before an AFC-3 observation; a suppressed programme nudge falls through to the
    observation list (DEC-RESOLVER-26).
    """
    programme_nudge = _programme_nudge(conn, on_date=on_date)
    if programme_nudge is not None and not _suppressed(
        conn, programme_nudge["key"], programme_nudge, on_date
    ):
        return programme_nudge
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


def _programme_nudge(conn, *, on_date: str) -> dict[str, Any] | None:
    """A scheduled deload or an active competition window, or None.

    This is context, not a new training decision: the deload policy and the competition window
    already own the verdict. The nudge only asks the athlete to review it.
    """
    header = programme.header(conn, on_date)
    deload = header.get("deload") or {}
    if deload.get("status") == "suggested":
        week = deload.get("calendar_week")
        event_id = deload.get("event_id")
        evidence_id = (
            f"programme:deload:{event_id}"
            if event_id else
            f"programme:deload:{week if week is not None else 'unknown'}"
        )
        statement = (
            f"A scheduled deload is due (block week {week}). Review whether to take it."
            if week is not None
            else "A scheduled deload is due. Review whether to take it."
        )
        return _programme_payload(
            key="nudge:programme:deload",
            statement=statement,
            evidence_id=evidence_id,
            on_date=on_date,
            value={
                "calendar_week": week,
                "trigger": deload.get("trigger"),
                "reason": deload.get("reason"),
                "event_id": event_id,
            },
            limitations=("A policy suggestion, not a measured requirement.",),
        )
    competition = header.get("competition") or {}
    if competition.get("window") in ("peak", "taper"):
        date = str(competition.get("date") or "")
        days = competition.get("days_until")
        window = str(competition.get("window"))
        evidence_id = f"programme:competition:{date}:{window}"
        when = f"in {days} days" if days is not None else "today"
        statement = (
            f"Competition on {date} is {when}; the {window} window is active."
        )
        return _programme_payload(
            key="nudge:programme:competition",
            statement=statement,
            evidence_id=evidence_id,
            on_date=on_date,
            value={"date": date, "days_until": days, "window": window},
            limitations=("Context for the existing competition policy; it changes no plan.",),
        )
    return None


def _programme_payload(
    *,
    key: str,
    statement: str,
    evidence_id: str,
    on_date: str,
    value: Mapping[str, Any],
    limitations: tuple[str, ...],
) -> dict[str, Any]:
    observation_id = "ob:programme:" + hashlib.sha256(
        f"{key}|{evidence_id}".encode()
    ).hexdigest()[:24]
    evidence = {
        "evidence_id": evidence_id,
        "source": "programme_header",
        "source_ids": [],
        "window": {"start": on_date, "end": on_date},
        "value": dict(value),
        "method": "strength_coach.features.programme.header",
        "gate": "signal",
        "n": 1,
        "limitations": list(limitations),
    }
    return {
        "key": key,
        "family": "programme",
        "statement": statement,
        "gate": "signal",
        "n": 1,
        "evidence_id": evidence_id,
        "observation_id": observation_id,
        "window": {"start": on_date, "end": on_date},
        "evidence": evidence,
        "category": "review",
        "source": "programme context",
    }


def _key(observation: Mapping[str, Any]) -> str:
    value = observation.get("value") or {}
    scope = str(value.get("exercise_id") or "session")
    return f"{KEY_PREFIX}{observation['family']}:{scope}"


def _validate_key(key: str) -> None:
    if not key.startswith(KEY_PREFIX):
        raise ValueError("nudge key must start with nudge:")
    parts = key[len(KEY_PREFIX):].split(":")
    if len(parts) != 2 or parts[0] not in NUDGE_FAMILIES or not parts[1]:
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
