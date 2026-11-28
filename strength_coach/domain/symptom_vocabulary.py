"""Symptom-character and side vocabulary.

The severity scale is unchanged: `symptom_log.level` stays 0-3 and `flare_from` stays the
only definition of a flare (DEC-SYMPTOM-02). Characters describe what a reading felt like.
They are labels, not diagnoses, and nothing reads them to decide anything: no rule, no injury
signal, no deload trigger (DEC-SYMPTOM-05). That is deliberate — "clicking" alone must not
change a prescription, and muscle soreness must not be folded into pain.

The vocabulary lives in `config/symptoms.v1.yaml` so the CLI, the web form and the API render
one list instead of three copies. This module is in `domain` because the store validates on
write, the web layer renders options and the CLI validates flags, and none of those layers may
import each other.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from strength_coach.utils import paths


class SymptomVocabularyError(ValueError):
    """The vocabulary file is missing or invalid, or a value is not in it."""


@dataclass(frozen=True)
class Character:
    """One descriptor: a stable id and the label the athlete sees."""

    id: str
    label: str


@dataclass(frozen=True)
class SeverityBand:
    """A display band over the existing 0-3 scale. Not a threshold."""

    level: int
    label: str


@dataclass(frozen=True)
class SymptomVocabulary:
    characters: tuple[Character, ...] = ()
    sides: tuple[Character, ...] = ()
    severity_bands: tuple[SeverityBand, ...] = ()
    source_path: Path = field(default_factory=Path)

    @property
    def character_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.characters)

    @property
    def side_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.sides)

    def character_label(self, character_id: str) -> str:
        """The label for a stored id; the id itself when the config no longer names it.

        History is not rewritten when a character is removed from the file, so an old row can
        hold an id with no label. Showing the id is honest; dropping the row would not be.
        """
        return next(
            (item.label for item in self.characters if item.id == character_id),
            character_id,
        )

    def side_label(self, side_id: str | None) -> str:
        if not side_id:
            return ""
        return next((item.label for item in self.sides if item.id == side_id), str(side_id))

    def validate_characters(self, values: Iterable[Any] | None) -> tuple[str, ...]:
        """Canonical character ids, in the order given, without duplicates."""
        chosen: list[str] = []
        for raw in values or ():
            text = str(raw).strip().lower()
            if not text or text in chosen:
                continue
            if text not in self.character_ids:
                raise SymptomVocabularyError(
                    f"unknown symptom character {text!r}; "
                    f"known: {', '.join(self.character_ids)}"
                )
            chosen.append(text)
        return tuple(chosen)

    def validate_side(self, value: Any | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        if text not in self.side_ids:
            raise SymptomVocabularyError(
                f"unknown symptom side {text!r}; known: {', '.join(self.side_ids)}"
            )
        return text

    @classmethod
    def load(cls, path: str | Path | None = None) -> SymptomVocabulary:
        source = Path(path or paths.symptoms_yaml())
        if not source.exists():
            raise SymptomVocabularyError(f"symptom vocabulary not found: {source}")
        body = source.read_text(encoding="utf-8")
        # The form is rendered per state read; parsing and validating the same file each time
        # is waste. The digest keeps an edited file from being served from the cache.
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return _parse(str(source), digest, body)


@lru_cache(maxsize=4)
def _parse(source_name: str, digest: str, body: str) -> SymptomVocabulary:
    raw = yaml.safe_load(body) or {}
    if not isinstance(raw, Mapping):
        raise SymptomVocabularyError("symptom vocabulary must be a mapping")
    characters = _items(raw.get("characters"), "characters", required=True)
    sides = _items(raw.get("sides"), "sides")
    bands = _bands(raw.get("severity_bands"))
    if not sides:
        raise SymptomVocabularyError("symptom vocabulary needs at least one side value")
    return SymptomVocabulary(
        characters=characters,
        sides=sides,
        severity_bands=bands,
        source_path=Path(source_name),
    )


def _items(raw: Any, key: str, *, required: bool = False) -> tuple[Character, ...]:
    if not raw:
        if required:
            raise SymptomVocabularyError(f"symptom vocabulary needs at least one {key[:-1]}")
        return ()
    if not isinstance(raw, (list, tuple)):
        raise SymptomVocabularyError(f"{key} must be a list")
    out: list[Character] = []
    seen: set[str] = set()
    for entry in raw:
        if isinstance(entry, Mapping):
            identifier = str(entry.get("id") or "").strip().lower()
            label = str(entry.get("label") or identifier).strip()
        else:
            identifier = str(entry or "").strip().lower()
            label = identifier
        if not identifier:
            raise SymptomVocabularyError(f"{key}: an entry has no id")
        if identifier in seen:
            raise SymptomVocabularyError(f"{key}: duplicate id {identifier!r}")
        seen.add(identifier)
        out.append(Character(identifier, label or identifier))
    return tuple(out)


def _bands(raw: Any) -> tuple[SeverityBand, ...]:
    if not raw:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise SymptomVocabularyError("severity_bands must be a list")
    out: list[SeverityBand] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise SymptomVocabularyError("severity_bands entries must be mappings")
        try:
            level = int(entry.get("level"))
        except (TypeError, ValueError) as exc:
            raise SymptomVocabularyError("severity_bands level must be an integer") from exc
        label = str(entry.get("label") or level)
        out.append(SeverityBand(level, label))
    return tuple(sorted(out, key=lambda item: item.level))
