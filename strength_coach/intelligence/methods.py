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

from strength_coach import history, workout
from strength_coach.features import attendance, deload, progress, volume
from strength_coach.store import queries

#: Fully qualified owning functions. The key is what a FactBlock's `method` must contain.
METHODS: dict[str, Callable[..., object]] = {
    "strength_coach.features.attendance.summary": attendance.summary,
    "strength_coach.store.queries.athlete_constraints": queries.athlete_constraints,
    "strength_coach.store.queries.athlete_profile": queries.athlete_profile,
    "strength_coach.features.deload.decision": deload.decision,
    "strength_coach.features.progress.dashboard": progress.dashboard,
    "strength_coach.features.volume.compute": volume.compute,
    "strength_coach.history.detail": history.detail,
    "strength_coach.store.queries.readiness_series": queries.readiness_series,
    "strength_coach.store.queries.session_feedback": queries.session_feedback,
    "strength_coach.workout.summary": workout.summary,
}


def is_registered(method: str) -> bool:
    return method in METHODS


def registered_methods() -> tuple[str, ...]:
    return tuple(sorted(METHODS))
