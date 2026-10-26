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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from strength_coach.features import volume as volume_feature
from strength_coach.prescribe import schedule, templates
from strength_coach.store import queries, repositories
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
DEFAULT_COMPENSATION_SIMILARITY = {
    "squat": {"hinge": 0.7, "horizontal_push": 0.2},
    "hinge": {"squat": 0.7, "horizontal_push": 0.2},
    "horizontal_push": {"squat": 0.2, "hinge": 0.2, "horizontal_pull": 0.3},
    "horizontal_pull": {"horizontal_push": 0.3},
}

DEFAULT_COMPENSATION_SLOTS = {
    "squat": (
        {"exercise_id": "dumbbell_bench_press", "group": "horizontal_push", "sets": 3},
        {"exercise_id": "rdl", "group": "hinge", "sets": 3},
    ),
    "bench_squat": (
        {"exercise_id": "rdl", "group": "hinge", "sets": 3},
        {"exercise_id": "dumbbell_bench_press", "group": "horizontal_push", "sets": 3},
    ),
    "hinge": (
        {"exercise_id": "dumbbell_bench_press", "group": "horizontal_push", "sets": 3},
    ),
    "bench_hinge": (
        {"exercise_id": "dumbbell_bench_press", "group": "horizontal_push", "sets": 3},
        {"exercise_id": "rdl", "group": "hinge", "sets": 3},
    ),
}

SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")

SET_SECONDS = 30

# A set removed by one of these is a safety/recovery cut and must not be re-added.
SAFETY_REFS = frozenset({"MOD-FAT-001", "MOD-DELOAD-001", "MOD-SPINE-001"})


