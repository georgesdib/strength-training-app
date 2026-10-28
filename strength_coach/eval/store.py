"""Rubric marks stored in the database, so calibration accumulates.

The YAML format is still supported for import/export (`eval.labels`), but the running source
of truth is `rubric_mark`: append-only, so every review adds evidence and a correction is a
new row rather than an edit.
"""

from __future__ import annotations

from collections.abc import Mapping

from strength_coach.critique.rubric import RUBRIC_VERSION
from strength_coach.eval.labels import ITEM_KEYS, LabelledSession, LabelledSet
from strength_coach.store import queries, repositories

DEFAULT_TOLERANCE = 0.25


def load_marks(conn) -> LabelledSet:
    """The latest mark per (session, item), grouped into sessions.

    Session-level compatibility: a session whose latest marks were made against a different
    rubric definition is excluded whole and counted, not silently mixed into the calibration.
    Mixing versions would compare the current rubric's prediction with a score that answered a
    different question (DEC-EVAL-06).
    """
    rows = queries.latest_rubric_marks(conn)
    scores: dict[str, dict[str, float | None]] = {}
    confidence: dict[str, str] = {}
    marked_at: dict[str, str] = {}
    versions: dict[str, set[str]] = {}

    for row in rows:
        session_id = str(row["session_id"])
        scores.setdefault(session_id, {})[str(row["item"])] = row["score"]
        confidence[session_id] = str(row["confidence"])
        marked_at[session_id] = str(row["marked_at"])
        versions.setdefault(session_id, set()).add(str(row["rubric_version"] or ""))

    stale: dict[str, int] = {}
    kept: dict[str, LabelledSession] = {}
    for session_id, values in scores.items():
        session_versions = versions[session_id]
        if session_versions != {RUBRIC_VERSION}:
            # Whole-session exclusion: a session part-marked under an older definition would
            # otherwise contribute a partial, non-comparable label.
            for version in sorted(session_versions):
                if version != RUBRIC_VERSION:
                    key = version or "unknown"
                    stale[key] = stale.get(key, 0) + 1
            continue
        kept[session_id] = LabelledSession(
            session_id=session_id,
            scores=values,
            confidence=confidence[session_id],
            marked_at=marked_at[session_id],
            rubric_version=RUBRIC_VERSION,
        )

    return LabelledSet(
        sessions=kept,
        tolerance=DEFAULT_TOLERANCE,
        source="database",
        excluded_rubric_versions=stale,
    )


def record_marks(
    conn,
    session_id: str,
    scores: Mapping[str, float | None],
    *,
    confidence: str,
    rubric_version: str,
    note: str | None = None,
) -> int:
    """Append one review's marks; returns how many rows were written.

    A `None` score means "not judged" and writes nothing: writing it would override an
    earlier real mark for that item, which would lose information rather than add it.
    """
    unknown = sorted(set(map(str, scores)) - set(ITEM_KEYS))
    if unknown:
        raise ValueError(f"unknown rubric items: {unknown}")
    if confidence not in {"high", "low", "unknown"}:
        raise ValueError(f"invalid confidence: {confidence!r}")
    for item, score in scores.items():
        if score is None:
            continue
        repositories.append_rubric_mark(
            conn,
            session_id=session_id,
            item=str(item),
            score=float(score),
            confidence=confidence,
            rubric_version=rubric_version,
            note=note,
        )
    return sum(1 for score in scores.values() if score is not None)
