"""Per-region injury signals: evidence for a suitability review, never a clearance.

This replaces the single back-progression summary with a **general** signal plus one per
region (low back, biceps, knee, and any region added to `config/injuries.v1.yaml`).

Three ideas hold it together:

1. **Exposure is measured, not assumed.** A region is loaded by an exercise according to the
   link table in `config/injuries.v1.yaml`; direct loading weighs 2, indirect 1. The table is
   a mechanical mapping, not a causal claim (ASSUMPTION-10).
2. **Tolerance needs a reading after the load.** A loaded session counts as *tolerated* only
   when a symptom reading exists in the following window and no flare appears in it. No
   reading means `unverified`, never "tolerated" (AGENTS.md invariant 12).
3. **The window scales with history.** More previous flares means a longer symptom-free
   streak and more tolerated sessions are required, because recurrence is predicted by prior
   episodes (ASSUMPTION-08; da Silva 2019).

It may recommend; it may never set `exercise_suitability` or clear a constraint
(DEC-BACKSIGNAL-01, DEC-INJURY-01).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import yaml

from strength_coach.domain.symptoms import flare_from
from strength_coach.store import queries
from strength_coach.utils import exercises, paths

DISCLAIMER = (
    "Not medical clearance. A symptom-free streak is weak evidence; the athlete decides, and "
    "a clinician should be involved if there is doubt."
)

STATUS_UNKNOWN = "unknown"
STATUS_INSUFFICIENT = "insufficient"
STATUS_ACTIVE = "active"
STATUS_MONITORING = "monitoring"
STATUS_REVIEW = "review"

# Aggregate ranking: a live flare outranks a review suggestion, which outranks plain
# monitoring. `insufficient` and `unknown` are the bottom because they say nothing.
_SEVERITY = {
    STATUS_UNKNOWN: 0,
    STATUS_INSUFFICIENT: 1,
    STATUS_MONITORING: 2,
    STATUS_REVIEW: 3,
    STATUS_ACTIVE: 4,
}

WEIGHT_DIRECT = 2
WEIGHT_INDIRECT = 1


class InjuryConfigError(ValueError):
    """The injury configuration is invalid or references something that does not exist."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ExerciseLink:
    """Which exercises a region's loading is read from.

    Every clause is optional and they are ORed. `flags` names taxonomy boolean properties
    (e.g. `high_fatigue_spinal`); a flag that does not exist anywhere in the taxonomy is
    rejected, because it would silently match nothing.
    """

    patterns: tuple[str, ...] = ()
    muscles: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    exercises: tuple[str, ...] = ()

    def matches(self, exercise_id: str, props: Mapping[str, Any]) -> bool:
        if exercise_id in self.exercises:
            return True
        pattern = props.get("pattern")
        if pattern is not None and str(pattern) in self.patterns:
            return True
        if any(bool(props.get(flag)) for flag in self.flags):
            return True
        muscles = props.get("primary_muscles") or ()
        if self.muscles and any(str(m) in self.muscles for m in muscles):
            return True
        return False


@dataclass(frozen=True)
class RegionRule:
    region: str
    label: str
    direct: ExerciseLink
    indirect: ExerciseLink
    base_symptom_free_days: int
    days_per_prior_flare: int
    max_symptom_free_days: int
    base_min_tolerated_sessions: int
    sessions_per_prior_flare: int
    max_min_tolerated_sessions: int
    max_entry_age_days: int
    verify_within_days: int
    min_session_load: int

    def weight(self, exercise_id: str, props: Mapping[str, Any]) -> int:
        if self.direct.matches(exercise_id, props):
            return WEIGHT_DIRECT
        if self.indirect.matches(exercise_id, props):
            return WEIGHT_INDIRECT
        return 0

    def window_days(self, prior_flares: int) -> int:
        return min(
            self.base_symptom_free_days + self.days_per_prior_flare * prior_flares,
            self.max_symptom_free_days,
        )

    def required_sessions(self, prior_flares: int) -> int:
        return min(
            self.base_min_tolerated_sessions
            + self.sessions_per_prior_flare * prior_flares,
            self.max_min_tolerated_sessions,
        )


