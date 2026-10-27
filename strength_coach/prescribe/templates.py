"""Day templates: which slots a generated session contains.

`ingest.sessions` answers "which session type was this?"; this module answers "what should
the session contain?". The schema version is checked so a stale template fails loudly.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from strength_coach.utils import paths

SUPPORTED_SCHEMA_VERSIONS = ("1.0.0",)
LOAD_SOURCES = ("e1rm", "double_progression", "bodyweight")
SESSION_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")


class TemplateError(ValueError):
    """The day template is missing a prescription block or contradicts the constitution."""


@dataclass(frozen=True)
class Slot:
    id: str
    sets: int
    reps_low: int
    reps_high: int
    rir_low: int | None
    rir_high: int | None
    rest_s: int | None
    essential: bool
    load_source: str
    exercise: str | None = None
    variants: tuple[str, ...] = field(default_factory=tuple)
    # Power work is prescribed by intent and quality, not by a load target: it is excluded
    # from weekly rep-scheme undulation and carries no double-progression citation.
    power: bool = False
    # Optional flare policy. None/auto derives from the taxonomy and the essential flag;
    # hold_effort and erector_dose are explicit template choices (DEC-SPINE-07).
    flare: str | None = None
    # Power work is quality-limited: it carries this stop rule instead of an RIR target
    # (DEC-POWER-02).
    quality_stop: str | None = None

    @property
    def exercises(self) -> tuple[str, ...]:
        if self.exercise:
            return (self.exercise,)
        return self.variants


@dataclass(frozen=True)
class SessionTemplate:
    session_type: str
    label: str
    slots: tuple[Slot, ...]
    time_cap_s: int
    schema_version: str

    def rep_ranges(self) -> dict[str, tuple[int, int]]:
        ranges: dict[str, tuple[int, int]] = {}
        for slot in self.slots:
            for exercise_id in slot.exercises:
                ranges[exercise_id] = (slot.reps_low, slot.reps_high)
        return ranges

    @classmethod
    def load(cls, session_type: str,
             path: str | Path | None = None) -> SessionTemplate:
        source = Path(path or paths.session_types_yaml())
        body = source.read_text(encoding="utf-8")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return _parse_session_template(str(session_type), str(source), digest, body)


@lru_cache(maxsize=8)
def _parse_session_template(session_type: str, source_name: str, digest: str,
                            body: str) -> SessionTemplate:
    raw = yaml.safe_load(body) or {}
    schema_version = str(raw.get("schema_version", "unversioned"))
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise TemplateError(
            f"unsupported session-types schema {schema_version!r}; "
            f"supported: {SUPPORTED_SCHEMA_VERSIONS}"
        )
    types = raw.get("session_types") or {}
    if session_type not in types:
        raise TemplateError(f"session type {session_type!r} is not defined in {Path(source_name).name}")
    block = types[session_type].get("prescription")
    if not block:
        raise TemplateError(f"session type {session_type!r} has no prescription block")
    slots = tuple(_parse_slot(entry, f"{session_type}/{entry.get('id', '<unnamed>')}")
                  for entry in (block.get("slots") or []))
    if not slots:
        raise TemplateError(f"session type {session_type!r} has an empty prescription block")
    _check_ids(slots)
    return SessionTemplate(
        session_type=session_type,
        label=str(types[session_type].get("label", session_type)),
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
    for session_type in SESSION_TYPES:
        ranges.update(SessionTemplate.load(session_type).rep_ranges())
    return ranges




def validate_text(body: str) -> dict[str, Any]:
    """Parse every session type from an edited document before it is written."""
    raw = yaml.safe_load(body) or {}
    schema_version = str(raw.get("schema_version", "unversioned"))
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise TemplateError(
            f"unsupported session-types schema {schema_version!r}; "
            f"supported: {SUPPORTED_SCHEMA_VERSIONS}"
        )
    types = raw.get("session_types") or {}
    missing = sorted(set(SESSION_TYPES) - set(types))
    extra = sorted(set(types) - set(SESSION_TYPES))
    if missing or extra:
        raise TemplateError(f"session_types must be exactly {SESSION_TYPES}; missing {missing}, extra {extra}")
    for session_type in SESSION_TYPES:
        block = (types.get(session_type) or {}).get("prescription")
        if not block:
            raise TemplateError(f"{session_type}: missing prescription block")
        try:
            cap = int(block.get("time_cap_s", 4800))
        except (TypeError, ValueError) as exc:
            raise TemplateError(f"{session_type}: time_cap_s must be an integer") from exc
        if cap <= 0:
            raise TemplateError(f"{session_type}: time_cap_s must be positive")
        slots = block.get("slots") or []
        if not slots:
            raise TemplateError(f"{session_type}: prescription has no slots")
        if not any(bool(slot.get("essential")) for slot in slots):
            raise TemplateError(f"{session_type}: at least one slot must be essential")
        for slot in slots:
            has_exercise = bool(slot.get("exercise"))
            has_variants = bool(slot.get("exercise_variants"))
            if has_exercise == has_variants:
                raise TemplateError(
                    f"{session_type}/{slot.get('id', '<unnamed>')}: use exactly one of "
                    "exercise or exercise_variants"
                )
        _parse_session_template(session_type, f"<edited {session_type}>", "edited", body)
    return raw


def _parse_slot(entry: Mapping[str, Any], day: str) -> Slot:
    where = f"{day}: slot {entry.get('id', '<unnamed>')}"
    exercise = entry.get("exercise")
    variants = tuple(str(v) for v in (entry.get("exercise_variants") or ()))
    if not exercise and not variants:
        raise TemplateError(f"{where}: needs exercise or exercise_variants")

    load_source = str(entry.get("load_source", "e1rm"))
    if load_source not in LOAD_SOURCES:
        raise TemplateError(f"{where}: load_source must be one of {LOAD_SOURCES}")

    flare = entry.get("flare")
    if flare is not None and flare not in ("auto", "hold_effort", "erector_dose"):
        raise TemplateError(
            f"{where}: flare must be auto, hold_effort or erector_dose"
        )

    reps = entry.get("reps") or {}
    power = bool(entry.get("power", False))
    quality_stop = entry.get("quality_stop")
    if power:
        if entry.get("rir") is not None:
            raise TemplateError(
                f"{where}: power work must not carry an RIR target; use quality_stop "
                "(DEC-POWER-02)"
            )
        if not isinstance(quality_stop, str) or not quality_stop.strip():
            raise TemplateError(f"{where}: power work needs a quality_stop")
        rir_low = rir_high = None
    else:
        if quality_stop is not None:
            raise TemplateError(f"{where}: quality_stop is only for power work")
        rir = entry.get("rir") or {}
        try:
            rir_low = int(rir["low"])
            rir_high = int(rir["high"])
        except KeyError as exc:
            raise TemplateError(f"{where}: missing required field {exc}") from exc
    try:
        slot = Slot(
            id=str(entry["id"]),
            sets=int(entry.get("sets", 3)),
            reps_low=int(reps["low"]),
            reps_high=int(reps["high"]),
            rir_low=rir_low,
            rir_high=rir_high,
            rest_s=int(entry["rest_s"]) if entry.get("rest_s") is not None else None,
            essential=bool(entry.get("essential", True)),
            load_source=load_source,
            exercise=str(exercise) if exercise else None,
            variants=variants,
            power=power,
            flare=str(flare) if flare is not None else None,
            quality_stop=str(quality_stop) if power else None,
        )
    except KeyError as exc:
        raise TemplateError(f"{where}: missing required field {exc}") from exc

    if slot.reps_low > slot.reps_high:
        raise TemplateError(f"{where}: reps.low > reps.high")
    if (
        slot.rir_low is not None
        and slot.rir_high is not None
        and slot.rir_low > slot.rir_high
    ):
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