@dataclass(frozen=True)
class BudgetConfig:
    enabled: bool = False
    weekly_target: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_TARGET))
    weekly_total: float | None = None
    main_lift_floor: int = 3
    compensation_enabled: bool = False
    compensation_apply: bool = False
    compensation_floor: float = 0.1
    compensation_similarity: Mapping[str, Mapping[str, float]] = field(
        default_factory=lambda: {
            key: dict(row) for key, row in DEFAULT_COMPENSATION_SIMILARITY.items()
        }
    )
    compensation_slots: Mapping[str, tuple[Mapping[str, Any], ...]] = field(
        default_factory=lambda: {
            key: tuple(dict(entry) for entry in entries)
            for key, entries in DEFAULT_COMPENSATION_SLOTS.items()
        }
    )
    trim_enabled: bool = True
    top_up_enabled: bool = True
    band_min: float = 1.0
    min_accessory_sets: int = 1
    top_up_max_sets_per_item: int = 8
    set_seconds: float = SET_SECONDS
    session_cap_total: int = 30
    session_cap_pattern: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_CAPS))
    tolerance: float = 0.10
    warmup_estimate_minutes: float = 5.0
    session_time_cap_minutes: float = 80.0
    source_path: Path = Path()

    def total_target(self) -> float:
        if self.weekly_total is not None:
            return float(self.weekly_total)
        return sum(float(value) for value in self.weekly_target.values())

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
        raw_total = body.get("weekly_total")
        total = float(raw_total) if raw_total is not None else sum(targets.values())
        if total < 0:
            raise ValueError("volume budget weekly_total must be non-negative")
        if abs(total - sum(targets.values())) > 0.51:
            raise ValueError(
                "volume budget weekly_total "
                f"{total:g} must equal the sum of weekly_target "
                f"{sum(targets.values()):g}; change both when changing the dose"
            )
        floor = int(body.get("main_lift_floor", 3))
        if floor < 1:
            raise ValueError("volume budget main_lift_floor must be at least 1")
        comp = body.get("compensation") or {}
        comp_enabled = bool(comp.get("enabled", False))
        comp_apply = bool(comp.get("apply", False))
        comp_floor = float(comp.get("floor", 0.1))
        if not 0.0 <= comp_floor <= 1.0:
            raise ValueError("volume budget compensation floor must be between 0 and 1")
        similarity: dict[str, dict[str, float]] = {}
        for group, row in (comp.get("similarity") or DEFAULT_COMPENSATION_SIMILARITY).items():
            if group not in MANAGED_KEYS:
                raise ValueError(f"volume budget compensation unknown group {group!r}")
            similarity[str(group)] = {}
            for other, value in (row or {}).items():
                if other not in MANAGED_KEYS:
                    raise ValueError(
                        f"volume budget compensation unknown group {other!r}"
                    )
                number = float(value)
                if not 0.0 <= number <= 1.0:
                    raise ValueError("compensation similarity must be between 0 and 1")
                similarity[str(group)][str(other)] = number
        slots: dict[str, tuple[dict[str, Any], ...]] = {}
        for session, entries in (comp.get("slots") or DEFAULT_COMPENSATION_SLOTS).items():
            if session not in SESSION_TYPES:
                raise ValueError(f"volume budget compensation unknown session {session!r}")
            parsed: list[dict[str, Any]] = []
            for entry in entries:
                group = str(entry["group"])
                if group not in MANAGED_KEYS:
                    raise ValueError(f"compensation slot unknown group {group!r}")
                sets = int(entry["sets"])
                if sets < 1:
                    raise ValueError("compensation slot sets must be positive")
                load_source = str(entry.get("load_source", "double_progression"))
                if load_source not in templates.LOAD_SOURCES:
                    raise ValueError(
                        f"compensation load_source {load_source!r} is not supported"
                    )
                parsed.append({
                    "exercise_id": str(entry["exercise_id"]),
                    "group": group,
                    "sets": sets,
                    "reps_low": int(entry.get("reps_low", 8)),
                    "reps_high": int(entry.get("reps_high", 12)),
                    "rir_low": int(entry.get("rir_low", 2)),
                    "rir_high": int(entry.get("rir_high", 3)),
                    "rest_s": int(entry.get("rest_s", 90)),
                    "load_source": load_source,
                })
            if not parsed:
                raise ValueError(f"compensation slot for {session!r} is empty")
            slots[str(session)] = tuple(parsed)
        band_min = float(body.get("band_min", 1.0))
        if band_min < 0:
            raise ValueError("volume budget band_min must be non-negative")
        min_sets = int(body.get("min_accessory_sets", 1))
        max_sets = int(body.get("top_up_max_sets_per_item", 8))
        if min_sets < 1 or max_sets < 1 or min_sets > max_sets:
            raise ValueError(
                "volume budget accessory set bounds must be positive and ordered"
            )
        set_seconds = float(body.get("set_seconds", SET_SECONDS))
        if set_seconds <= 0:
            raise ValueError("volume budget set_seconds must be positive")
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
            weekly_total=total,
            main_lift_floor=floor,
            compensation_enabled=comp_enabled,
            compensation_apply=comp_apply,
            compensation_floor=comp_floor,
            compensation_similarity=similarity,
            compensation_slots=slots,
            trim_enabled=bool(body.get("trim_enabled", True)),
            top_up_enabled=bool(body.get("top_up_enabled", True)),
            band_min=band_min,
            min_accessory_sets=min_sets,
            top_up_max_sets_per_item=max_sets,
            set_seconds=set_seconds,
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
    effective: Mapping[str, float], tolerance: float, minimum: float = 1.0
) -> dict[str, float]:
    """Per-group diagnostic band: at least `minimum` sets, otherwise the configured tolerance."""
    return {
        key: max(float(minimum), tolerance * float(effective.get(key, 0)))
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
    essential main lift. The per-pattern session cap and the configured per-item maximum bound it.
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
        per_item = sum(
            max(0, config.top_up_max_sets_per_item - int(row.get("sets") or 0))
            for row in items
        )
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
    bands = per_pattern_band(effective, config.tolerance, config.band_min)
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
        int(row.get("sets") or 0) * (config.set_seconds + int(row.get("rest_s") or 0))
        for row in rows
    )
    return round(seconds / 60.0 + config.warmup_estimate_minutes, 1)


