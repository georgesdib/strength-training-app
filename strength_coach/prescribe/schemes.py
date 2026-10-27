"""Rep schemes: named rep ranges a prescription may use.

A scheme is the *only* way the number of repetitions changes. Python solves the load for the
chosen scheme, so the model or the athlete names a scheme rather than a rep count. The lowest
scheme (`maximal`) is excluded on hinge lifts: near-maximal hinging is the highest-risk
exposure for a back-history athlete.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import yaml

from strength_coach.utils import paths


class SchemeError(ValueError):
    """Unknown scheme, or a scheme used where it is not allowed."""


@dataclass(frozen=True)
class Scheme:
    name: str
    label: str
    reps_low: int
    reps_high: int
    exclude: tuple[str, ...] = ()

    def allows(self, exercise_id: str) -> bool:
        return exercise_id not in self.exclude


@dataclass(frozen=True)
class Schemes:
    schemes: Mapping[str, Scheme]
    maximal_hinge_allowed: bool = False

    def get(self, name: str) -> Scheme:
        try:
            return self.schemes[name]
        except KeyError as exc:
            raise SchemeError(f"unknown rep scheme {name!r}") from exc

    def applicable(self, name: str, *, exercise_id: str, essential: bool,
                   maximal_hinge_allowed: bool = False) -> bool:
        """Whether a scheme makes sense for this item.

        `maximal` and `strength` are main-lift schemes; `volume` and `accessory` are for
        assistance work. This mirrors the templates rather than inventing a new rule: a main
        lift is prescribed for strength, an accessory for volume. `maximal_hinge_allowed`
        overrides the configured hinge exclusion; the default keeps the back-history policy.
        """
        scheme = self.get(name)
        if not scheme.allows(exercise_id) and not (
            scheme.name == "maximal" and maximal_hinge_allowed
        ):
            return False
        if scheme.name in ("maximal", "strength"):
            return essential
        return True

    @classmethod
    def load(cls, path: str | Path | None = None) -> Schemes:
        source = Path(path or paths.schemes_yaml())
        if not source.exists():
            raise SchemeError(f"rep schemes file not found: {source}")
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        schemes: dict[str, Scheme] = {}
        for name, entry in (raw.get("schemes") or {}).items():
            reps = entry.get("reps") or []
            if len(reps) != 2 or int(reps[0]) < 1 or int(reps[1]) < int(reps[0]):
                raise SchemeError(f"scheme {name!r} needs an ordered [low, high] rep pair")
            schemes[name] = Scheme(
                name=str(name),
                label=str(entry.get("label", name)),
                reps_low=int(reps[0]),
                reps_high=int(reps[1]),
                exclude=tuple(str(x) for x in (entry.get("exclude") or ())),
            )
        if not schemes:
            raise SchemeError("no rep schemes configured")
        return cls(
            schemes=MappingProxyType(schemes),
            maximal_hinge_allowed=bool(raw.get("maximal_hinge_allowed", False)),
        )


def all_schemes() -> Schemes:
    return Schemes.load()