@dataclass(frozen=True)
class InjuryConfig:
    regions: Mapping[str, RegionRule]
    source_path: Path = Path()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "InjuryConfig":
        source = Path(path or paths.injuries_yaml())
        if not source.exists():
            # A missing file means no region is configured; the signal then says `unknown`
            # rather than pretending the athlete is fine.
            return cls(regions=MappingProxyType({}), source_path=source)
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        defaults = raw.get("defaults") or {}
        taxonomy = exercises.taxonomy()
        known_patterns, known_flags, known_muscles = _taxonomy_vocabulary(taxonomy)

        regions: dict[str, RegionRule] = {}
        for name, body in (raw.get("regions") or {}).items():
            region = str(name).strip().lower()
            if region in regions:
                raise InjuryConfigError(f"duplicate region {region!r}")
            if not region:
                raise InjuryConfigError("a region name cannot be empty")
            body = body or {}
            links = body.get("links") or {}
            rule = RegionRule(
                region=region,
                label=str(body.get("label", region.replace("_", " ").title())),
                direct=_link(links.get("direct") or {}, region, known_patterns,
                             known_flags, known_muscles),
                indirect=_link(links.get("indirect") or {}, region, known_patterns,
                               known_flags, known_muscles),
                base_symptom_free_days=_value(
                    body, defaults, "base_symptom_free_days", 28
                ),
                days_per_prior_flare=_value(body, defaults, "days_per_prior_flare", 14),
                max_symptom_free_days=_value(body, defaults, "max_symptom_free_days", 84),
                base_min_tolerated_sessions=_value(
                    body, defaults, "base_min_tolerated_sessions", 4
                ),
                sessions_per_prior_flare=_value(
                    body, defaults, "sessions_per_prior_flare", 2
                ),
                max_min_tolerated_sessions=_value(
                    body, defaults, "max_min_tolerated_sessions", 12
                ),
                max_entry_age_days=_value(body, defaults, "max_entry_age_days", 14),
                verify_within_days=_value(body, defaults, "verify_within_days", 7),
                min_session_load=_value(body, defaults, "min_session_load", 2),
            )
            _validate_rule(rule)
            regions[region] = rule

        if not regions:
            raise InjuryConfigError("no regions configured; the signal would say nothing")
        return cls(regions=MappingProxyType(regions), source_path=source)


def _value(body: Mapping[str, Any], defaults: Mapping[str, Any], key: str,
           fallback: int) -> int:
    if key in body:
        return int(body[key])
    if key in defaults:
        return int(defaults[key])
    return fallback


def _link(raw: Mapping[str, Any], region: str, known_patterns: set[str],
          known_flags: set[str], known_muscles: set[str]) -> ExerciseLink:
    patterns = tuple(str(p) for p in (raw.get("patterns") or ()))
    flags = tuple(str(f) for f in (raw.get("flags") or ()))
    muscles = tuple(str(m) for m in (raw.get("muscles") or ()))
    ids = tuple(str(e) for e in (raw.get("exercises") or ()))
    unknown = [p for p in patterns if p not in known_patterns]
    if unknown:
        # A typo here would make the region load nothing, which reads as "no exposure".
        raise InjuryConfigError(f"{region}: unknown exercise patterns {unknown}")
    unknown = [f for f in flags if f not in known_flags]
    if unknown:
        raise InjuryConfigError(f"{region}: unknown taxonomy flags {unknown}")
    unknown = [m for m in muscles if m not in known_muscles]
    if unknown:
        raise InjuryConfigError(f"{region}: unknown muscles {unknown}")
    return ExerciseLink(patterns=patterns, muscles=muscles, flags=flags, exercises=ids)


