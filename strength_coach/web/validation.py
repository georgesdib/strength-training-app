"""Canonical validation shared by the web write paths.

The browser controls improve usability; these checks keep the API authoritative. They are
deliberately small and pure so the tests can exercise them without an HTTP server. Existing
records are never rewritten by validation: a legacy value that is no longer in the current
vocabulary is still readable, but a new write carrying an unknown value is rejected.
"""

from __future__ import annotations

from collections.abc import Iterable

from strength_coach.features.injury_signal import InjuryConfig
from strength_coach.utils import exercises


def _text(value: object) -> str:
    return str(value or "").strip()


def choice(value: object, allowed: Iterable[str], field: str) -> str:
    """Return one canonical value or raise a useful 400-class error."""
    text = _text(value)
    known = tuple(allowed)
    if text not in known:
        raise ValueError(
            f"{field} must be one of: {', '.join(known)} (got {text!r})"
        )
    return text


def list_choice(values: object, allowed: Iterable[str], field: str) -> list[str]:
    """Validate a list of canonical values, preserving order and duplicates."""
    if values in (None, ""):
        return []
    if isinstance(values, str):
        items = [part.strip() for part in values.split(",") if part.strip()]
    elif isinstance(values, Iterable):
        items = [str(item).strip() for item in values if str(item).strip()]
    else:
        raise ValueError(f"{field} must be a list")
    known = tuple(allowed)
    unknown = sorted({item for item in items if item not in known})
    if unknown:
        raise ValueError(
            f"{field} contains unknown value(s): {', '.join(unknown)}; "
            f"known: {', '.join(known)}"
        )
    return items


def exercise_id(value: object, field: str = "exercise_id", *, required: bool = True) -> str:
    """Accept only a canonical exercise id; ids are the stable history key."""
    text = _text(value)
    if not text:
        if required:
            raise ValueError(f"{field} is required")
        return ""
    known = exercises.taxonomy().entities
    if text not in known:
        raise ValueError(f"unknown exercise id {text!r}")
    return text


def optional_exercise_id(value: object, field: str = "exercise_id") -> str | None:
    text = exercise_id(value, field, required=False)
    return text or None


def region(value: object, field: str = "region") -> str:
    config = InjuryConfig.load()
    known = tuple(sorted(config.regions))
    text = _text(value)
    if not known:
        raise ValueError("no injury regions are configured")
    if text not in known:
        raise ValueError(
            f"{field} must be one of: {', '.join(known)} (got {text!r})"
        )
    return text


def exercise_ids(values: object, field: str = "exercise_ids") -> list[str]:
    if values in (None, ""):
        return []
    if isinstance(values, str):
        items = [part.strip() for part in values.split(",") if part.strip()]
    elif isinstance(values, Iterable):
        items = [str(item).strip() for item in values if str(item).strip()]
    else:
        raise ValueError(f"{field} must be a list")
    return [exercise_id(item, field) for item in items]
