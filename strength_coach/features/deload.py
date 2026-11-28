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

from strength_coach.domain.symptoms import flare_from
from strength_coach.features import breaks as breaks_feature
from strength_coach.features import injury_signal
from strength_coach.rules import History, RuleContext, evaluate, load_document
from strength_coach.store import queries, repositories
from strength_coach.utils import exercises, paths, yaml_files


class ScheduledDeloadDecisionError(ValueError):
    def __init__(self, message: str, *, code: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class DeloadConfig:
    enabled: bool = True
    scheduled_enabled: bool = True
    every_weeks: int = 6
    anchor_required: bool = True
    reactive_enabled: bool = True
    reactive_weeks: int = 2
    reactive_flares: int = 2
    local_enabled: bool = True
    local_lookback_days: int = 21
    set_reduction: int = 1
    minimum_sets: int = 2
    include_essential: bool = True
    load_multiplier: float = 0.90
    rir_add: int = 1
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> DeloadConfig:
        source = Path(path or paths.config_dir("deload.v1.yaml"))
        raw = yaml_files.load_yaml_file(source) or {}
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
            local_enabled=bool((reactive.get("local") or {}).get("enabled", True)),
            local_lookback_days=max(
                1, int((reactive.get("local") or {}).get("lookback_days", 21))
            ),
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
    # Scope is explicit so the reducer never applies a full deload and then tries to undo it.
    # `full` keeps the historical behaviour: every item is reduced. `local` reduces only the
    # items whose exercise id the triggering regions load.
    scope: str = "full"
    regions: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    exercise_ids: tuple[str, ...] = ()
    evidence: tuple[dict, ...] = ()
    policy: str = ""
    event_id: str | None = None
    schedule_anchor: str | None = None
    window_starts_on: str | None = None
    window_ends_on: str | None = None
    owner_decision: str | None = None
    owner_decision_id: int | None = None
    owner_decided_on: str | None = None
    owner_reconsider_after: str | None = None

    def applies_to(self, exercise_id: str) -> bool:
        """Whether this decision may change one prescription item."""
        if self.scope == "full":
            return True
        return exercise_id in self.exercise_ids


OWNER_DECISION_LABELS = {
    None: "awaiting",
    "accepted": "accepted",
    "deferred": "deferred (asks again on the next issuance)",
    "dismissed": "dismissed",
}


def owner_decision_label(owner_decision: str | None) -> str:
    """One vocabulary for the CLI, the dashboard card and the contract (DEC-PROGRAMME-14).

    `awaiting` means no choice has been recorded. `deferred` states when the question
    returns, because that is the one label whose consequence is not obvious: the next
    issuance asks again, every time, with no expiry.
    """
    return OWNER_DECISION_LABELS.get(owner_decision, "awaiting")


def deferral_reconsiderable(
    scheduled: DeloadDecision | None, *, issuance_id: str | None = None,
) -> bool:
    """Whether a deferred event must be presented again, decided by issuance, not by a clock.

    A deferral covers exactly the issuance that recorded it (``reconsider_after_issuance_id``).
    Every later issuance is the next eligible issuance and asks again, so a deferral cannot
    silently become acceptance. Without an issuance in hand - the programme header and the nudge
    describe state rather than a request - the deferral is still in force and the event is not
    an actionable suggestion.

    This is the single rule for prescription issuance, the programme header and the nudge, and
    it never consults the calendar.
    """
    if scheduled is None or scheduled.owner_decision != "deferred":
        return False
    if issuance_id is None:
        return False
    return issuance_id != scheduled.owner_reconsider_after


def scheduled_reason(conn, as_of: str, *, config: DeloadConfig | None = None) -> str | None:
    """Return a reason when `as_of` falls in a scheduled deload week, else None."""
    cfg = config or DeloadConfig.load()
    event = _scheduled_event_context(conn, as_of, cfg)
    return event["reason"] if event is not None else None


def _scheduled_event_context(conn, as_of: str, config: DeloadConfig) -> dict | None:
    """The occurrence due on `as_of`, or None when no scheduled deload is due."""
    occurrence = _scheduled_occurrence(conn, as_of, config)
    return occurrence if occurrence is not None and occurrence["due"] else None


def _scheduled_occurrence(
    conn, as_of: str, config: DeloadConfig,
) -> dict | None:
    """The latest scheduled occurrence at or before `as_of`, due or not.

    The event identity is returned even when `as_of` is past its window, because the schedule
    needs it to retire an older unresolved deferral: a block that has come due replaces the
    previous block's answer whether or not the athlete requested a prescription during it.
    """
    if not config.enabled or not config.scheduled_enabled:
        return None
    profile = queries.athlete_profile(conn) or {}
    anchor_raw = profile.get("block_start_date")
    if not anchor_raw:
        return None
    anchor = dt.date.fromisoformat(str(anchor_raw))
    current = dt.date.fromisoformat(as_of)
    if current < anchor:
        return None
    # A scheduled break suppresses the deload while active and restarts the clock on its
    # first day back.
    breaks = [item for item in breaks_feature.all_breaks(conn) if not item.cancelled]
    if any(item.covers(current.isoformat()) for item in breaks):
        return None
    latest_end = None
    for item in breaks:
        end = dt.date.fromisoformat(item.ends_on)
        if end < anchor or end > current:
            continue
        if latest_end is None or end > latest_end:
            latest_end = end
    if latest_end is not None:
        anchor = latest_end + dt.timedelta(days=1)

    postponed = queries.latest_scheduled_deload_postponement(
        conn, as_of=current.isoformat()
    )
    postponed_until = None
    if postponed is not None:
        recorded_on = dt.date.fromisoformat(postponed["recorded_on"])
        if latest_end is None or recorded_on > latest_end:
            postponed_until = dt.date.fromisoformat(postponed["postponed_until"])
            anchor = postponed_until - dt.timedelta(weeks=config.every_weeks - 1)

    week = (current - anchor).days // 7 + 1
    if week < 1:
        return None
    # Every occurrence is a block of `every_weeks` weeks ending in its seven-day window; the
    # latest one at or before today is the newest block the schedule has produced.
    occurrence = week // config.every_weeks
    if occurrence < 1:
        return None
    window_start = anchor + dt.timedelta(
        weeks=(occurrence * config.every_weeks) - 1
    )
    window_end = window_start + dt.timedelta(days=6)
    due_week = occurrence * config.every_weeks
    reason = (
        f"scheduled deload (postponed window starting {postponed_until}; "
        f"every {config.every_weeks} weeks)"
        if postponed_until is not None and current >= postponed_until
        else f"scheduled deload (block week {due_week}; every {config.every_weeks} weeks)"
    )
    return {
        "reason": reason,
        "block_week": due_week,
        "schedule_anchor": anchor,
        "window_starts_on": window_start,
        "window_ends_on": window_end,
        "event_id": f"scheduled:{anchor.isoformat()}:{window_start.isoformat()}",
        "due": window_start <= current <= window_end,
    }


def record_scheduled_decision(
    conn,
    *,
    event: DeloadDecision,
    decision: str,
    expected_decision_id: int | None,
    operation_id: str,
    issuance_id: str,
    decided_at: str,
) -> int:
    choice_map = {"accept": "accepted", "defer": "deferred", "dismiss": "dismissed"}
    persisted = choice_map.get(decision) if isinstance(decision, str) else None
    if persisted is None:
        raise ScheduledDeloadDecisionError(
            "decision must be accept, defer, or dismiss",
            code="validation_failed",
            status=400,
        )
    operation = operation_id.strip() if isinstance(operation_id, str) else ""
    if not operation or len(operation) > 128 or not operation.isascii():
        raise ScheduledDeloadDecisionError(
            "operation_id must be 1-128 ASCII characters",
            code="validation_failed",
            status=400,
        )
    if not event.event_id or not event.schedule_anchor or not event.window_starts_on \
            or not event.window_ends_on:
        raise ScheduledDeloadDecisionError(
            "scheduled deload event is incomplete",
            code="deload_event_changed",
            status=409,
        )
    existing_operation = queries.scheduled_deload_decision_by_operation(
        conn, operation
    )
    if existing_operation is not None:
        if (
            existing_operation["event_id"] != event.event_id
            or existing_operation["decision"] != persisted
        ):
            raise ScheduledDeloadDecisionError(
                "operation_id was already used for a different deload decision",
                code="idempotency_conflict",
                status=409,
            )
        return int(existing_operation["decision_id"])

    latest = queries.latest_scheduled_deload_decision(conn, event.event_id)
    latest_id = int(latest["decision_id"]) if latest else None
    if latest_id != expected_decision_id:
        raise ScheduledDeloadDecisionError(
            "the scheduled-deload decision changed; refresh and try again",
            code="decision_changed",
            status=409,
        )
    if latest is not None and latest["decision"] in {"accepted", "dismissed"}:
        raise ScheduledDeloadDecisionError(
            "this scheduled deload already has a final decision",
            code="decision_already_final",
            status=409,
        )

    return repositories.append_scheduled_deload_decision(
        conn,
        event_id=event.event_id,
        schedule_anchor=event.schedule_anchor,
        window_starts_on=event.window_starts_on,
        window_ends_on=event.window_ends_on,
        decision=persisted,
        decided_at=decided_at,
        operation_id=operation,
        consumed_by_issuance_id=issuance_id,
        reconsider_after_issuance_id=(
            issuance_id if persisted == "deferred" else None
        ),
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
        from strength_coach.analytics import core as derived_core

        context = (
            derived_core.weekly_context(conn, end=as_of)
            if history is None
            else None
        )
        if context is None:
            context = RuleContext.from_store(conn, end=as_of, history=history)
        # Only PRG-SPINE-001 is read below. Selective evaluation returns the same verdict and
        # details for that rule while skipping the other predicates; the full document is still
        # evaluated everywhere else.
        verdict = evaluate(
            document, context, rule_ids=("PRG-SPINE-001",)
        ).verdict("PRG-SPINE-001")
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

    # Only the last N training days are read. Building every training-day record here dominated
    # overview/programme latency; the distinct-date query preserves the same ordering and
    # eligibility (non-voided sessions) without materialising the whole history.
    recent_days = [
        str(row["occurred_on"])
        for row in conn.execute(
            "SELECT DISTINCT occurred_on FROM session "
            "WHERE occurred_on <= ? AND voided = 0 "
            "ORDER BY occurred_on DESC LIMIT ?",
            (as_of, int(cfg.reactive_flares)),
        ).fetchall()
    ]
    recent_days.reverse()
    if len(recent_days) >= cfg.reactive_flares:
        flares = []
        for occurred_on in recent_days:
            entry = queries.latest_symptom(conn, occurred_on)
            flares.append(
                entry is not None
                and flare_from(int(entry["level"]), entry["settled_within_48h"]) is True
            )
        if all(flares):
            return "two consecutive flaring sessions"
    return None


def _days_between(day: str, as_of: str) -> int:
    return (dt.date.fromisoformat(as_of) - dt.date.fromisoformat(str(day)[:10])).days


def _entry_flare(entry: dict | None) -> bool | None:
    """Flare state of one reading: True, False, or None when there is no reading."""
    if entry is None:
        return None
    return flare_from(int(entry["level"]), entry.get("settled_within_48h"))


def local_deloads(conn, as_of: str, *, config: DeloadConfig | None = None,
                  injury_config: injury_signal.InjuryConfig | None = None) -> list[dict]:
    """Regions whose recent relevant exposures are flaring, newest first.

    A region qualifies when two things hold:

    1. its latest observation at or before as_of (any timing -- a flare logged after a
       session is still an active flare) is a flare, and
    2. the leading run of relevant exposures within lookback_days contains at least
       consecutive_flares flaring sessions.

    Relevance reuses the injury signal's own exposure model, so a session counts only when the
    weighted working sets reach the region's min_session_load. An exposure with no reading is
    skipped: it is neither evidence of a flare nor evidence of recovery. A clear reading at an
    exposure stops the run, which is how a non-flaring observation resets the sequence.

    Only regions whose policy.deload is enabled are considered. Every shipped region enables
    it, so this mechanism is live: the back response it joins is unchanged because the reducer
    compares against the factor already applied, so a local deload cannot double the cut
    (DEC-SYMPTOM-06, DEC-PROGRAMME-14).
    """
    cfg = config or DeloadConfig.load()
    if not cfg.enabled or not cfg.reactive_enabled or not cfg.local_enabled:
        return []
    try:
        injury = injury_config or injury_signal.InjuryConfig.load()
        taxonomy = exercises.taxonomy()
    except Exception:
        # A forecast must not fail because an optional safety input is unavailable.
        return []
    start = (
        dt.date.fromisoformat(as_of) - dt.timedelta(days=cfg.local_lookback_days)
    ).isoformat()
    found: list[dict] = []
    for rule in injury.regions.values():
        if not rule.deload_enabled:
            continue
        latest = queries.latest_region_symptom(conn, as_of, region=rule.region)
        if _entry_flare(latest) is not True:
            continue
        loaded = injury_signal.loaded_dates_for(conn, rule, start, as_of, taxonomy)
        run: list[dict] = []
        for day in sorted(loaded, reverse=True):
            entry = queries.latest_region_symptom(conn, day, region=rule.region)
            state = _entry_flare(entry)
            if state is None:
                continue          # unknown exposure: no evidence either way
            if state is not True:
                break             # a clear reading ends the sequence
            run.append({
                "exposure_on": day,
                "level": int(entry["level"]),
                "observed_on": str(entry["logged_on"]),
                "timing": str(entry["timing"]),
            })
            if len(run) >= cfg.reactive_flares:
                break
        if len(run) < cfg.reactive_flares:
            continue
        age = _days_between(str(latest["logged_on"]), as_of)
        found.append({
            "region": rule.region,
            "label": rule.label,
            "exposures": tuple(run),
            "latest": {
                "level": int(latest["level"]),
                "on": str(latest["logged_on"]),
                "timing": str(latest["timing"]),
                "age_days": age,
            },
            "exercise_ids": tuple(injury_signal.linked_exercises(rule, taxonomy)),
            "patterns": tuple(sorted(set(rule.direct.patterns) | set(rule.indirect.patterns))),
            # A reading older than the signal's own staleness bound cannot support a claim
            # about today, so the deload stays (missing is not recovery) and the warning says
            # the evidence is stale.
            "stale": age > rule.max_entry_age_days,
        })
    return found


def local_decision(
    conn, as_of: str, *, config: DeloadConfig | None = None,
    injury_config: injury_signal.InjuryConfig | None = None,
) -> DeloadDecision | None:
    """One scoped decision covering every region that qualifies, or None.

    Regions merge into a single decision so the reducer applies the modifier once. Because the
    modifiers are region-independent by design (one set, one load factor, one RIR step),
    "most protective" is not a choice between values -- it is the union of the scopes.
    """
    cfg = config or DeloadConfig.load()
    active = local_deloads(conn, as_of, config=cfg, injury_config=injury_config)
    if not active:
        return None
    regions = tuple(item["region"] for item in active)
    exercise_ids = tuple(sorted({
        exercise_id for item in active for exercise_id in item["exercise_ids"]
    }))
    patterns = tuple(sorted({pattern for item in active for pattern in item["patterns"]}))
    parts = []
    for item in active:
        exposures = ", ".join(
            f"{exposure['exposure_on']} level {exposure['level']}"
            for exposure in reversed(item["exposures"])
        )
        parts.append(f"{item['label']} ({exposures})")
    stale = [item["label"] for item in active if item["stale"]]
    reason = "local reactive deload -- " + "; ".join(parts)
    if stale:
        reason += (
            f"; evidence is stale for {', '.join(stale)} -- a level 0 reading, or a level 1 "
            f"recorded as settled within 48 h, clears it"
        )
    return DeloadDecision(
        reason,
        "reactive_local",
        block_week=_block_week(conn, as_of),
        scope="local",
        regions=regions,
        patterns=patterns,
        exercise_ids=exercise_ids,
        evidence=tuple(active),
        policy="reactive.local.v1",
    )


def scheduled_decision(
    conn, as_of: str, *, config: DeloadConfig | None = None,
    include_deferred: bool = False,
) -> DeloadDecision | None:
    """Return the scheduled-deload event and its persisted owner decision, if any."""
    cfg = config or DeloadConfig.load()
    latest = _scheduled_occurrence(conn, as_of, cfg)
    event = latest if latest is not None and latest["due"] else None
    # A deferral on an older block is retired once the schedule has produced a newer one; the
    # decision row stays as history, it just stops being presentable.
    pending_deferral = (
        queries.latest_pending_scheduled_deload_deferral(
            conn,
            not_before_window=(
                latest["window_starts_on"].isoformat()
                if latest is not None else None
            ),
        )
        if include_deferred and latest is not None else None
    )
    if pending_deferral is not None and event is None:
        # Nothing is due and a deferral is still in force: the deferral is presented again at
        # the next issuance, which is what `deferral_reconsiderable` decides for the request.
        event = {
            "reason": (
                "scheduled deload (deferred; window "
                f"{pending_deferral['window_starts_on']} to "
                f"{pending_deferral['window_ends_on']})"
            ),
            "block_week": None,
            "schedule_anchor": dt.date.fromisoformat(
                pending_deferral["schedule_anchor"]
            ),
            "window_starts_on": dt.date.fromisoformat(
                pending_deferral["window_starts_on"]
            ),
            "window_ends_on": dt.date.fromisoformat(
                pending_deferral["window_ends_on"]
            ),
            "event_id": pending_deferral["event_id"],
        }
        stored = pending_deferral
    elif event is None:
        return None
    else:
        stored = queries.latest_scheduled_deload_decision(conn, event["event_id"])
    return DeloadDecision(
        reason=event["reason"],
        trigger="scheduled",
        block_week=event["block_week"],
        event_id=event["event_id"],
        schedule_anchor=event["schedule_anchor"].isoformat(),
        window_starts_on=event["window_starts_on"].isoformat(),
        window_ends_on=event["window_ends_on"].isoformat(),
        owner_decision=stored["decision"] if stored else None,
        owner_decision_id=int(stored["decision_id"]) if stored else None,
        owner_decided_on=str(stored["decided_at"])[:10] if stored else None,
        owner_reconsider_after=(
            stored["reconsider_after_issuance_id"] if stored else None
        ),
    )


def reactive_decision(
    conn, as_of: str, *, history: History | None = None,
    config: DeloadConfig | None = None,
) -> DeloadDecision | None:
    """Return an automatic reactive-deload decision for one date.

    The two historical triggers run first and are unchanged. A full-scope decision wins, so a
    regional deload never stacks on a whole-session one; the regional policy is evaluated only
    when neither historical trigger fires.
    """
    reason = reactive_reason(conn, as_of, history=history, config=config)
    if reason is not None:
        return DeloadDecision(reason, "reactive", block_week=_block_week(conn, as_of))
    return local_decision(conn, as_of, config=config)


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