def _validate_rule(rule: RegionRule) -> None:
    positive = {
        "base_symptom_free_days": rule.base_symptom_free_days,
        "max_symptom_free_days": rule.max_symptom_free_days,
        "base_min_tolerated_sessions": rule.base_min_tolerated_sessions,
        "max_min_tolerated_sessions": rule.max_min_tolerated_sessions,
        "max_entry_age_days": rule.max_entry_age_days,
        "verify_within_days": rule.verify_within_days,
        "min_session_load": rule.min_session_load,
    }
    for key, value in positive.items():
        if value <= 0:
            raise InjuryConfigError(f"{rule.region}: {key} must be positive, got {value}")
    for key in ("days_per_prior_flare", "sessions_per_prior_flare"):
        if getattr(rule, key) < 0:
            raise InjuryConfigError(f"{rule.region}: {key} cannot be negative")
    if rule.max_symptom_free_days < rule.base_symptom_free_days:
        raise InjuryConfigError(
            f"{rule.region}: max_symptom_free_days is below base_symptom_free_days"
        )
    if rule.max_min_tolerated_sessions < rule.base_min_tolerated_sessions:
        raise InjuryConfigError(
            f"{rule.region}: max_min_tolerated_sessions is below the base"
        )
    if not (rule.direct.patterns or rule.direct.muscles or rule.direct.flags
            or rule.direct.exercises):
        raise InjuryConfigError(f"{rule.region}: no direct loading links; it can never load")


def _taxonomy_vocabulary(taxonomy: exercises.Taxonomy) -> tuple[set[str], set[str],
                                                                set[str]]:
    patterns: set[str] = set()
    flags: set[str] = set()
    muscles: set[str] = set()
    for entity in taxonomy.entities.values():
        pattern = entity.get("pattern")
        if pattern is not None:
            patterns.add(str(pattern))
        flags.update(str(key) for key in entity)
        muscles.update(str(m) for m in (entity.get("primary_muscles") or ()))
    for _regex, rule in taxonomy.patterns:
        synthetic = rule.get("synthetic") or {}
        if synthetic.get("pattern"):
            patterns.add(str(synthetic["pattern"]))
    return patterns, flags, muscles


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RegionSignal:
    region: str
    label: str
    status: str
    summary: str
    symptom_free_days: int | None
    last_flare_on: str | None
    prior_flares: int
    window_days: int
    required_tolerated_sessions: int
    loaded_sessions: int
    tolerated_sessions: int
    unverified_sessions: int
    latest_level: int | None
    linked_exercises: tuple[str, ...]
    recommendation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "symptom_free_days": self.symptom_free_days,
            "last_flare_on": self.last_flare_on,
            "prior_flares": self.prior_flares,
            "window_days": self.window_days,
            "required_tolerated_sessions": self.required_tolerated_sessions,
            "loaded_sessions": self.loaded_sessions,
            "tolerated_sessions": self.tolerated_sessions,
            "unverified_sessions": self.unverified_sessions,
            "latest_level": self.latest_level,
            "linked_exercises": list(self.linked_exercises),
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class InjurySignal:
    status: str
    summary: str
    regions: tuple[RegionSignal, ...] = ()
    ramp_week: int | None = None
    disclaimer: str = DISCLAIMER

    @property
    def active_regions(self) -> tuple[str, ...]:
        return tuple(r.region for r in self.regions if r.status == STATUS_ACTIVE)

    def region(self, name: str) -> RegionSignal | None:
        return next((r for r in self.regions if r.region == name), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "ramp_week": self.ramp_week,
            "regions": {r.region: r.as_dict() for r in self.regions},
            "active_regions": list(self.active_regions),
            "disclaimer": self.disclaimer,
        }


def _days_between(start: str, end: str) -> int:
    return (dt.date.fromisoformat(str(end)[:10])
            - dt.date.fromisoformat(str(start)[:10])).days


def _props_for(taxonomy: exercises.Taxonomy, exercise_id: str) -> Mapping[str, Any]:
    entity = taxonomy.entities.get(exercise_id)
    if entity is not None:
        return entity
    # Accessories resolve to `pattern:<family>` slugs that have no entity of their own.
    if exercise_id.startswith("pattern:"):
        return {"pattern": exercise_id.split(":", 1)[1]}
    return {}


