"""Canonical athlete-state vocabulary shared by the UI and the store.

The database CHECK constraints are the final authority; these tuples exist so the web layer
can render the same values instead of duplicating labels in JavaScript. Keep them in sync with
strength_coach/store/migrations/0003_athlete_state.sql (there is a test for that).
"""

from __future__ import annotations

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


def choices(values: tuple[str, ...], labels: dict[str, str]) -> list[dict[str, str]]:
    """JSON-ready value/label options for the browser."""
    return [{"value": value, "label": labels.get(value, value.replace("_", " ").title())}
            for value in values]
