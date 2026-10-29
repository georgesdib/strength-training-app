"""Canonical option payloads for the browser.

One source per vocabulary: the taxonomy supplies patterns, VBT families, muscles and exercise
ids; the injury config supplies regions; the domain constants mirror the database CHECKs. The
front end must render these options rather than inventing its own lists.
"""

from __future__ import annotations

from typing import Any

from strength_coach.domain import athlete_state
from strength_coach.features.injury_signal import InjuryConfig
from strength_coach.utils import exercises


def canonical_options() -> dict[str, Any]:
    taxonomy = exercises.taxonomy()
    config = InjuryConfig.load()
    regions = [
        {"value": rule.region, "label": rule.label}
        for rule in sorted(config.regions.values(), key=lambda item: item.label)
    ]
    entities = [
        {"value": entity_id, "label": str(entity.get("display") or entity_id)}
        for entity_id, entity in sorted(taxonomy.entities.items())
    ]
    return {
        "goals": athlete_state.choices(athlete_state.GOALS, athlete_state.GOAL_LABELS),
        "constraint_kinds": athlete_state.choices(
            athlete_state.CONSTRAINT_KINDS, athlete_state.CONSTRAINT_KIND_LABELS
        ),
        "severities": athlete_state.choices(
            athlete_state.SEVERITIES, athlete_state.SEVERITY_LABELS
        ),
        "regions": regions,
        "patterns": [{"value": value, "label": value} for value in exercises.canonical_patterns()],
        "vbt_families": [
            {"value": value, "label": value} for value in exercises.canonical_vbt_families()
        ],
        "muscles": [{"value": value, "label": value} for value in exercises.canonical_muscles()],
        "exercises": entities,
    }