def linked_exercises(rule: RegionRule, taxonomy: exercises.Taxonomy | None = None) -> tuple[str, ...]:
    """What loads this region, for display next to the signal.

    Canonical entity ids plus `pattern:<family>` slugs for linked patterns that have no
    entity of their own (rows, curls, swings). Without the slugs, the biceps region would
    list only pull-ups and silently omit every curl.
    """
    taxonomy = taxonomy or exercises.taxonomy()
    ids = {
        exercise_id
        for exercise_id in taxonomy.entities
        if rule.weight(exercise_id, taxonomy.entities[exercise_id]) > 0
    }
    covered = {taxonomy.entities[i].get("pattern") for i in ids}
    for pattern in set(rule.direct.patterns) | set(rule.indirect.patterns):
        if pattern not in covered:
            ids.add(f"pattern:{pattern}")
    return tuple(sorted(ids))


def compute(conn, on_date: str, *, config: InjuryConfig | None = None,
            ramp_week: int | None = None) -> InjurySignal:
    """Build the general signal and one per configured region."""
    cfg = config or InjuryConfig.load()
    if not cfg.regions:
        return InjurySignal(
            STATUS_UNKNOWN, "no injury regions are configured", (), ramp_week
        )
    entries = queries.symptom_entries(conn)
    taxonomy = exercises.taxonomy()
    signals = tuple(
        _region_signal(conn, rule, entries, on_date, taxonomy)
        for rule in cfg.regions.values()
    )
    return InjurySignal(
        status=_aggregate_status(signals),
        summary=_aggregate_summary(signals),
        regions=signals,
        ramp_week=ramp_week,
    )


def _aggregate_status(signals: Iterable[RegionSignal]) -> str:
    signals = tuple(signals)
    if not signals:
        return STATUS_UNKNOWN
    return max((s.status for s in signals), key=lambda status: _SEVERITY[status])


def _aggregate_summary(signals: Iterable[RegionSignal]) -> str:
    signals = tuple(signals)
    by_status: dict[str, list[str]] = {}
    for signal in signals:
        by_status.setdefault(signal.status, []).append(signal.label)
    if STATUS_ACTIVE in by_status:
        return "flaring: " + ", ".join(by_status[STATUS_ACTIVE])
    if STATUS_REVIEW in by_status:
        return "review suggested for: " + ", ".join(by_status[STATUS_REVIEW])
    if STATUS_MONITORING in by_status:
        return "monitoring: " + ", ".join(by_status[STATUS_MONITORING])
    if STATUS_INSUFFICIENT in by_status:
        return "no recent symptom entry: " + ", ".join(by_status[STATUS_INSUFFICIENT])
    return "no symptom entries, so nothing can be said"


