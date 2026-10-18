"""The labelled eval set: a human's scores for the rubric.

Format (version 1):

    version: 1
    tolerance: 0.25
    sessions:
      "2026-10-05":
        notes: "felt heavy"
        scores:
          RIR_ADHERENCE: 0.75
          REDUNDANCY: 1.0

Only the measurable items are compared; a human may still mark the unmeasurable ones (duration,
velocity loss), and those marks are reported but never scored. Validation is strict on the
things that would silently corrupt a comparison: unknown item keys, out-of-range values and
duplicate session ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from strength_coach.critique.rubric import RUBRIC_WEIGHTS

FORMAT_VERSION = 1
ITEM_KEYS: tuple[str, ...] = tuple(RUBRIC_WEIGHTS)


class LabelError(ValueError):
    """The labelled set is malformed; refuse rather than compare against garbage."""


@dataclass(frozen=True)
class LabelledSession:
    session_id: str
    scores: Mapping[str, float | None]
    notes: str | None = None
    marked_at: str | None = None

    def score_for(self, key: str) -> float | None:
        return self.scores.get(key)


@dataclass(frozen=True)
class LabelledSet:
    sessions: Mapping[str, LabelledSession]
    tolerance: float = 0.25
    source: str = ""


def load_labels(path: str | Path) -> LabelledSet:
    source = Path(path)
    if not source.exists():
        raise LabelError(f"labelled set not found: {source}")
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise LabelError(f"could not parse {source}: {exc}") from exc

    version = raw.get("version", FORMAT_VERSION)
    if int(version) != FORMAT_VERSION:
        raise LabelError(f"unsupported labelled-set version {version!r}")

    sessions: dict[str, LabelledSession] = {}
    for session_id, block in (raw.get("sessions") or {}).items():
        key = str(session_id)
        if key in sessions:
            raise LabelError(f"duplicate session {key!r}")
        block = block or {}
        scores = _validate_scores(key, block.get("scores") or {})
        sessions[key] = LabelledSession(
            session_id=key,
            scores=scores,
            notes=_optional_str(block.get("notes")),
            marked_at=_optional_str(block.get("marked_at")),
        )

    if not sessions:
        raise LabelError(f"{source} contains no sessions")

    return LabelledSet(
        sessions=sessions,
        tolerance=float(raw.get("tolerance", 0.25)),
        source=str(source),
    )


def _validate_scores(session_id: str, scores: Mapping[str, Any]) -> dict[str, float | None]:
    unknown = sorted(set(map(str, scores)) - set(ITEM_KEYS))
    if unknown:
        raise LabelError(
            f"{session_id}: unknown rubric items {unknown}; expected a subset of {list(ITEM_KEYS)}"
        )
    parsed: dict[str, float | None] = {}
    for key, value in scores.items():
        name = str(key)
        if value is None:
            parsed[name] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise LabelError(f"{session_id}.{name}: not a number ({value!r})") from exc
        if not 0.0 <= number <= 1.0:
            raise LabelError(f"{session_id}.{name}: {number} is outside 0..1")
        parsed[name] = number
    return parsed


def template(session_ids: list[str]) -> dict[str, Any]:
    """A skeleton for a human to fill in; every score starts null."""
    return {
        "version": FORMAT_VERSION,
        "tolerance": 0.25,
        "sessions": {
            session_id: {"notes": "", "scores": {key: None for key in ITEM_KEYS}}
            for session_id in session_ids
        },
    }


def write_template(path: str | Path, session_ids: list[str], *, overwrite: bool = False) -> Path:
    target = Path(path)
    if target.exists() and not overwrite:
        raise LabelError(f"{target} already exists; pass overwrite=True to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(template(session_ids), sort_keys=False), encoding="utf-8")
    return target


def _optional_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)
