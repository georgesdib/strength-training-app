"""Session identity for the four normal types plus the 9c derived sessions."""

from __future__ import annotations

ORIGINAL_TYPES = ("squat", "hinge", "bench_squat", "bench_hinge")
VOLUME_FILL_PREFIX = "volume_fill_"
TECHNIQUE = "technique"


def is_volume_fill(session_type: str) -> bool:
    return str(session_type).startswith(VOLUME_FILL_PREFIX)


def is_technique(session_type: str) -> bool:
    return str(session_type) == TECHNIQUE


def is_derived(session_type: str) -> bool:
    return is_volume_fill(session_type) or is_technique(session_type)


def original_type(session_type: str) -> str | None:
    value = str(session_type)
    if is_volume_fill(value):
        return value[len(VOLUME_FILL_PREFIX):]
    if is_technique(value):
        return None
    return value


def label(session_type: str) -> str:
    value = str(session_type)
    if is_volume_fill(value):
        original = value[len(VOLUME_FILL_PREFIX):].replace("_", " ")
        return f"Volume fill ({original} omitted)"
    if is_technique(value):
        return "Technique (week complete)"
    return value


def counts_as_main(session_type: str) -> bool:
    return not is_derived(session_type)


def rotation_family(session_type: str) -> str | None:
    value = str(session_type)
    if is_technique(value):
        return None
    if is_volume_fill(value):
        value = value[len(VOLUME_FILL_PREFIX):]
    if value not in ORIGINAL_TYPES:
        return None
    if value in ("bench_squat", "bench_hinge"):
        return "bench"
    return value
