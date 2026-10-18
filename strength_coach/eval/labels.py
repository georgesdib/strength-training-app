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

# What each item asks, in the direction the engine scores it. Without this the marks are
# ambiguous: "spinal cost" can read as "how much work" (higher = more) or "how compliant"
# (higher = better), and a backtest against the wrong reading measures nothing.
ITEM_GUIDE: dict[str, tuple[str, str]] = {
    "RIR_ADHERENCE": (
        "Did the working sets on primary compounds stay at RIR 2-3?",
        "1.0 = every rated set was inside the window; 0.0 = none were",
    ),
    "PROGRESSION_ADHERENCE": (
        "Did the accessories add load only after reaching the top of the rep range?",
        "1.0 = every accessory progressed as double progression prescribes; 0.0 = none did",
    ),
    "WEEKLY_SPINAL_COST": (
        "Did the week stay inside the high-fatigue spinal cap of 3 weighted exposures?",
        "1.0 = at or under the cap; 0.0 = double the cap or worse. MORE work is a LOWER score",
    ),
    "ESSENTIAL_WORK": (
        "Were the day's essential lifts present (trap bar and a bench variant on day B)?",
        "1.0 = all essential slots present; 0.0 = none",
    ),
    "REDUNDANCY": (
        "Was the session free of stacking (no hinge + erector, no two hinge exercises)?",
        "1.0 = no stacking at all; 0.0 = erector stacked on a hinge AND a second hinge",
    ),
    "ROTATION": (
        "Was exercise selection appropriate for the session's provenance?",
        "1.0 = stable for a self-directed session, or expected rotation for an app-assigned one; "
        "0.0 = churn in a self-directed session",
    ),
    "SESSION_DURATION": (
        "Was the session length appropriate? (the engine cannot measure this)",
        "leave null unless you want to record a judgement; it is never compared",
    ),
    "VELOCITY_LOSS": (
        "Was within-set velocity loss controlled? (not computable from the export)",
        "leave null unless you want to record a judgement; it is never compared",
    ),
}


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


def render_template(session_ids: list[str]) -> str:
    """The skeleton plus the question each item asks, written as comments."""
    lines = [
        "# Labelled eval set -- a human's scores, compared with the engine's.",
        "#",
        "# Score every item 0-1. HIGHER IS ALWAYS BETTER: 1.0 means 'nothing to improve'.",
        "#",
    ]
    for key in ITEM_KEYS:
        question, anchors = ITEM_GUIDE[key]
        lines.append(f"# {key}")
        lines.append(f"#   {question}")
        lines.append(f"#   {anchors}")
        lines.append("")
    lines.append(yaml.safe_dump(template(session_ids), sort_keys=False))
    return "\n".join(lines)


def write_template(path: str | Path, session_ids: list[str], *, overwrite: bool = False) -> Path:
    target = Path(path)
    if target.exists() and not overwrite:
        raise LabelError(f"{target} already exists; pass overwrite=True to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_template(session_ids), encoding="utf-8")
    return target


def _optional_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)