def _delta(changes: list[dict[str, Any]], exercise_id: str, key: str, delta: int) -> None:
    for row in changes:
        if row["exercise_id"] == exercise_id and row["key"] == key:
            row["delta"] += delta
            return
    changes.append({"exercise_id": exercise_id, "key": key, "delta": delta})


def reduce_filled_main_lifts(
    rows: Sequence[Mapping[str, Any]],
    *,
    completed: Mapping[str, int],
    effective: Mapping[str, float],
    floor: int,
) -> dict[str, Any]:
    """Trim a filled group's main lift to the opt-in floor (step 2b).

    "Filled" means the group had already reached its effective target before today. The lift
    stays in the session; only sets are removed, never added. A safety cut is left alone.
    """
    out = [dict(row) for row in rows]
    changed: list[dict[str, Any]] = []
    keep = max(1, int(floor))
    for row in out:
        if not row.get("main_lift") or not row.get("key"):
            continue
        key = row["key"]
        target = float(effective.get(key, 0))
        if target <= 0 or float(completed.get(key, 0)) < target:
            continue
        refs = row.get("refs")
        if refs is None and row.get("item") is not None:
            refs = row["item"].rationale_refs
        if SAFETY_REFS & set(refs or ()):
            continue
        current = int(row["sets"])
        new = min(current, keep)
        if new < current:
            row["sets"] = new
            _delta(changed, row["exercise_id"], key, new - current)
    return {"rows": out, "changed": changed}


