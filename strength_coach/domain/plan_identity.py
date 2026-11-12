"""Stable plan-item identity and actual-set attribution.

A plan item's order_index is its identity inside one workout snapshot, not its current
display position: in-workout edits never renumber it. Actual sets store that identity, so a
comparison must join on identity rather than exercise display name. Old plan JSON without the
field still gets a deterministic identity from its initial order, and old set rows written with
a display position are accepted only when that value names an item of the same exercise.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def item_identity(item: Mapping[str, Any], position: int) -> int:
    """Return the stable identity for one plan item, falling back to its position."""
    return int(item.get("order_index", position))


def row_plan_identity(
    items: Sequence[Mapping[str, Any]], row: Mapping[str, Any]
) -> int | None:
    """Resolve a stored set to a stable item identity.

    The stored value is authoritative only when it names an item of the same exercise. Legacy
    rows hold the list position at write time; that position is accepted only when it still
    names the same exercise. Anything else returns None and stays unmatched rather than
    being guessed into the first same-name item.
    """
    value = row.get("prescription_item_index")
    if value is None:
        return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    exercise = str(row.get("exercise_id"))
    for position, item in enumerate(items):
        if item_identity(item, position) == index and str(item.get("exercise_id")) == exercise:
            return index
    if 0 <= index < len(items) and str(items[index].get("exercise_id")) == exercise:
        return item_identity(items[index], index)
    return None
