"""The one approved MCP resource: a compact, non-sensitive athlete profile.

The canonical contract describes goal and priority fields. Those columns were retired from the
product (DEC-STATE-02) and are no longer written, so this resource returns what actually exists:
the current training profile and the non-injury structured constraints. Injury constraints,
symptoms, measurements and free text are excluded by policy; their count is reported so the
reader knows something was withheld rather than absent.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import Envelope, FactBlock, Period, Privacy
from strength_coach.intelligence.service import (
    Clock,
    execution_context,
    read_snapshot,
)
from strength_coach.store import queries

RESOURCE_NAME = "athlete_profile"
RESOURCE_VERSION = "1.0.0"
RESOURCE_URI = "strength://athlete/profile"

PROFILE_KEYS = (
    "effective_from",
    "sessions_per_week_target",
    "max_session_minutes",
    "block_start_date",
    "volume_budget_enabled",
    "main_lift_policy",
)

CONSTRAINT_KEYS = ("kind", "region", "severity", "forbidden_patterns", "forbidden_exercises")

MODULES = (
    "strength_coach.store.queries.athlete_profile",
    "strength_coach.store.queries.athlete_constraints",
)

UNITS = {"load": "kg", "velocity": "m/s", "duration": "min"}

LIMITATIONS = (
    "Goal, goal rank and focus-lift fields are retired (DEC-STATE-02) and are not returned.",
    "Injury constraints are excluded from this resource; only their count is reported.",
    "Units are fixed by the platform: load kg, velocity m/s, duration min.",
)


def _profile_fact(profile: dict | None) -> dict[str, object]:
    if profile is None:
        return {}
    return {key: profile.get(key) for key in PROFILE_KEYS}


def _json_list(value: object) -> list[object]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return list(value) if isinstance(value, (list, tuple)) else []


def _constraints(rows: list[dict]) -> tuple[list[dict[str, object]], int]:
    included: list[dict[str, object]] = []
    excluded_injuries = 0
    for row in rows:
        if str(row.get("kind")) == "injury":
            excluded_injuries += 1
            continue
        included.append({
            "kind": row.get("kind"),
            "region": row.get("region"),
            "severity": row.get("severity"),
            "forbidden_patterns": _json_list(row.get("forbidden_patterns")),
            "forbidden_exercises": _json_list(row.get("forbidden_exercises")),
        })
    return included, excluded_injuries


def athlete_profile(
    conn: sqlite3.Connection,
    *,
    config: IntelligenceConfig,
    clock: Clock | None = None,
) -> Envelope:
    with read_snapshot(conn):
        today = (clock.today() if clock is not None else dt.date.today()).isoformat()
        execution = execution_context(conn, config, clock=clock)
        profile = queries.athlete_profile(conn)
        rows = queries.athlete_constraints(conn)
        constraints, excluded_injuries = _constraints(rows)

        missing: list[str] = []
        if profile is None:
            missing.append("no athlete profile recorded")
        if profile is not None and profile.get("sessions_per_week_target") is None:
            missing.append("no sessions-per-week target")
        if excluded_injuries:
            missing.append(f"{excluded_injuries} injury constraint(s) withheld by policy")

        facts = {
            "profile": FactBlock(
                value=_profile_fact(profile),
                basis="observed",
                method="strength_coach.store.queries.athlete_profile",
                note="Current profile row; retired goal fields are not returned.",
            ),
            "constraints": FactBlock(
                value=constraints,
                basis="observed",
                method="strength_coach.store.queries.athlete_constraints",
                n=len(constraints),
                note="Injury constraints are excluded.",
            ),
        }
        status = "ok" if (profile is not None or constraints) else "no_data"

        envelope = Envelope(
            capability=RESOURCE_NAME,
            version=RESOURCE_VERSION,
            status=status,
            as_of=today,
            period=Period(start=today, end=today, days=1, weeks=None,
                          timezone=execution.timezone),
            units=UNITS,
            facts=facts,
            evidence=(),
            observations=(),
            coverage={
                "constraints_included": len(constraints),
                "injury_constraints_withheld": excluded_injuries,
            },
            missing=tuple(missing),
            limitations=LIMITATIONS,
            quality_flags=(),
            privacy=Privacy(
                classification="training",
                excluded_fields=(
                    "injury constraints",
                    "symptoms",
                    "body measurements",
                    "free-text notes",
                ),
                redactions=(
                    "injury constraints reduced to a withheld count",
                    "profile reduced to training-relevant columns",
                ),
            ),
            provenance=execution.provenance(
                capability=RESOURCE_NAME,
                version=RESOURCE_VERSION,
                arguments={},
                modules=MODULES,
            ),
            generated_at=execution.generated_at,
        )
        envelope.validate()
        return envelope