def allocate_items(
    rows: Sequence[Mapping[str, Any]],
    *,
    effective: Mapping[str, float],
    completed: Mapping[str, int],
    future_sets: Sequence[Mapping[str, int]],
    persistent: Mapping[str, Mapping[str, Any] | None],
    config: BudgetConfig,
    time_cap_minutes: float,
    safety_keys: Iterable[str] = (),
    allow_top_up: bool = True,
) -> dict[str, Any]:
    """Per-group allocation used by the engine (step 2).

    A group moves only when its own weekly band is crossed and either the total is outside its
    band or the four-week ledger agrees. Accessories only; essential items never move.
    """
    out = [dict(row) for row in rows]
    bands = per_pattern_band(effective, config.tolerance, config.band_min)
    limits = band(effective, config.tolerance)
    projected = projection(completed, pattern_sets(out), future_sets)
    before_projected = dict(projected)
    before_total = sum(before_projected.values())
    total = before_total
    safety = set(safety_keys)
    changed: list[dict[str, Any]] = []
    blocked: list[str] = []
    actions: dict[str, str] = {}

    def recompute() -> None:
        nonlocal projected, total
        projected = projection(completed, pattern_sets(out), future_sets)
        total = sum(projected.values())

    total_over = total > limits["high"]
    total_under = total < limits["low"]

    for key in MANAGED_KEYS:
        target = float(effective.get(key, 0))
        value = float(projected.get(key, 0))
        band_p = bands[key]
        if value < target - band_p:
            week = "under"
        elif value > target + band_p:
            week = "over"
        else:
            continue
        persistent_status = (persistent.get(key) or {}).get("status")
        agrees = persistent_status == week
        if total_over and week == "over":
            actions[key] = "over"
        elif total_under and week == "under":
            actions[key] = "under"
        elif not total_over and not total_under and agrees:
            actions[key] = week

    # Trim first, then top up, so a total overrun is not made worse.
    for key, direction in list(actions.items()):
        if direction != "over":
            continue
        if not config.trim_enabled:
            blocked.append(f"{key}: over, trim disabled")
            continue
        target = float(effective.get(key, 0))
        high = target + bands[key]
        candidates = [
            index for index, row in enumerate(out)
            if row.get("key") == key and not row.get("essential")
        ]
        for index in reversed(candidates):
            while (
                projected.get(key, 0.0) > high
                and out[index]["sets"] > config.min_accessory_sets
            ):
                out[index]["sets"] -= 1
                _delta(changed, out[index]["exercise_id"], key, -1)
                recompute()
        if projected.get(key, 0.0) > high:
            blocked.append(f"{key}: over, no non-essential set left")

    for key, direction in list(actions.items()):
        if direction != "under":
            continue
        if not allow_top_up or not config.top_up_enabled:
            blocked.append(f"{key}: under, top-up disabled in reduce mode")
            continue
        if key in safety:
            blocked.append(f"{key}: safety cut, not re-added")
            continue
        target = float(effective.get(key, 0))
        low = target - bands[key]
        cap = config.session_cap_pattern.get(key, 0)
        candidates = [
            index for index, row in enumerate(out)
            if row.get("key") == key
            and not row.get("essential")
            and row["sets"] < config.top_up_max_sets_per_item
        ]
        if not candidates:
            blocked.append(f"{key}: under, no non-essential capacity")
            continue
        while projected.get(key, 0.0) < low:
            current = pattern_sets(out).get(key, 0)
            if current >= cap:
                blocked.append(f"{key}: under, session cap reached")
                break
            if sum(row["sets"] for row in out) >= config.session_cap_total:
                blocked.append(f"{key}: under, total session cap reached")
                break
            progressed = False
            for index in candidates:
                if out[index]["sets"] >= config.top_up_max_sets_per_item:
                    continue
                out[index]["sets"] += 1
                if estimate_minutes(out, config) > time_cap_minutes:
                    out[index]["sets"] -= 1
                    blocked.append(f"{key}: under, time cap reached")
                    break
                _delta(changed, out[index]["exercise_id"], key, 1)
                recompute()
                progressed = True
                break
            if not progressed:
                break
        if projected.get(key, 0.0) < low and not any(
            item.startswith(f"{key}:") for item in blocked
        ):
            blocked.append(f"{key}: under, no capacity")

    after = pattern_sets(out)
    projected_after = projection(completed, after, future_sets)
    return {
        "rows": out,
        "actions": actions,
        "changed": changed,
        "blocked": blocked,
        "projected_before": before_projected,
        "projected_after": projected_after,
        "total_before": round(before_total, 1),
        "total_after": round(sum(projected_after.values()), 1),
        "target_low": round(limits["low"], 1),
        "target_high": round(limits["high"], 1),
        "time_minutes": estimate_minutes(out, config),
        "top_up": allow_top_up,
    }


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

    if projected_total > limits["high"] and config.trim_enabled:
        action = "trim"
        managed = [
            index for index, row in enumerate(out)
            if row.get("key") in MANAGED_KEYS and not row.get("essential")
        ]
        for index in reversed(managed):
            while (
                projected_total > limits["high"]
                and out[index]["sets"] > config.min_accessory_sets
            ):
                out[index]["sets"] -= 1
                _delta(trimmed, out[index]["exercise_id"], out[index]["key"], -1)
                recompute()
        truncated = projected_total > limits["high"]
    elif projected_total < limits["low"] and config.top_up_enabled:
        action = "top_up"
        while projected_total < limits["low"]:
            candidates = [
                index for index, row in enumerate(out)
                if row.get("key") in MANAGED_KEYS
                and not row.get("essential")
                and int(row["sets"]) < config.top_up_max_sets_per_item
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


def _compensation_similarity(config: BudgetConfig, source: str, receiver: str) -> float:
    if source == receiver:
        return 1.0
    row = config.compensation_similarity.get(source) or {}
    if receiver in row:
        return float(row[receiver])
    reverse = config.compensation_similarity.get(receiver) or {}
    if source in reverse:
        return float(reverse[source])
    return 0.1


def simulate_compensation(
    *,
    session_type: str,
    rows: Sequence[Mapping[str, Any]],
    completed: Mapping[str, int],
    effective: Mapping[str, float],
    projected: Mapping[str, float],
    config: BudgetConfig,
) -> dict[str, Any]:
    """Read-only preview of the 9a compensation slot. Never changes a prescription.

    Freed sets are the non-essential sets of a group that was already filled before today. The
    one optional slot is filled from the best-weighted receiver that is under target and has
    session headroom. Nothing here is applied; `apply` is reserved for 9b.
    """
    if not config.compensation_enabled:
        return {
            "enabled": False,
            "apply": False,
            "status": "disabled",
            "freed": {},
            "source": None,
            "candidates": [],
            "selected": None,
            "note": "9a simulation is disabled in config.",
        }

    freed: dict[str, int] = {}
    for key in MANAGED_KEYS:
        target = float(effective.get(key, 0))
        if target <= 0 or float(completed.get(key, 0)) < target:
            continue
        sets = sum(
            int(row.get("sets") or 0)
            for row in rows
            if row.get("key") == key and not row.get("essential")
        )
        if sets > 0:
            freed[key] = sets
    if not freed:
        return {
            "enabled": True,
            "apply": bool(config.compensation_apply),
            "status": "no_filled_accessory",
            "freed": {},
            "source": None,
            "candidates": [],
            "selected": None,
            "note": "No group is filled with a non-essential accessory in this session.",
        }

    source = max(freed, key=lambda key: freed[key])
    freed_total = sum(freed.values())
    today_sets = pattern_sets(rows)
    session_total = sum(int(row.get("sets") or 0) for row in rows)
    total_high = band(effective, config.tolerance)["high"]
    projected_total = sum(float(value) for value in projected.values())
    weekly_headroom = max(0.0, total_high - projected_total)
    if weekly_headroom <= 0:
        return {
            "enabled": True,
            "apply": bool(config.compensation_apply),
            "status": "weekly_full",
            "freed": freed,
            "source": source,
            "candidates": [],
            "selected": None,
            "note": (
                "The projected week is already at or above the high tolerance band; "
                "9b does not add compensation volume."
            ),
        }
    candidates: list[dict[str, Any]] = []
    for slot in config.compensation_slots.get(session_type, ()):
        group = str(slot["group"])
        if group in freed:
            continue
        target = float(effective.get(group, 0))
        shortfall = target - float(projected.get(group, 0))
        if target <= 0 or shortfall <= 0:
            continue
        session_headroom = max(
            0, config.session_cap_pattern.get(group, 0) - today_sets.get(group, 0)
        )
        total_headroom = max(0, config.session_cap_total - session_total)
        sets = int(
            min(
                freed_total,
                int(slot["sets"]),
                shortfall,
                session_headroom,
                total_headroom,
                weekly_headroom,
            )
        )
        if sets <= 0:
            continue
        similarity = _compensation_similarity(config, source, group)
        weight = max(config.compensation_floor, 1.0 - similarity)
        candidates.append({
            "group": group,
            "exercise_id": str(slot["exercise_id"]),
            "sets": sets,
            "shortfall": round(shortfall, 1),
            "weight": round(weight, 2),
            "reps_low": int(slot.get("reps_low", 8)),
            "reps_high": int(slot.get("reps_high", 12)),
            "rir_low": int(slot.get("rir_low", 2)),
            "rir_high": int(slot.get("rir_high", 3)),
            "rest_s": int(slot.get("rest_s", 90)),
            "load_source": str(slot.get("load_source", "double_progression")),
        })
    if not candidates:
        return {
            "enabled": True,
            "apply": bool(config.compensation_apply),
            "status": "no_receiver",
            "freed": freed,
            "source": source,
            "candidates": [],
            "selected": None,
            "note": "A group is filled, but no slot receiver is under target with headroom.",
        }

    total_weight = sum(float(row["weight"]) for row in candidates)
    for row in candidates:
        row["share"] = round(float(row["weight"]) / total_weight, 2)
    candidates.sort(key=lambda row: (-float(row["weight"]), -int(row["sets"])))
    selected = dict(candidates[0])
    return {
        "enabled": True,
        "apply": bool(config.compensation_apply),
        "status": "simulated",
        "freed": freed,
        "source": source,
        "candidates": candidates,
        "selected": selected,
        "note": (
            "Read-only 9a preview; the engine applies this slot only when the budget is on."
            if not config.compensation_apply
            else "Application is enabled: the engine adds the selected slot when the budget is on."
        ),
    }


def report(
    conn, on_date: str, *, config: BudgetConfig | None = None,
    session_type: str | None = None,
) -> dict[str, Any]:
    """Read-only weekly budget for a date. Writes nothing."""
    cfg = config or BudgetConfig.load()
    start, end = week_bounds(on_date)
    profile = queries.athlete_profile(conn) or {}
    target_frequency = int(profile.get("sessions_per_week_target") or 3)
    profile_max = profile.get("max_session_minutes")
    time_cap = float(cfg.session_time_cap_minutes)
    if profile_max is not None:
        time_cap = min(time_cap, float(profile_max))

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
        today_type = session_type or schedule.next_session_type(conn, str(on_date))
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
    if today_rows:
        compensation = simulate_compensation(
            session_type=str(today_type),
            rows=today_rows,
            completed=completed,
            effective=effective,
            projected=projected,
            config=cfg,
        )
    else:
        compensation = {
            "enabled": cfg.compensation_enabled,
            "apply": False,
            "status": "today_done" if today_done else "no_session",
            "freed": {},
            "source": None,
            "candidates": [],
            "selected": None,
            "note": "No open session to preview compensation for.",
        }

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
        "total_target": round(cfg.total_target(), 1),
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
        "parameters": {
            "weekly_total": round(cfg.total_target(), 1),
            "tolerance": cfg.tolerance,
            "band_min": cfg.band_min,
            "trim_enabled": cfg.trim_enabled,
            "top_up_enabled": cfg.top_up_enabled,
            "min_accessory_sets": cfg.min_accessory_sets,
            "top_up_max_sets_per_item": cfg.top_up_max_sets_per_item,
            "set_seconds": cfg.set_seconds,
            "warmup_estimate_minutes": cfg.warmup_estimate_minutes,
            "session_time_cap_minutes": cfg.session_time_cap_minutes,
            "main_lift_floor": cfg.main_lift_floor,
            "session_cap_total": cfg.session_cap_total,
            "session_cap_per_pattern": dict(cfg.session_cap_pattern),
        },
        "feasibility": feasibility(
            effective, cfg, current_frequency=target_frequency
        ),
        "compensation": compensation,
        "plan": plan,
        "note": (
            "Read-only template projection; the live prescription may include history-driven "
            "sets (for example under-MEV) that this report does not model. Per-group status "
            "and capacity are read-only; the engine applies the budget only when the profile "
            "flag is on."
        ),
    }


