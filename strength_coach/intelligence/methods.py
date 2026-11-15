"""Allow-list of owning functions a capability fact may name.

Every fact in a response must say which function computed it (contract §3.2). Without a fixed
allow-list a capability could name a module that does not exist, or invent a plausible-sounding
method, and the claim would look authoritative. This module is that allow-list and nothing more:
it does not dispatch, wrap or cache calls. Capabilities call the real functions directly.

Adding an INT-2 capability means adding its owner here in the same change, which is the point:
a new method name is a reviewable event.
"""

from __future__ import annotations

from collections.abc import Callable

from strength_coach import history, settings_profile, workout
from strength_coach.features import (
    adherence_analytics,
    attendance,
    breaks,
    deload,
    exercise_history,
    observations,
    progress,
    readiness_score,
    regime_change,
    strength_trend,
    vbt_performance,
    volume,
)
from strength_coach.store import queries
from strength_coach.utils import exercises

#: Fully qualified owning functions. The key is what a FactBlock's `method` must contain.
METHODS: dict[str, Callable[..., object]] = {
    "strength_coach.features.attendance.summary": attendance.summary,
    "strength_coach.store.queries.athlete_constraints": queries.athlete_constraints,
    "strength_coach.store.queries.athlete_profile": queries.athlete_profile,
    "strength_coach.features.deload.decision": deload.decision,
    "strength_coach.features.progress.dashboard": progress.dashboard,
    "strength_coach.features.volume.compute": volume.compute,
    "strength_coach.history.detail": history.detail,
    "strength_coach.history.list_sessions": history.list_sessions,
    "strength_coach.store.queries.readiness_series": queries.readiness_series,
    "strength_coach.store.queries.session_feedback": queries.session_feedback,
    "strength_coach.workout.summary": workout.summary,
    "strength_coach.features.adherence_analytics.analytics": adherence_analytics.analytics,
    "strength_coach.features.observations.analyse": observations.analyse,
    "strength_coach.features.exercise_history.history": exercise_history.history,
    "strength_coach.features.readiness_score.compute": readiness_score.compute,
    "strength_coach.features.regime_change.detect": regime_change.detect,
    "strength_coach.features.strength_trend.observations": strength_trend.observations,
    "strength_coach.features.strength_trend.rolling_median": strength_trend.rolling_median,
    "strength_coach.features.strength_trend.series_breaks": strength_trend.series_breaks,
    "strength_coach.features.strength_trend.summarize": strength_trend.summarize,
    "strength_coach.features.vbt_performance.analyse": vbt_performance.analyse,
    "strength_coach.features.breaks.all_breaks": breaks.all_breaks,
    "strength_coach.features.breaks.active_on": breaks.active_on,
    "strength_coach.settings_profile.state": settings_profile.state,
    "strength_coach.store.queries.prescription_detail": queries.prescription_detail,
    "strength_coach.utils.exercises.taxonomy": exercises.taxonomy,
    "strength_coach.utils.exercises.canonical_id": exercises.canonical_id,
}


def is_registered(method: str) -> bool:
    return method in METHODS


def registered_methods() -> tuple[str, ...]:
    return tuple(sorted(METHODS))
