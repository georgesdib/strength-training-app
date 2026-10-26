"""Weekly volume budget: target, projection, allocation and feasibility.

This is step 1 of docs/VOLUME-MODULATION-PLAN.md: it computes what the engine *would* do and
changes no prescription. The engine hook and MOD-VOL-003 land later.

It lives in prescribe because it needs the session templates and the rolling schedule; the
features layer may not import those. The weekly target is explicit config, pinned to the
six-session template average by tests/test_volume_budget.py, so a template change fails loudly
instead of silently moving the dose.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from strength_coach.features import volume as volume_feature
from strength_coach.prescribe import schedule, templates
from strength_coach.store import queries
from strength_coach.utils import exercises, paths

# The ledger's target keys. The first eight have MEV/MAV/MRV landmarks and are managed by the
# budget; erector and power work are fixed template doses, included in the weekly total and the
# session cap but never trimmed or topped up.
TARGET_KEYS = (
    "squat", "hinge", "hinge_unilateral", "horizontal_push", "horizontal_pull",
    "vertical_push", "vertical_pull", "core", "erector_extension", "power_jump",
)
MANAGED_KEYS = (
    "squat", "hinge", "hinge_unilateral", "horizontal_push", "horizontal_pull",
    "vertical_push", "vertical_pull", "core",
)

DEFAULT_TARGET = {
    "squat": 10.0, "hinge": 6.5, "hinge_unilateral": 0.0, "horizontal_push": 12.0,
    "horizontal_pull": 9.0, "vertical_push": 3.0, "vertical_pull": 4.5, "core": 6.0,
    "erector_extension": 3.0, "power_jump": 3.0,
}
DEFAULT_CAPS = {
    "squat": 8, "hinge": 6, "hinge_unilateral": 5, "horizontal_push": 8,
    "horizontal_pull": 8, "vertical_push": 5, "vertical_pull": 5, "core": 6,
}

# Matches the minimum-session planner's set cost. It is a planning estimate, not the clock.
SET_SECONDS = 30


@dataclass(frozen=True)
class BudgetConfig:
    enabled: bool = False
    weekly_target: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_TARGET))
    session_cap_total: int = 30
    session_cap_pattern: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_CAPS))
    tolerance: float = 0.10
    warmup_estimate_minutes: float = 5.0
    session_time_cap_minutes: float = 80.0
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "BudgetConfig":
        source = Path(path or paths.config_dir("volume.v1.yaml"))
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        body = raw.get("budget") or {}
        targets = {
            str(key): float(value)
            for key, value in (body.get("weekly_target") or DEFAULT_TARGET).items()
        }
        unknown = sorted(set(targets) - set(TARGET_KEYS))
        missing = sorted(set(TARGET_KEYS) - set(targets))
        if unknown or missing:
            raise ValueError(
                f"volume budget weekly_target: unknown {unknown}, missing {missing}"
            )
        if any(value < 0 for value in targets.values()):
            raise ValueError("volume budget targets must be non-negative")
        cap = body.get("session_cap") or {}
        per_pattern = {
            str(key): int(value)
            for key, value in (cap.get("per_pattern") or DEFAULT_CAPS).items()
        }
        unknown_caps = sorted(set(per_pattern) - set(MANAGED_KEYS))
        missing_caps = sorted(set(MANAGED_KEYS) - set(per_pattern))
        if unknown_caps or missing_caps:
            raise ValueError(
                f"volume budget session_cap: unknown {unknown_caps}, missing {missing_caps}"
            )
        if any(value <= 0 for value in per_pattern.values()):
            raise ValueError("volume budget per-pattern caps must be positive")
        total_cap = int(cap.get("total", 30))
        if total_cap <= 0:
            raise ValueError("volume budget total cap must be positive")
        tolerance = float(body.get("tolerance", 0.10))
        if not 0.0 <= tolerance <= 1.0:
            raise ValueError("volume budget tolerance must be between 0 and 1")
        warmup = float(body.get("warmup_estimate_minutes", 5.0))
        time_cap = float(body.get("session_time_cap_minutes", 80.0))
        if warmup < 0 or time_cap <= 0:
            raise ValueError("volume budget time settings must be positive")
        return cls(
            enabled=bool(body.get("enabled", False)),
            weekly_target=targets,
            session_cap_total=total_cap,
            session_cap_pattern=per_pattern,
            tolerance=tolerance,
            warmup_estimate_minutes=warmup,
            session_time_cap_minutes=time_cap,
            source_path=source,
        )


def week_bounds(on_date: str) -> tuple[str, str]:
    """ISO week (Monday-Sunday) containing the date."""
    day = dt.date.fromisoformat(str(on_date))
    start = day - dt.timedelta(days=day.weekday())
    end = start + dt.timedelta(days=6)
    return start.isoformat(), end.isoformat()


def pattern_key(exercise_id: str, taxonomy: Mapping[str, Any] | None = None) -> str | None:
    tax = taxonomy or exercises.taxonomy()
    entity = tax.entities.get(str(exercise_id), {}) or {}
    pattern = entity.get("pattern")
    if not pattern:
        return None
    return volume_feature.volume_target_key(str(pattern))


def template_rows(session_type: str) -> list[dict[str, Any]]:
    """The session template as budget rows, one row per slot.

    Variant slots use their first exercise: this is a read-only projection, not the selector.
    """
    template = templates.SessionTemplate.load(session_type)
    taxonomy = exercises.taxonomy()
    rows: list[dict[str, Any]] = []
    for slot in template.slots:
        exercise_id = slot.exercise or (slot.variants[0] if slot.variants else None)
        if exercise_id is None:
            continue
        rows.append({
            "exercise_id": str(exercise_id),
            "sets": int(slot.sets),
            "essential": bool(slot.essential),
            "rest_s": int(slot.rest_s or 0),
            "key": pattern_key(str(exercise_id), taxonomy),
            "slot_id": slot.id,
        })
    return rows


def pattern_sets(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    out = {key: 0 for key in TARGET_KEYS}
    for row in rows:
        key = row.get("key")
        if key in out:
            out[key] += int(row.get("sets") or 0)
    return out


def completed_sets(conn, *, on_date: str, include_today: bool) -> dict[str, int]:
    """Working sets in the week before (or through) the date, by ledger key."""
    start, _ = week_bounds(on_date)
    end = str(on_date)
    if not include_today:
        end = (dt.date.fromisoformat(str(on_date)) - dt.timedelta(days=1)).isoformat()
    if start > end:
        return {key: 0 for key in TARGET_KEYS}
    frame = queries.clean_sets(conn, start=start, end=end)
    out = {key: 0 for key in TARGET_KEYS}
    if frame.empty:
        return out
    taxonomy = exercises.taxonomy()
    working = frame[frame["is_working_set"].astype(bool)]
    for exercise_id in working["exercise_id"].astype(str):
        key = pattern_key(exercise_id, taxonomy)
        if key in out:
            out[key] += 1
    return out


def completed_sessions(conn, *, on_date: str) -> int:
    start, _ = week_bounds(on_date)
    frame = queries.sessions(conn, start=start, end=str(on_date))
    return 0 if frame.empty else int(len(frame))


def exemptions(conn, *, on_date: str) -> dict[str, int]:
    start, end = week_bounds(on_date)
    out = {key: 0 for key in TARGET_KEYS}
    for row in queries.volume_exemptions(conn, start=start, end=end):
        key = str(row["pattern"])
        if key in out:
            out[key] += int(row["sets"])
    return out


def effective_targets(
    targets: Mapping[str, float], exempt: Mapping[str, int]
) -> dict[str, float]:
    return {
        key: max(0.0, float(targets.get(key, 0)) - float(exempt.get(key, 0)))
        for key in TARGET_KEYS
    }


def band(targets: Mapping[str, float], tolerance: float) -> dict[str, float]:
    total = sum(float(value) for value in targets.values())
    return {
        "total": max(0.0, tolerance * total),
        "low": total - max(0.0, tolerance * total),
        "high": total + max(0.0, tolerance * total),
    }


def projection(
    completed: Mapping[str, int],
    today: Mapping[str, int],
    future: Iterable[Mapping[str, int]],
) -> dict[str, float]:
    out = {key: float(completed.get(key, 0)) + float(today.get(key, 0)) for key in TARGET_KEYS}
    for sets in future:
        for key in TARGET_KEYS:
            out[key] += float(sets.get(key, 0))
    return out


def per_pattern_band(
    effective: Mapping[str, float], tolerance: float
) -> dict[str, float]:
    """Per-group diagnostic band: at least one set, otherwise the configured tolerance."""
    return {
        key: max(1.0, tolerance * float(effective.get(key, 0)))
        for key in MANAGED_KEYS
    }


def top_up_capacity(
    rows: Sequence[Mapping[str, Any]],
    *,
    config: BudgetConfig,
    current: Mapping[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Non-essential headroom in today's template, per managed group.

    A group with no non-essential item has zero capacity: the budget must not inflate an
    essential main lift. The per-pattern session cap and the per-item maximum (8) bound it.
    """
    current_sets = dict(current or pattern_sets(rows))
    out: dict[str, dict[str, Any]] = {
        key: {"sets": 0, "items": []} for key in MANAGED_KEYS
    }
    for key in MANAGED_KEYS:
        items = [
            row for row in rows
            if row.get("key") == key and not row.get("essential")
        ]
        if not items:
            continue
        headroom = config.session_cap_pattern.get(key, 0) - current_sets.get(key, 0)
        if headroom <= 0:
            continue
        per_item = sum(max(0, 8 - int(row.get("sets") or 0)) for row in items)
        out[key] = {
            "sets": int(min(headroom, per_item)),
            "items": [str(row["exercise_id"]) for row in items],
        }
    return out


