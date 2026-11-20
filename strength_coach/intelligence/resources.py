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

from strength_coach import settings_profile
from strength_coach.features import breaks, deload, programme, regime_change
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


PROGRAMME_RESOURCE = "programme_current"
PROGRAMME_URI = "strength://programme/current"
PROGRAMME_VERSION = "1.1.0"
PROGRAMME_MODULES = (
    "strength_coach.settings_profile.state",
    "strength_coach.features.programme.header",
    "strength_coach.rules.context.trained_week_index",
    "strength_coach.prescribe.undulation.Undulation.for_week",
    "strength_coach.prescribe.top_set.competition_window",
    "strength_coach.features.deload.decision",
    "strength_coach.features.regime_change.detect",
    "strength_coach.features.breaks.active_on",
)


def programme_current(
    conn: sqlite3.Connection,
    *,
    config: IntelligenceConfig,
    clock: Clock | None = None,
) -> Envelope:
    """Compact current-programme context: settings, budget, deload and active breaks."""
    with read_snapshot(conn):
        today = (clock.today() if clock is not None else dt.date.today()).isoformat()
        execution = execution_context(conn, config, clock=clock)
        state = settings_profile.state(conn, today)
        decision = deload.decision(conn, today)
        header = programme.header(conn, today)
        regime = regime_change.detect(conn, on_date=today)
        active = breaks.as_dict(breaks.active_on(conn, today))

        facts = {
            "profile": FactBlock(
                value={
                    "profile_id": state.get("profile_id"),
                    "effective_from": state.get("effective_from"),
                    "budget": state.get("budget"),
                },
                basis="observed",
                method="strength_coach.settings_profile.state",
            ),
            "trained_week": FactBlock(
                value=header.get("trained_week"),
                basis="derived",
                method="strength_coach.rules.context.trained_week_index",
            ),
            "dup": FactBlock(
                value=header.get("dup"),
                basis="derived",
                method="strength_coach.prescribe.undulation.Undulation.for_week",
            ),
            "competition": FactBlock(
                value=header.get("competition"),
                basis="derived",
                method="strength_coach.prescribe.top_set.competition_window",
            ),
            "deload": FactBlock(
                value={
                    "active": header["deload"]["status"] == "active",
                    "status": header["deload"]["status"],
                    "calendar_week": header["deload"]["calendar_week"],
                    "reason": header["deload"]["reason"],
                    "trigger": header["deload"]["trigger"],
                    "block_week": getattr(decision, "block_week", None),
                },
                basis="derived",
                method="strength_coach.features.programme.header",
            ),
            "regime": FactBlock(
                value={
                    "window": regime.get("window"),
                    "findings": len(regime.get("findings") or []),
                    "coverage": regime.get("coverage"),
                },
                basis="derived",
                method="strength_coach.features.regime_change.detect",
            ),
            "breaks": FactBlock(
                value=active,
                basis="observed",
                method="strength_coach.features.breaks.active_on",
                n=len(active),
            ),
        }
        missing: list[str] = []
        if state.get("profile_id") is None:
            missing.append("no settings profile is recorded")
        if header.get("trained_week") is None:
            missing.append("no block anchor or trained week is recorded")

        has_context = (
            state.get("profile_id") is not None
            or bool((regime.get("coverage") or {}).get("main_lifts_checked"))
            or bool(active)
            or decision is not None
        )
        envelope = Envelope(
            capability=PROGRAMME_RESOURCE,
            version=PROGRAMME_VERSION,
            status="ok" if has_context else "no_data",
            as_of=today,
            period=Period(start=today, end=today, days=1, weeks=None,
                          timezone=execution.timezone),
            units=UNITS,
            facts=facts,
            evidence=(),
            observations=(),
            coverage={
                "active_breaks": len(active),
                "regime_findings": len(regime.get("findings") or []),
            },
            missing=tuple(missing),
            limitations=(
                "No stored training block exists; settings and budget are the current profile.",
                "Regime findings are counted here; the tool returns them in detail.",
            ),
            quality_flags=(),
            privacy=Privacy(
                classification="training",
                excluded_fields=("injury constraints", "symptoms", "notes"),
                redactions=("regime findings reduced to a count",),
            ),
            provenance=execution.provenance(
                capability=PROGRAMME_RESOURCE,
                version=PROGRAMME_VERSION,
                arguments={},
                modules=PROGRAMME_MODULES,
            ),
            generated_at=execution.generated_at,
        )
        envelope.validate()
        return envelope


OVERVIEW_RESOURCE = "overview_current"
OVERVIEW_URI = "strength://overview/current"
OVERVIEW_VERSION = "1.0.0"


def overview_current(
    conn: sqlite3.Connection,
    *,
    config: IntelligenceConfig,
    clock: Clock | None = None,
) -> Envelope:
    """The four-week overview fact set, as a compact resource envelope."""
    from strength_coach.intelligence.capabilities import overview as overview_capability
    from strength_coach.intelligence.capabilities._common import envelope as build

    today = clock.today() if clock is not None else dt.date.today()
    request = overview_capability.OverviewRequest(as_of=today, window_weeks=4)
    with read_snapshot(conn):
        execution = execution_context(conn, config, clock=clock)
        full = overview_capability.overview(conn, request, execution)
    return build(
        capability=OVERVIEW_RESOURCE,
        version=OVERVIEW_VERSION,
        status=full.status,
        as_of=full.as_of,
        period=full.period,
        facts=full.facts,
        coverage=full.coverage,
        missing=full.missing,
        limitations=full.limitations + (
            "Resource projection of the four-week overview; use the tool for explicit windows.",
        ),
        privacy=full.privacy,
        execution=execution,
        arguments={},
        modules=overview_capability.MODULES,
    )
