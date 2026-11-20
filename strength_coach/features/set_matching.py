"""Shared order-based classification and set-group selection.

The recorded sequence decides a set's working status and its target group; a legacy role is not
read. RIR 6 is the warm-up sentinel by definition (DEC-RIR-01, owner clarification 2026-11-20):
it wins even if a stored working flag or an old role disagrees.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

WARM_UP_RIR = 6


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_set(row: Mapping[str, Any]) -> str:
    """Return warm_up or working. Missing RIR stays working (unknown status)."""
    if _integer(row.get("rir")) == WARM_UP_RIR:
        return "warm_up"
    return "working"


def is_warm_up(row: Mapping[str, Any]) -> bool:
    return classify_set(row) == "warm_up"


def has_missing_rir(row: Mapping[str, Any]) -> bool:
    return _integer(row.get("rir")) is None


def working_sets(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if not is_warm_up(row)]


def warm_up_sets(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if is_warm_up(row)]


def groups(item: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        group for group in (item.get("set_groups") or [])
        if isinstance(group, Mapping)
    ]


def group_index_for_ordinal(item: Mapping[str, Any], ordinal: int) -> int | None:
    """Return the group index for the nth working set of the item, or None for straight sets."""
    values = groups(item)
    if not values:
        return None
    target = ordinal + 1
    cumulative = 0
    for index, group in enumerate(values):
        cumulative += max(0, _integer(group.get("sets")) or 0)
        if target <= cumulative:
            return index
    return len(values) - 1


def group_for_ordinal(
    item: Mapping[str, Any], ordinal: int
) -> Mapping[str, Any] | None:
    index = group_index_for_ordinal(item, ordinal)
    if index is None:
        return None
    return groups(item)[index]