def apply(
    items,
    *,
    conn,
    context,
    for_date: str,
    session_type: str,
    config: BudgetConfig | None = None,
) -> tuple[tuple, tuple[str, ...], dict[str, Any]]:
    """Apply the per-group budget to a session's items. No-op unless the profile enables it."""
    cfg = config or BudgetConfig.load()
    profile = queries.athlete_profile(conn) or {}
    if "volume_budget_enabled" in profile:
        enabled = bool(profile.get("volume_budget_enabled"))
    else:
        enabled = cfg.enabled
    if not enabled:
        return tuple(items), (), {"enabled": False}

    data = report(conn, for_date, config=cfg, session_type=session_type)
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        entity = context.entity(item.exercise_id) or {}
        pattern = entity.get("pattern")
        key = volume_feature.volume_target_key(str(pattern)) if pattern else None
        rows.append({
            "index": index,
            "item": item,
            "exercise_id": item.exercise_id,
            "sets": int(item.sets),
            "essential": bool(item.essential),
            "main_lift": bool(entity.get("main_lift")),
            "rest_s": int(item.rest_s or 0),
            "key": key,
        })
    policy = str(profile.get("main_lift_policy") or "preserve")
    main_changed: list[dict[str, Any]] = []
    if policy == "reduce":
        reduced = reduce_filled_main_lifts(
            rows,
            completed=data["completed"],
            effective=data["effective_targets"],
            floor=cfg.main_lift_floor,
        )
        rows = reduced["rows"]
        main_changed = reduced["changed"]
    safety = {
        row["key"] for row in rows
        if row["key"] and SAFETY_REFS & set(row["item"].rationale_refs)
    }
    persistent = {
        key: diag.get("persistent") for key, diag in data["per_pattern"].items()
    }
    profile_max = profile.get("max_session_minutes")
    time_cap = float(cfg.session_time_cap_minutes)
    if profile_max is not None:
        time_cap = min(time_cap, float(profile_max))
    result = allocate_items(
        rows,
        effective=data["effective_targets"],
        completed=data["completed"],
        future_sets=[entry["sets"] for entry in data["future"]],
        persistent=persistent,
        config=cfg,
        time_cap_minutes=time_cap,
        safety_keys=safety,
        allow_top_up=policy != "reduce",
    )
    out = list(items)
    for row in result["rows"]:
        if int(row["sets"]) == int(row["item"].sets):
            continue
        refs = row["item"].rationale_refs
        if "MOD-VOL-003" not in refs:
            refs = refs + ("MOD-VOL-003",)
        out[row["index"]] = replace(
            row["item"], sets=int(row["sets"]), rationale_refs=refs
        )
    warnings: list[str] = []
    if policy == "drop":
        warnings.append(
            "MOD-VOL-003: main_lift_policy 'drop' is not implemented yet; preserving main lifts"
        )
    if main_changed:
        changes = ", ".join(
            f"{row['exercise_id']}{row['delta']:+d}" for row in main_changed
        )
        warnings.append(f"MOD-VOL-003: main-lift reduce; {changes}")
    if result["changed"]:
        changes = ", ".join(
            f"{row['exercise_id']}{row['delta']:+d}" for row in result["changed"]
        )
        warnings.append(f"MOD-VOL-003: volume budget; {changes}")
    outside = (
        result["total_before"] < result["target_low"]
        or result["total_before"] > result["target_high"]
    )
    if result["blocked"] and (result["changed"] or outside):
        warnings.append("MOD-VOL-003: " + "; ".join(result["blocked"]))
    note = {
        "enabled": True,
        "main_lift_policy": policy,
        "main_lift_floor": cfg.main_lift_floor,
        "actions": result["actions"],
        "changed": main_changed + result["changed"],
        "main_lift_reduce": main_changed,
        "blocked": result["blocked"],
        "top_up": result.get("top_up", True),
        "total_before": result["total_before"],
        "total_after": result["total_after"],
        "time_minutes": result["time_minutes"],
    }
    return tuple(out), tuple(warnings), note