def _region_signal(conn, rule: RegionRule, entries: list[dict], on_date: str,
                   taxonomy: exercises.Taxonomy) -> RegionSignal:
    region_entries = [
        e for e in entries
        if str(e["region"]).lower() == rule.region and str(e["logged_on"]) <= on_date
    ]
    linked = linked_exercises(rule, taxonomy)
    if not region_entries:
        return RegionSignal(
            region=rule.region, label=rule.label, status=STATUS_UNKNOWN,
            summary="no symptom entries for this region",
            symptom_free_days=None, last_flare_on=None, prior_flares=0,
            window_days=rule.window_days(0),
            required_tolerated_sessions=rule.required_sessions(0),
            loaded_sessions=0, tolerated_sessions=0, unverified_sessions=0,
            latest_level=None, linked_exercises=linked,
        )

    latest = region_entries[-1]
    latest_level = int(latest["level"])
    age = _days_between(str(latest["logged_on"]), on_date)
    flares = [e for e in region_entries if flare_from(int(e["level"]), e["settled_within_48h"])]
    last_flare = str(flares[-1]["logged_on"]) if flares else None
    # The flare that ended the current streak is not evidence of a *recurring* problem; the
    # ones before it are. That is what the window scales on (ASSUMPTION-08).
    prior_flares = max(0, len(flares) - 1) if flares else 0
    window = rule.window_days(prior_flares)
    required = rule.required_sessions(prior_flares)

    if latest_level > 0:
        streak = 0
        streak_summary = f"latest reading is level {latest_level}; no clean streak"
    else:
        start = last_flare or str(region_entries[0]["logged_on"])
        streak = max(0, _days_between(start, on_date))
        streak_summary = f"{streak} days since the last flare (or first clean entry)"

    start = last_flare or str(region_entries[0]["logged_on"])
    loaded = _loaded_dates(conn, rule, start, on_date, taxonomy)
    tolerated = sum(
        1 for day in loaded if _verified_tolerated(rule, region_entries, day)
    )
    unverified = len(loaded) - tolerated

    base = dict(
        region=rule.region, label=rule.label,
        symptom_free_days=streak, last_flare_on=last_flare, prior_flares=prior_flares,
        window_days=window, required_tolerated_sessions=required,
        loaded_sessions=len(loaded), tolerated_sessions=tolerated,
        unverified_sessions=unverified, latest_level=latest_level,
        linked_exercises=linked,
    )

    if age > rule.max_entry_age_days:
        return RegionSignal(
            status=STATUS_INSUFFICIENT,
            summary=(f"last entry is {age} days old; log a reading to make this meaningful "
                     f"({streak_summary})"),
            **base,
        )

    current_flare = flare_from(latest_level, latest["settled_within_48h"])
    if current_flare:
        return RegionSignal(
            status=STATUS_ACTIVE,
            summary=f"a flare is active (level {latest_level} on {latest['logged_on']})",
            **base,
        )

    if streak >= window and tolerated >= required:
        return RegionSignal(
            status=STATUS_REVIEW,
            summary=(f"{streak} symptom-free days with {tolerated} tolerated loaded sessions "
                     f"(window {window} days, need {required})"),
            recommendation=(
                "consider reviewing the suitability of the lifts that load this region; "
                "the athlete still decides"
            ),
            **base,
        )

    return RegionSignal(
        status=STATUS_MONITORING,
        summary=(f"{streak_summary}; {tolerated}/{required} tolerated loaded sessions "
                 f"(window {window} days)"),
        **base,
    )


def _loaded_dates(conn, rule: RegionRule, start: str, on_date: str,
                  taxonomy: exercises.Taxonomy) -> dict[str, int]:
    """Region load per training date: sum of (working sets x exercise weight)."""
    rows = conn.execute(
        "SELECT occurred_on, exercise_id, COUNT(*) AS n FROM clean_set "
        "WHERE occurred_on > ? AND occurred_on <= ? AND is_working_set = 1 "
        "GROUP BY occurred_on, exercise_id",
        (start, on_date),
    ).fetchall()
    load: dict[str, int] = {}
    for row in rows:
        exercise_id = str(row["exercise_id"])
        weight = rule.weight(exercise_id, _props_for(taxonomy, exercise_id))
        if weight:
            load[str(row["occurred_on"])] = load.get(str(row["occurred_on"]), 0) + (
                int(row["n"]) * weight
            )
    return {day: value for day, value in load.items() if value >= rule.min_session_load}


def _verified_tolerated(rule: RegionRule, entries: list[dict], day: str) -> bool:
    """Whether a loaded session is followed by a reading with no flare in the window.

    The session is *not* tolerated if any reading in the window is a flare: a flare that
    appears the next day is evidence the load was too much. No reading means unverified.
    """
    end = (dt.date.fromisoformat(day[:10])
           + dt.timedelta(days=rule.verify_within_days)).isoformat()
    window = [e for e in entries if day < str(e["logged_on"]) <= end]
    if not window:
        return False
    return not any(flare_from(int(e["level"]), e["settled_within_48h"]) for e in window)
