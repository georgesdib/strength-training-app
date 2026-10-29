"""Part C: fatigue-informed substitution that only suggests (DEC-SELECT-12).

A suggestion is produced only when the rolling exposure signal is active, the slot is an
accessory variant slot, the candidate is comparable, covers the current lift's primary
muscles, and a rated demand dimension is strictly lower. Nothing is applied here: the
existing selection confirmation rebuilds the item from the candidate's own history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strength_coach.features import demands as demands_feature
from strength_coach.features import exposure as exposure_feature
from strength_coach.features import volume as volume_feature
from strength_coach.prescribe import selection, templates
from strength_coach.store import queries
from strength_coach.utils import exercises

# The dimension a substitution reduces first. Axial and local load are the fatigue-relevant
# ones; trunk stability and technical demand follow. systemic stays unknown for now, so it can
# never be the targeted dimension (docs/EXERCISE-DEMANDS.md).
DIMENSION_PRIORITY = ("axial_spinal", "local_muscular", "technical", "trunk_stability")

_LEVEL_RANK = {"none": 0, "low": 1, "moderate": 2, "high": 3}


@dataclass(frozen=True)
class Suggestion:
    session_type: str
    slot_id: str
    current: str
    candidate: str
    dimension: str
    current_level: str
    candidate_level: str
    comparison_class: str
    requires_confirmation: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_type": self.session_type,
            "slot_id": self.slot_id,
            "current": self.current,
            "candidate": self.candidate,
            "dimension": self.dimension,
            "current_level": self.current_level,
            "candidate_level": self.candidate_level,
            "comparison_class": self.comparison_class,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SubstitutionReport:
    on_date: str
    session_type: str
    signal: str
    ratio: float | None
    suggestions: tuple[Suggestion, ...]
    abstentions: tuple[str, ...]
    applied: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "on_date": self.on_date,
            "session_type": self.session_type,
            "signal": self.signal,
            "ratio": None if self.ratio is None else round(self.ratio, 2),
            "suggestions": [item.as_dict() for item in self.suggestions],
            "abstentions": list(self.abstentions),
            "applied": self.applied,
        }


def _target_dimension(
    catalogue: demands_feature.DemandCatalogue, current: str, candidate: str
) -> tuple[str, str, str] | None:
    """The rated dimension where the candidate is meaningfully lower, or None."""
    best: tuple[int, int, str, str, str] | None = None
    for rank, dimension in enumerate(DIMENSION_PRIORITY):
        left = catalogue.claim(current, dimension)
        right = catalogue.claim(candidate, dimension)
        if left is None or right is None or not left.rated or not right.rated:
            continue
        # A drop from low to none is real but not a fatigue-relevant reason to swap.
        if _LEVEL_RANK.get(left.level, 0) < 2:
            continue
        drop = _LEVEL_RANK.get(left.level, 0) - _LEVEL_RANK.get(right.level, 0)
        if drop <= 0:
            continue
        entry = (drop, -rank, dimension, left.level, right.level)
        if best is None or entry[:2] > best[:2]:
            best = entry
    if best is None:
        return None
    return best[2], best[3], best[4]


def _covers(candidate_muscles: Any, current_muscles: Any) -> bool:
    wanted = {str(item) for item in (current_muscles or ())}
    if not wanted:
        return True  # no declared stimulus, nothing to preserve
    have = {str(item) for item in (candidate_muscles or ())}
    return wanted <= have


def suggest(
    conn,
    on_date: str,
    session_type: str,
    *,
    selection_report: list[selection.SlotSelection] | None = None,
    exposure_report: exposure_feature.ExposureReport | None = None,
    catalogue: demands_feature.DemandCatalogue | None = None,
    config: exposure_feature.ExposureConfig | None = None,
) -> SubstitutionReport:
    """Return at most one fatigue-informed suggestion, or the reason for abstaining."""
    found = exposure_report or exposure_feature.compute(conn, on_date, config)
    catalogue = catalogue or demands_feature.load()
    abstain: list[str] = []

    profile = queries.athlete_profile(conn) or {}
    if profile.get("exposure_trim_enabled"):
        # One action per signal: when the trim is on it already acts on the high group.
        abstain.append(
            "the exposure trim is enabled; its set reduction is the single action for this signal"
        )
        return SubstitutionReport(on_date, session_type, found.signal, found.ratio, (), tuple(abstain))

    if found.signal != "high" or found.abstain:
        reason = (
            "abstained: " + ", ".join(found.abstain) if found.abstain
            else f"exposure signal is {found.signal}, no substitution"
        )
        abstain.append(reason)
        return SubstitutionReport(on_date, session_type, found.signal, found.ratio, (), tuple(abstain))

    rows = selection_report
    if rows is None:
        rows = selection.select(conn, None, on_date, session_type)
    if not rows:
        abstain.append("no multi-variant slots on this day")
        return SubstitutionReport(on_date, session_type, found.signal, found.ratio, (), tuple(abstain))

    entities = exercises.taxonomy().entities
    template = templates.SessionTemplate.load(session_type)
    essential = {slot.id: bool(slot.essential) for slot in template.slots}
    high_groups = {group.group for group in found.groups if group.signal == "high"}

    for row in rows:
        if essential.get(row.slot_id, True):
            continue  # main lifts are never substituted
        current_entity = entities.get(row.current, {})
        group = volume_feature.volume_target_key(str(current_entity.get("pattern") or ""))
        if group not in high_groups:
            continue
        for candidate in row.candidates:
            if candidate.exercise_id == row.current:
                continue
            if candidate.comparison_class not in {"A", "B"}:
                continue
            target = _target_dimension(catalogue, row.current, candidate.exercise_id)
            if target is None:
                continue
            candidate_entity = entities.get(candidate.exercise_id, {})
            if not _covers(candidate_entity.get("primary_muscles"),
                           current_entity.get("primary_muscles")):
                continue
            dimension, left, right = target
            reason = (
                f"{group} exposure is high; {candidate.exercise_id} rates {dimension} "
                f"{right} vs {left} for {row.current} (class {candidate.comparison_class}). "
                "Suggest-only: apply selection to rebuild the item from its own history."
            )
            suggestion = Suggestion(
                session_type=session_type,
                slot_id=row.slot_id,
                current=row.current,
                candidate=candidate.exercise_id,
                dimension=dimension,
                current_level=left,
                candidate_level=right,
                comparison_class=candidate.comparison_class,
                requires_confirmation=candidate.comparison_class == "B",
                reason=reason,
            )
            return SubstitutionReport(
                on_date, session_type, found.signal, found.ratio, (suggestion,), ()
            )

    abstain.append("high exposure but no candidate is comparable, covers the stimulus and is lower")
    return SubstitutionReport(on_date, session_type, found.signal, found.ratio, (), tuple(abstain))
