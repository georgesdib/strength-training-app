"""Exercise taxonomy resolution: raw log string -> canonical, property-carrying id.

Why this exists
---------------
There are 147 distinct exercise names in a 5-year log, they drift over time, and two
of them are known to be mislabelled (see DEC-TRAPBAR-01 / DEC-BACKEXT-01 in
`config/exercises/taxonomy.v1.yaml`). If ingestion, features, prescription, the
policy engine and the agent tools each pattern-matched on the raw string, adding one
exercise would mean five edits and the agent prompts would need to know exercise
names. Instead every row resolves once, here, and all downstream code branches on
properties (`pattern`, `high_fatigue_spinal`, `direct_erector`, `vbt_family`,
`time_based`).

The `applies_to_history` flag is the subtle part. New prescriptions may name either
`back_extension` or the historical `Hyperextensions`; rows keep their own identity, but —
since DEC-BACKEXT-02 amended the original decision — historical hyperextension rows **do**
count as back-extension history for load and dose lookups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from strength_coach.utils import paths

RESOLUTION_ORDER = ("alias_override", "entity_log_name", "classification_pattern")


@dataclass(frozen=True)
class ResolvedExercise:
    """One raw name resolved to a canonical identity plus its properties."""

    id: str
    display: str
    matched_by: str
    applies_to_history: bool
    forward_alias: str | None
    decision: str | None
    props: Mapping[str, Any] = field(default_factory=dict)

    # --- property accessors (downstream code uses these, never raw strings) ---
    def get(self, key: str, default: Any = None) -> Any:
        return self.props.get(key, default)

    @property
    def pattern(self) -> str | None:
        return self.props.get("pattern")

    @property
    def is_main_lift(self) -> bool:
        return bool(self.props.get("main_lift", False))

    @property
    def is_high_fatigue_spinal(self) -> bool:
        return bool(self.props.get("high_fatigue_spinal", False))

    @property
    def is_direct_erector(self) -> bool:
        return bool(self.props.get("direct_erector", False))

    @property
    def is_time_based(self) -> bool:
        return bool(self.props.get("time_based", False))

    @property
    def rep_semantics(self) -> str:
        """'reps' or 'seconds'. Time-based movements log seconds in Reps_Done."""
        return str(self.props.get("rep_semantics", "seconds" if self.is_time_based else "reps"))

    @property
    def vbt_family(self) -> str | None:
        return self.props.get("vbt_family")

    @property
    def counts_toward_back_extension_dose(self) -> bool:
        """DEC-BACKEXT-02: historical hyperextensions DO feed the dose ramp.

        The id stays distinct (identity is preserved), but the movement is the same, so its
        history is usable. The amendment reversed the original DEC-BACKEXT-01 clause.
        """
        if self.id == "back_extension":
            return True
        if self.props.get("history_equivalent_of") == "back_extension":
            return True
        return bool(self.props.get("counts_toward_back_extension_dose", False))


class UnknownExerciseError(KeyError):
    """Raised in strict mode when a name cannot be resolved."""


@dataclass(frozen=True)
class Taxonomy:
    version: str
    entities: Mapping[str, Mapping[str, Any]]
    aliases: Mapping[str, Mapping[str, Any]]
    patterns: tuple[tuple[re.Pattern[str], Mapping[str, Any]], ...]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Taxonomy":
        source = Path(path or paths.taxonomy_yaml())
        with source.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)

        entities = raw.get("entities", {}) or {}
        aliases = {
            str(item["match"]): dict(item)
            for item in (raw.get("alias_overrides") or [])
        }
        patterns: list[tuple[re.Pattern[str], Mapping[str, Any]]] = []
        for item in raw.get("classification_patterns") or []:
            patterns.append((re.compile(item["pattern"]), dict(item)))
        return cls(
            version=str(raw.get("schema_version", "unversioned")),
            entities=entities,
            aliases=aliases,
            patterns=tuple(patterns),
        )

    # ------------------------------------------------------------------
    def resolve(self, name: str | None, on_date: str | None = None) -> ResolvedExercise | None:
        """Resolve one raw name. Returns None if genuinely unknown — never guesses.

        `on_date` matters for identities that changed over time. "Competition Deadlift" was a
        sumo pull before the athlete's switch and a trap-bar pull afterwards (DEC-TRAPBAR-02),
        so the same name can legitimately resolve to two different lifts.
        """
        if name is None:
            return None
        text = str(name).strip()
        if not text:
            return None

        # 1. explicit override wins: it encodes a user decision, not a heuristic.
        alias = self.aliases.get(text)
        if alias is not None:
            canonical = alias["canonical"]
            # Date-scoped identities: the historical lift applies only before the switch.
            switch = alias.get("switch_date")
            historical = alias.get("historical_canonical")
            if historical and switch and on_date is not None:
                if str(on_date)[:10] < str(switch)[:10]:
                    canonical = str(historical)
            entity = self.entities.get(canonical)
            props = dict(entity) if entity else {}
            props.update({k: v for k, v in alias.items() if k in _PROP_KEYS})
            return ResolvedExercise(
                id=canonical,
                display=str(props.get("display", canonical)),
                matched_by="alias_override",
                applies_to_history=bool(alias.get("applies_to_history", True)),
                forward_alias=alias.get("forward_alias"),
                decision=alias.get("decision"),
                props=props,
            )

        # 2. declared log name on an entity
        for entity_id, entity in self.entities.items():
            names = entity.get("log_names") or []
            if text in {str(n).strip() for n in names}:
                return ResolvedExercise(
                    id=entity_id,
                    display=str(entity.get("display", entity_id)),
                    matched_by="entity_log_name",
                    applies_to_history=True,
                    forward_alias=None,
                    decision=None,
                    props=dict(entity),
                )

        # 3. ordered regex fallback. First match wins, so specific patterns precede
        #    general ones ("romanian deadlift" before "deadlift").
        for regex, rule in self.patterns:
            if not regex.search(text):
                continue
            canonical = rule.get("canonical")
            if canonical:
                entity = self.entities.get(canonical, {})
                return ResolvedExercise(
                    id=str(canonical),
                    display=str(entity.get("display", text)),
                    matched_by="classification_pattern",
                    applies_to_history=True,
                    forward_alias=None,
                    decision=None,
                    props=dict(entity),
                )
            synthetic = dict(rule.get("synthetic") or {})
            if synthetic:
                slug = f"pattern:{synthetic.get('pattern', 'unknown')}"
                return ResolvedExercise(
                    id=slug,
                    display=text,
                    matched_by="classification_pattern",
                    applies_to_history=True,
                    forward_alias=None,
                    decision=None,
                    props=synthetic,
                )

        return None

    def classify(self, frame: pd.DataFrame, column: str = "Exercise") -> pd.DataFrame:
        """Return a copy with `exercise_id` and `exercise_matched_by` columns added."""
        resolved = frame[column].map(self.resolve)
        out = frame.copy()
        out["exercise_id"] = resolved.map(lambda r: r.id if r else pd.NA)
        out["exercise_matched_by"] = resolved.map(lambda r: r.matched_by if r else pd.NA)
        out["exercise_decision"] = resolved.map(lambda r: r.decision if r else pd.NA)
        return out

    def unmatched(self, names) -> list[str]:
        """Names that resolve to nothing — reported, then handled by policy."""
        seen: dict[str, None] = {}
        for name in names:
            if self.resolve(name) is None:
                seen.setdefault(str(name), None)
        return sorted(seen)

    def names_for(self, exercise_id: str) -> list[str]:
        entity = self.entities.get(exercise_id) or {}
        return [str(n) for n in (entity.get("log_names") or [])]


# Alias keys that may override entity properties.
_PROP_KEYS = frozenset(
    {
        "display",
        "pattern",
        "main_lift",
        "day_roles",
        "high_fatigue_spinal",
        "direct_erector",
        "erector_family",
        "vbt_family",
        "loadable",
        "time_based",
        "rep_semantics",
    }
)


@lru_cache(maxsize=1)
def taxonomy() -> Taxonomy:
    """Process-wide default taxonomy (cached; tests pass an explicit path instead)."""
    return Taxonomy.load()


def canonical_id(name: str | None, on_date: str | None = None) -> str | None:
    resolved = taxonomy().resolve(name, on_date)
    return resolved.id if resolved else None


def history_equivalents(exercise_id: str) -> tuple[str, ...]:
    """Ids whose rows count as history for this lift.

    `back_extension` carries `hyperextension` (DEC-BACKEXT-02): the rows keep their own
    identity, but the same movement's history is usable for load and dose lookups.
    """
    entities = taxonomy().entities
    equivalents = [exercise_id]
    for candidate, props in entities.items():
        if props.get("history_equivalent_of") == exercise_id:
            equivalents.append(candidate)
    return tuple(equivalents)


def forward_name(name: str | None) -> str | None:
    """Name to *use in a prescription* for a historical log name.

    The reason this differs from `canonical_id`: a historical `Hyperextensions` row keeps
    its own entity id, but new prescriptions talk about `back_extension`. Since
    DEC-BACKEXT-02 its rows also count as back-extension history.
    """
    resolved = taxonomy().resolve(name)
    if resolved is None:
        return None
    return resolved.forward_alias or resolved.id
