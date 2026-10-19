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

# A mark is only evidence if the marker actually remembers the session. Reconstructed marks
# are kept (they are still a record) but excluded from the headline agreement, because tuning
# a rubric against a guess would encode the guess.
CONFIDENCE_LEVELS = ("high", "low", "unknown")

# What each item asks, in the direction the engine scores it. Without this the marks are
# ambiguous: "spinal cost" can read as "how much work" (higher = more) or "how compliant"
# (higher = better), and a backtest against the wrong reading measures nothing.
ITEM_GUIDE: dict[str, tuple[str, str]] = {
    "RIR_ADHERENCE": (
        "Did the main working sets stay in the effort window (RIR 1-4, aiming for 2-3)?",
        "1.0 = every rated main set was 1-4; 0.0 = none were. Skip if no main set has an RIR.",
    ),
    "PROGRESSION_ADHERENCE": (
        "Did accessories add load only after reaching the top of their rep range at RIR 2+?",
        "1.0 = every comparable accessory followed that rule; 0.0 = none did. "
        "Skip if no accessory has two comparable sessions.",
    ),
    "WEEKLY_SPINAL_COST": (
        "Did the week stay within the weighted spinal cap (3 exposures)?",
        "1.0 = at or under the cap; 0.0 = at double the cap or worse. "
        "More heavy spinal work lowers this score.",
    ),
    "ESSENTIAL_WORK": (
        "Were the day's essential lifts present? "
        "(A: SSB squat + bench; B: trap bar + a bench variant; C: bench + SSB squat.)",
        "1.0 = all present; 0.0 = none. Skip if the day could not be identified.",
    ),
    "REDUNDANCY": (
        "Was the session free of stacking (no hinge with direct erector work, no two hinges)?",
        "1.0 = no stacking; 0.0 = both problems at once; use a middle value for one.",
    ),
    "ROTATION": (
        "Was exercise selection sensible for who chose the session? "
        "Self-directed: keep lifts stable. App-assigned: rotation is expected.",
        "1.0 = appropriate; 0.0 = churn in a self-directed session.",
    ),
    "SESSION_DURATION": (
        "Did the session length feel appropriate? (The engine cannot measure this.)",
        "Score only if you know; otherwise skip. Never compared with the engine.",
    ),
    "VELOCITY_LOSS": (
        "Was within-set velocity loss controlled? (Not computable from the export.)",
        "Score only if you have a reason to judge it; otherwise skip. Never compared.",
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
    confidence: str = "unknown"

    @property
    def reliable(self) -> bool:
        return self.confidence == "high"

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
        confidence = str(block.get("confidence", "unknown")).lower()
        if confidence not in CONFIDENCE_LEVELS:
            raise LabelError(
                f"{key}.confidence: {confidence!r} is not one of {CONFIDENCE_LEVELS}"
            )
        sessions[key] = LabelledSession(
            session_id=key,
            scores=scores,
            notes=_optional_str(block.get("notes")),
            marked_at=_optional_str(block.get("marked_at")),
            confidence=confidence,
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
            session_id: {
                "confidence": "unknown",
                "notes": "",
                "scores": {key: None for key in ITEM_KEYS},
            }
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
        "# Set confidence per session: high (you remember it), low (reconstructed), or",
        "# unknown. Only high-confidence marks count toward the headline agreement.",
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
