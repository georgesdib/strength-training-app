"""Day templates: which slots a generated session contains.

`ingest.sessions` answers "which day was this?"; this module answers "what should the day
contain?". They share `config/templates/days.v1.yaml` but read different blocks, and the
schema version is checked so a stale template fails loudly instead of silently prescribing
yesterday's programme.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from strength_coach.utils import paths

SUPPORTED_SCHEMA_VERSIONS = ("1.0.0",)
LOAD_SOURCES = ("e1rm", "double_progression", "bodyweight")
# The programme is the three-day A/B/C rotation; rep ranges are pooled across it so a rule
# that scopes the whole accessory collection can see every exercise on every day.
DAYS = ("A", "B", "C")


class TemplateError(ValueError):
    """The day template is missing a prescription block or contradicts the constitution."""


@dataclass(frozen=True)
class Slot:
    id: str
    sets: int
    reps_low: int
    reps_high: int
    rir_low: int
    rir_high: int
    rest_s: int | None
    essential: bool
    load_source: str
    exercise: str | None = None
    variants: tuple[str, ...] = field(default_factory=tuple)
    # Power work is prescribed by intent and quality, not by a load target: it is excluded
    # from weekly rep-scheme undulation and carries no double-progression citation.
    power: bool = False

    @property
    def exercises(self) -> tuple[str, ...]:
        if self.exercise:
            return (self.exercise,)
        return self.variants


@dataclass(frozen=True)
class DayTemplate:
    day: str
    slots: tuple[Slot, ...]
    time_cap_s: int
    schema_version: str

    def rep_ranges(self) -> dict[str, tuple[int, int]]:
        """Rep range per exercise, for PRG-DP-001 and for the load solver."""
        ranges: dict[str, tuple[int, int]] = {}
        for slot in self.slots:
            for exercise_id in slot.exercises:
                ranges[exercise_id] = (slot.reps_low, slot.reps_high)
        return ranges

    @classmethod
    def load(cls, day: str = "B", path: str | Path | None = None) -> "DayTemplate":
        source = Path(path or paths.config_dir("templates", "days.v1.yaml"))
        body = source.read_text(encoding="utf-8")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return _parse_template(day, str(source), digest, body)


@lru_cache(maxsize=8)
def _parse_template(day: str, source_name: str, digest: str, body: str) -> DayTemplate:
    source = Path(source_name)
    raw = yaml.safe_load(body) or {}
    schema_version = str(raw.get("schema_version", "unversioned"))
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise TemplateError(
            f"unsupported days template schema {schema_version!r}; "
            f"supported: {SUPPORTED_SCHEMA_VERSIONS}"
        )
    days = raw.get("days") or {}
    if day not in days:
        raise TemplateError(f"day {day!r} is not defined in {source.name}")

    block = days[day].get("prescription")
    if not block:
        # A day without prescription slots cannot be generated. Saying so is better than
        # emitting an empty session that looks valid.
        raise TemplateError(f"day {day!r} has no prescription block")

    slots = tuple(_parse_slot(entry, day) for entry in (block.get("slots") or []))
    if not slots:
        raise TemplateError(f"day {day!r} has an empty prescription block")
    _check_ids(slots)
    return DayTemplate(
        day=day,
        slots=slots,
        time_cap_s=int(block.get("time_cap_s", 4800)),
        schema_version=schema_version,
    )


def all_rep_ranges(path: str | Path | None = None) -> dict[str, tuple[int, int]]:
    """Rep range per exercise across every day.

    The rule that needs these (`PRG-DP-001`) scopes the whole accessory collection, not just
    the day being prescribed. Using the current day's ranges left it unassessable on every day
    because each template is missing at least one scoped exercise (OPEN-QUESTIONS Q16).
    """
    ranges: dict[str, tuple[int, int]] = {}
    for day in DAYS:
        ranges.update(DayTemplate.load(day, path).rep_ranges())
    return ranges


def _parse_slot(entry: Mapping[str, Any], day: str) -> Slot:
    where = f"{day}: slot {entry.get('id', '<unnamed>')}"
    exercise = entry.get("exercise")
    variants = tuple(str(v) for v in (entry.get("exercise_variants") or ()))
    if not exercise and not variants:
        raise TemplateError(f"{where}: needs exercise or exercise_variants")

    load_source = str(entry.get("load_source", "e1rm"))
    if load_source not in LOAD_SOURCES:
        raise TemplateError(f"{where}: load_source must be one of {LOAD_SOURCES}")

    reps = entry.get("reps") or {}
    rir = entry.get("rir") or {}
    try:
        slot = Slot(
            id=str(entry["id"]),
            sets=int(entry.get("sets", 3)),
            reps_low=int(reps["low"]),
            reps_high=int(reps["high"]),
            rir_low=int(rir["low"]),
            rir_high=int(rir["high"]),
            rest_s=int(entry["rest_s"]) if entry.get("rest_s") is not None else None,
            essential=bool(entry.get("essential", True)),
            load_source=load_source,
            exercise=str(exercise) if exercise else None,
            variants=variants,
            power=bool(entry.get("power", False)),
        )
    except KeyError as exc:
        raise TemplateError(f"{where}: missing required field {exc}") from exc

    if slot.reps_low > slot.reps_high:
        raise TemplateError(f"{where}: reps.low > reps.high")
    if slot.rir_low > slot.rir_high:
        raise TemplateError(f"{where}: rir.low > rir.high")
    if slot.sets <= 0:
        raise TemplateError(f"{where}: sets must be positive")
    return slot


def _check_ids(slots: tuple[Slot, ...]) -> None:
    seen: set[str] = set()
    for slot in slots:
        if slot.id in seen:
            raise TemplateError(f"duplicate slot id {slot.id!r}")
        seen.add(slot.id)
