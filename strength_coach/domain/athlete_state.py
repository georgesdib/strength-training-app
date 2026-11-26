"""Canonical athlete-state vocabulary shared by the UI and the store.

The database CHECK constraints are the final authority; these tuples exist so the web layer
can render the same values instead of duplicating labels in JavaScript. Keep them in sync with
strength_coach/store/migrations/0003_athlete_state.sql (there is a test for that).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CONSTRAINT_KINDS = ("injury", "contraindication", "mobility", "asymmetry")
CONSTRAINT_KIND_LABELS = {
    "injury": "Injury",
    "contraindication": "Contraindication",
    "mobility": "Mobility limitation",
    "asymmetry": "Asymmetry",
}

SEVERITIES = ("hard_exclude", "caution", "monitor")
SEVERITY_LABELS = {
    "hard_exclude": "Hard exclude",
    "caution": "Caution",
    "monitor": "Monitor",
}


SUITABILITY_DEFAULTS = {"can_do": True, "will_do": True, "feels_bad": False}


def suitability_values(rating: Mapping[str, Any] | None) -> dict[str, bool]:
    """Suitability flags with the athlete-facing defaults for absent fields.

    A missing rating is not a rating: callers must keep the unrated branch distinct. Once a
    rating row exists, an absent can_do means yes, an absent will_do (won't-do false) means
    yes, and an absent feels_bad means no. Explicit null is treated as absent.
    """
    raw = rating or {}
    out: dict[str, bool] = {}
    for key, default in SUITABILITY_DEFAULTS.items():
        value = raw.get(key)
        out[key] = default if value is None else bool(value)
    return out


def choices(values: tuple[str, ...], labels: dict[str, str]) -> list[dict[str, str]]:
    """JSON-ready value/label options for the browser."""
    return [{"value": value, "label": labels.get(value, value.replace("_", " ").title())}
            for value in values]
