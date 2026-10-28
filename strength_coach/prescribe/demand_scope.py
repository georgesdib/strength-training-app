"""The exercise set that demand coverage is measured against.

An id outside this set is never selected by the shipped programme, so rating it is not a
priority. The walk lives here rather than in features: features may not import prescribe, and
both the CLI and the report tool need the same answer.
"""

from __future__ import annotations

from strength_coach.prescribe import templates
from strength_coach.utils import exercises, paths


def reachable_ids() -> list[str]:
    """Every canonical id a shipped template or a configured candidate can select."""
    import yaml

    ids: set[str] = set()
    for session_type in templates.SESSION_TYPES:
        for slot in templates.SessionTemplate.load(session_type).slots:
            ids.update(str(item) for item in slot.exercises)
    source = paths.config_dir("variants.v1.yaml")
    if source.is_file():
        variants = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        for slots in (variants.get("slots") or {}).values():
            for candidates in (slots or {}).values():
                ids.update(str(item) for item in (candidates or ()))
    # Refuse ids the taxonomy does not know: coverage over a typo would hide a real gap.
    known = exercises.taxonomy().entities
    return sorted(item for item in ids if item in known)