def record_exemptions(
    conn,
    *,
    prescription_id: str,
    effective_on: str,
    session_type: str,
    items,
) -> None:
    """Record sets a safety rule removed so the budget never re-adds them (DEC-VOLUME-06).

    Called after the prescription is stored. Items removed entirely are not recorded: the
    budget only tops up items that are present, so it cannot resurrect them.
    """
    try:
        template = templates.SessionTemplate.load(session_type)
    except (ValueError, KeyError):
        return
    slots: dict[str, Any] = {}
    for slot in template.slots:
        exercises = ([slot.exercise] if slot.exercise else []) + list(slot.variants)
        for exercise in exercises:
            slots[str(exercise)] = slot
    for item in items:
        is_mapping = isinstance(item, Mapping)
        exercise = str(item["exercise_id"] if is_mapping else item.exercise_id)
        slot = slots.get(exercise)
        if slot is None:
            continue
        refs = (
            item.get("rationale_refs") or item.get("refs") or ()
            if is_mapping else item.rationale_refs
        )
        sets = int(item["sets"] if is_mapping else item.sets)
        safety = SAFETY_REFS & set(refs)
        if not safety or sets >= int(slot.sets):
            continue
        key = pattern_key(exercise)
        if key is None:
            continue
        repositories.append_volume_exemption(
            conn,
            prescription_id=prescription_id,
            effective_on=effective_on,
            pattern=key,
            sets=int(slot.sets) - sets,
            source=sorted(safety)[0],
        )