def per_pattern_status(
    *,
    targets: Mapping[str, float],
    effective: Mapping[str, float],
    completed: Mapping[str, int],
    projected: Mapping[str, float],
    rows: Sequence[Mapping[str, Any]],
    config: BudgetConfig,
    persistent: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Read-only per-group diagnosis: week status, persistent ledger status and capacity."""
    bands = per_pattern_band(effective, config.tolerance)
    capacity = top_up_capacity(rows, config=config)
    out: dict[str, dict[str, Any]] = {}
    for key in MANAGED_KEYS:
        target = float(effective.get(key, 0))
        value = float(projected.get(key, 0))
        band = bands[key]
        if value < target - band:
            status = "under"
        elif value > target + band:
            status = "over"
        else:
            status = "within"
        out[key] = {
            "target": round(target, 1),
            "target_nominal": round(float(targets.get(key, 0)), 1),
            "completed": int(completed.get(key, 0)),
            "projected": round(value, 1),
            "short": round(max(0.0, target - value), 1),
            "band": round(band, 1),
            "status": status,
            "persistent": dict(persistent.get(key, {})) if persistent else None,
            "top_up_capacity": capacity[key],
        }
    return out


def feasibility(
    targets: Mapping[str, float],
    config: BudgetConfig,
    *,
    current_frequency: int,
) -> dict[str, Any]:
    managed = {key: float(targets.get(key, 0)) for key in MANAGED_KEYS}
    total = sum(float(value) for value in targets.values())
    by_total = math.ceil(total / config.session_cap_total) if total > 0 else 0
    by_pattern = max(
        [math.ceil(value / config.session_cap_pattern[key])
         for key, value in managed.items()
         if value > 0 and config.session_cap_pattern.get(key, 0) > 0] or [0]
    )
    minimum = max(by_total, by_pattern)
    reachable = current_frequency >= minimum
    unreachable = 0.0 if reachable else max(
        0.0, total - current_frequency * config.session_cap_total
    )
    return {
        "min_sessions": minimum,
        "current_frequency": int(current_frequency),
        "reachable": reachable,
        "unreachable_sets": round(unreachable, 1),
    }


def estimate_minutes(rows: Iterable[Mapping[str, Any]], config: BudgetConfig) -> float:
    seconds = sum(
        int(row.get("sets") or 0) * (SET_SECONDS + int(row.get("rest_s") or 0))
        for row in rows
    )
    return round(seconds / 60.0 + config.warmup_estimate_minutes, 1)


def _delta(changes: list[dict[str, Any]], exercise_id: str, key: str, delta: int) -> None:
    for row in changes:
        if row["exercise_id"] == exercise_id and row["key"] == key:
            row["delta"] += delta
            return
    changes.append({"exercise_id": exercise_id, "key": key, "delta": delta})


def plan_session(
    rows: Sequence[Mapping[str, Any]],
    *,
    completed: Mapping[str, int],
    future_sets: Sequence[Mapping[str, int]],
    effective: Mapping[str, float],
    config: BudgetConfig,
    time_cap_minutes: float,
) -> dict[str, Any]:
    """The read-only allocation: trim, top up, or keep today's template.

    The decision is made against the projected week and the effective target, never against
    today's remainder alone. Only non-essential managed rows move; untargeted work is fixed.
    """
    out = [dict(row) for row in rows]
    before = pattern_sets(out)
    projected = projection(completed, before, future_sets)
    projected_before = dict(projected)
    total_before_sets = sum(projected_before.values())
    total_effective = sum(float(value) for value in effective.values())
    limits = band(effective, config.tolerance)
    projected_total = sum(projected.values())
    added: list[dict[str, Any]] = []
    trimmed: list[dict[str, Any]] = []
    action = "keep"
    truncated = False
    time_bound = False

    def recompute() -> None:
        nonlocal projected, projected_total
        projected = projection(completed, pattern_sets(out), future_sets)
        projected_total = sum(projected.values())

    if projected_total > limits["high"]:
        action = "trim"
        managed = [
            index for index, row in enumerate(out)
            if row.get("key") in MANAGED_KEYS and not row.get("essential")
        ]
        for index in reversed(managed):
            while projected_total > limits["high"] and out[index]["sets"] > 1:
                out[index]["sets"] -= 1
                _delta(trimmed, out[index]["exercise_id"], out[index]["key"], -1)
                recompute()
        truncated = projected_total > limits["high"]
    elif projected_total < limits["low"]:
        action = "top_up"
        while projected_total < limits["low"]:
            candidates = [
                index for index, row in enumerate(out)
                if row.get("key") in MANAGED_KEYS
                and not row.get("essential")
                and int(row["sets"]) < 8
                and effective.get(row["key"], 0.0) - projected.get(row["key"], 0.0) > 0
            ]
            if not candidates:
                break
            candidates.sort(
                key=lambda index: (
                    -(effective.get(out[index]["key"], 0.0) - projected.get(out[index]["key"], 0.0)),
                    index,
                )
            )
            progressed = False
            for index in candidates:
                key = out[index]["key"]
                current = pattern_sets(out)
                if current[key] >= config.session_cap_pattern.get(key, 0):
                    continue
                if sum(row["sets"] for row in out) >= config.session_cap_total:
                    break
                out[index]["sets"] += 1
                if estimate_minutes(out, config) > time_cap_minutes:
                    out[index]["sets"] -= 1
                    time_bound = True
                    break
                _delta(added, out[index]["exercise_id"], key, 1)
                recompute()
                progressed = True
                break
            if not progressed:
                break

    after = pattern_sets(out)
    projected_after = projection(completed, after, future_sets)
    total_after = sum(projected_after.values())
    if not added and not trimmed:
        action = "keep"
    return {
        "action": action,
        "before": before,
        "after": after,
        "added": added,
        "trimmed": trimmed,
        "projected_before": projected_before,
        "projected_after": projected_after,
        "total_before": round(total_before_sets, 1),
        "total_after": round(total_after, 1),
        "target_low": round(limits["low"], 1),
        "target_high": round(limits["high"], 1),
        "band": round(limits["total"], 1),
        "shortfall_sets": round(max(0.0, total_effective - total_after), 1),
        "unreachable_sets": round(max(0.0, limits["low"] - total_after), 1),
        "time_minutes": estimate_minutes(out, config),
        "time_cap_minutes": float(time_cap_minutes),
        "time_bound": time_bound,
        "truncated": truncated,
    }


def report(conn, on_date: str, *, config: BudgetConfig | None = None) -> dict[str, Any]:
    """Read-only weekly budget for a date. Writes nothing."""
    cfg = config or BudgetConfig.load()
    start, end = week_bounds(on_date)
    profile = queries.athlete_profile(conn) or {}
    target_frequency = int(profile.get("sessions_per_week_target") or 3)
    time_cap = float(profile.get("max_session_minutes") or cfg.session_time_cap_minutes)

    today_sessions = queries.sessions(conn, start=str(on_date), end=str(on_date))
    today_done = not today_sessions.empty
    today_type = None
    if today_done:
        today_type = str(today_sessions.iloc[-1].get("session_type") or "unknown")

    completed = completed_sets(conn, on_date=on_date, include_today=today_done)
    exempt = exemptions(conn, on_date=on_date)
    effective = effective_targets(cfg.weekly_target, exempt)
    sessions_done = completed_sessions(conn, on_date=on_date)

    if today_done:
        future_count = max(0, target_frequency - sessions_done)
        today_rows: list[dict[str, Any]] = []
        prior: list[str] = []
    else:
        future_count = max(0, target_frequency - sessions_done - 1)
        today_type = schedule.next_session_type(conn, str(on_date))
        today_rows = template_rows(today_type)
        prior = [today_type]

    future_types: list[str] = []
    for _ in range(future_count):
        next_type = schedule.next_session_type(
            conn, str(on_date), prior_types=tuple(prior)
        )
        future_types.append(next_type)
        prior.append(next_type)
    future_sets = [pattern_sets(template_rows(session_type)) for session_type in future_types]

    today_sets = pattern_sets(today_rows)
    projected = projection(completed, today_sets, future_sets)
    # The four-week ledger is the persistence check: one phase week is not a deficit.
    ledger_start = (dt.date.fromisoformat(str(on_date)) - dt.timedelta(days=28)).isoformat()
    ledger = volume_feature.compute(
        queries.clean_sets(conn, start=ledger_start, end=str(on_date)),
        on_date=str(on_date),
    )
    persistent = {
        str(row.get("group")): {
            "status": row["status"],
            "average": row["group_average"],
        }
        for row in ledger["patterns"]
        if str(row.get("group")) in MANAGED_KEYS
    }
    per_pattern = per_pattern_status(
        targets=cfg.weekly_target,
        effective=effective,
        completed=completed,
        projected=projected,
        rows=today_rows,
        config=cfg,
        persistent=persistent,
    )
    limits = band(effective, cfg.tolerance)
    plan = None
    if today_rows:
        plan = plan_session(
            today_rows,
            completed=completed,
            future_sets=future_sets,
            effective=effective,
            config=cfg,
            time_cap_minutes=time_cap,
        )

    return {
        "on_date": str(on_date),
        "week": {"start": start, "end": end},
        "sessions_target": target_frequency,
        "sessions_done": sessions_done,
        "today": {
            "done": today_done,
            "session_type": today_type,
            "sets": today_sets,
        },
        "future": [
            {"session_type": session_type, "sets": sets}
            for session_type, sets in zip(future_types, future_sets)
        ],
        "targets": dict(cfg.weekly_target),
        "exempt": exempt,
        "effective_targets": effective,
        "completed": completed,
        "projection": projected,
        "per_pattern": per_pattern,
        "total_target": round(sum(cfg.weekly_target.values()), 1),
        "total_effective": round(sum(effective.values()), 1),
        "total_projected": round(sum(projected.values()), 1),
        "band": {
            "total": round(limits["total"], 1),
            "low": round(limits["low"], 1),
            "high": round(limits["high"], 1),
        },
        "session_cap": {
            "total": cfg.session_cap_total,
            "per_pattern": dict(cfg.session_cap_pattern),
        },
        "feasibility": feasibility(
            effective, cfg, current_frequency=target_frequency
        ),
        "plan": plan,
        "note": (
            "Read-only template projection; the live prescription may include history-driven "
            "sets (for example under-MEV) that this report does not model. Per-group status "
            "and capacity are read-only; the engine does not apply the budget yet."
        ),
    }
