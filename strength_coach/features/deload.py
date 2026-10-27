"""Deload policy: scheduled low-volume weeks plus the existing reactive triggers.

The evidence for a fixed deload calendar is weak, so this is a configurable policy, not a
scientific claim. The scheduled trigger needs the declared block anchor; without it, only the
reactive triggers run. Application lives in `prescribe.deload` to keep this feature layer below
the prescription layer.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml

from strength_coach.domain.symptoms import flare_from
from strength_coach.features import breaks as breaks_feature
from strength_coach.rules import History, RuleContext, evaluate, load_document
from strength_coach.store import queries
from strength_coach.utils import paths


@dataclass(frozen=True)
class DeloadConfig:
    enabled: bool = True
    scheduled_enabled: bool = True
    every_weeks: int = 6
    anchor_required: bool = True
    reactive_enabled: bool = True
    reactive_weeks: int = 2
    reactive_flares: int = 2
    set_reduction: int = 1
    minimum_sets: int = 2
    include_essential: bool = True
    load_multiplier: float = 0.90
    rir_add: int = 1
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> DeloadConfig:
        source = Path(path or paths.config_dir("deload.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        scheduled = raw.get("scheduled") or {}
        reactive = raw.get("reactive") or {}
        prescription = raw.get("prescription") or {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            scheduled_enabled=bool(scheduled.get("enabled", True)),
            every_weeks=max(1, int(scheduled.get("every_weeks", 6))),
            anchor_required=bool(scheduled.get("anchor_required", True)),
            reactive_enabled=bool(reactive.get("enabled", True)),
            reactive_weeks=max(1, int(reactive.get("consecutive_weeks", 2))),
            reactive_flares=max(1, int(reactive.get("consecutive_flares", 2))),
            set_reduction=max(0, int(prescription.get("set_reduction", 1))),
            minimum_sets=max(1, int(prescription.get("minimum_sets_per_item", 2))),
            include_essential=bool(prescription.get("include_essential", True)),
            load_multiplier=float(prescription.get("load_multiplier", 0.90)),
            rir_add=max(0, int(prescription.get("rir_add", 1))),
            source_path=source,
        )


@dataclass(frozen=True)
class DeloadDecision:
    reason: str
    trigger: str
    block_week: int | None = None


def scheduled_reason(conn, as_of: str, *, config: DeloadConfig | None = None) -> str | None:
    """Return a reason when `as_of` falls in a scheduled deload week, else None."""
    cfg = config or DeloadConfig.load()
    if not cfg.enabled or not cfg.scheduled_enabled:
        return None
    profile = queries.athlete_profile(conn) or {}
    anchor_raw = profile.get("block_start_date")
    if not anchor_raw:
        return None
    anchor = dt.date.fromisoformat(str(anchor_raw))
    current = dt.date.fromisoformat(as_of)
    if current < anchor:
        return None
    # Scheduled time off resets the deload clock: the block restarts after the latest
    # declared break ends. A break that is still active does not also trigger a deload.
    breaks = [item for item in breaks_feature.all_breaks(conn) if not item.cancelled]
    latest_end = None
    for item in breaks:
        end = dt.date.fromisoformat(item.ends_on)
        if end < anchor or end > current:
            continue
        if latest_end is None or end > latest_end:
            latest_end = end
    if latest_end is not None:
        if current <= latest_end:
            return None
        anchor = latest_end + dt.timedelta(days=1)
    week = (current - anchor).days // 7 + 1
    if week % cfg.every_weeks != 0:
        return None
    return (
        f"scheduled deload (block week {week}; every {cfg.every_weeks} weeks)"
    )


def reactive_reason(
    conn, as_of: str, *, history: History | None = None,
    config: DeloadConfig | None = None,
) -> str | None:
    """The two configured reactive triggers: two weeks over the spinal cap, or two flares."""
    cfg = config or DeloadConfig.load()
    if not cfg.enabled or not cfg.reactive_enabled:
        return None
    try:
        document = load_document()
        context = RuleContext.from_store(conn, end=as_of, history=history)
        verdict = evaluate(document, context).verdict("PRG-SPINE-001")
        costs = verdict.details.get("weighted_costs", {}) if verdict.details else {}
        cap = float(verdict.details.get("cap", 3)) if verdict.details else 3.0
        weeks = sorted(costs)
        if len(weeks) >= cfg.reactive_weeks:
            last_two = weeks[-cfg.reactive_weeks:]
            consecutive = (
                dt.date.fromisocalendar(int(last_two[1][:4]), int(last_two[1][6:]), 1)
                - dt.date.fromisocalendar(int(last_two[0][:4]), int(last_two[0][6:]), 1)
            ).days == 7
            if consecutive and all(float(costs[w]) > cap for w in last_two):
                return (
                    f"two consecutive weeks over the spinal cap "
                    f"({last_two[0]}={costs[last_two[0]]:g}, "
                    f"{last_two[1]}={costs[last_two[1]]:g}; cap {cap:g})"
                )
    except Exception:
        # A forecast must not fail because an optional safety input is unavailable.
        pass

    sessions = queries.sessions(conn, end=as_of)
    if len(sessions) >= cfg.reactive_flares:
        flares = []
        for occurred_on in sessions.tail(cfg.reactive_flares)["occurred_on"]:
            entry = queries.latest_symptom(conn, str(occurred_on))
            flares.append(
                entry is not None
                and flare_from(int(entry["level"]), entry["settled_within_48h"]) is True
            )
        if all(flares):
            return "two consecutive flaring sessions"
    return None


def scheduled_decision(
    conn, as_of: str, *, config: DeloadConfig | None = None,
) -> DeloadDecision | None:
    """Return the scheduled-deload suggestion for one date, without applying it."""
    reason = scheduled_reason(conn, as_of, config=config)
    if reason is None:
        return None
    return DeloadDecision(reason, "scheduled", block_week=_block_week(conn, as_of))


def reactive_decision(
    conn, as_of: str, *, history: History | None = None,
    config: DeloadConfig | None = None,
) -> DeloadDecision | None:
    """Return an automatic reactive-deload decision for one date."""
    reason = reactive_reason(conn, as_of, history=history, config=config)
    if reason is None:
        return None
    return DeloadDecision(reason, "reactive", block_week=_block_week(conn, as_of))


def decision(
    conn, as_of: str, *, history: History | None = None,
    include_reactive: bool = True, config: DeloadConfig | None = None,
) -> DeloadDecision | None:
    """Combine scheduled and reactive triggers into one decision for one date.

    This is retained for callers that explicitly want the combined policy; the prescription
    path now separates a scheduled suggestion from an automatic reactive decision.
    """
    cfg = config or DeloadConfig.load()
    if not cfg.enabled:
        return None
    scheduled = scheduled_reason(conn, as_of, config=cfg)
    reactive = (
        reactive_reason(conn, as_of, history=history, config=cfg)
        if include_reactive else None
    )
    if scheduled and reactive:
        return DeloadDecision(
            f"{scheduled}; reactive trigger also active: {reactive}",
            "scheduled+reactive", block_week=_block_week(conn, as_of),
        )
    if scheduled:
        return DeloadDecision(scheduled, "scheduled", block_week=_block_week(conn, as_of))
    if reactive:
        return DeloadDecision(reactive, "reactive", block_week=_block_week(conn, as_of))
    return None


def _block_week(conn, as_of: str) -> int | None:
    profile = queries.athlete_profile(conn) or {}
    anchor_raw = profile.get("block_start_date")
    if not anchor_raw:
        return None
    anchor = dt.date.fromisoformat(str(anchor_raw))
    current = dt.date.fromisoformat(as_of)
    if current < anchor:
        return None
    return (current - anchor).days // 7 + 1