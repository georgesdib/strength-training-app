"""Session detail: one completed workout, read-only.

Two sources, chosen by the identifier the caller already has:

* a workout id (or a session id that resolves to a workout) -> the existing completed-workout
  report, including its real evidence array and at most one deterministic observation;
* an imported session with no workout row -> the stored session outline, its sets and feedback,
  with adherence/VBT reported as unavailable rather than recomputed.

The capability returns an explicit field allowlist. Notes, symptoms, form ratings and other
health fields are never selected, even though the underlying payloads contain them.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach import history, workout
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import Envelope, FactBlock, Period, Privacy
from strength_coach.intelligence.errors import IntelligenceError
from strength_coach.intelligence.registry import (
    CAPABILITIES,
    CapabilityRequest,
    CapabilitySpec,
    payload_mapping,
    reject_unknown,
)
from strength_coach.intelligence.service import ExecutionContext

CAPABILITY_NAME = "get_session_details"
CAPABILITY_VERSION = "1.0.0"
MAX_SETS = 100

MODULES = (
    "strength_coach.workout",
    "strength_coach.history",
    "strength_coach.store.queries",
)

UNITS = {"load": "kg", "velocity": "m/s", "duration": "min", "ratio": "ratio"}

FEEDBACK_KEYS = (
    "srpe",
    "duration_min",
    "duration_source",
    "duration_basis",
    "session_load_au",
    "session_load_status",
    "productivity",
    "recorded_at",
)

SET_KEYS = (
    "set_id",
    "exercise_id",
    "load_kg",
    "reps",
    "rir",
    "velocity_mps",
    "prescription_item_index",
    "vbt_mean",
)

LIMITATIONS = (
    "Read-only session detail; no prescription or workout is changed.",
    "Adherence compares the frozen plan with performed sets; unattributed sets are reported, "
    "not inferred.",
    "Free-text notes, symptoms and form ratings are excluded from this capability.",
)


@dataclass(frozen=True)
class SessionRequest(CapabilityRequest):
    workout_id: str | None
    session_id: str | None
    include_ratios: bool

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> SessionRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("workout_id", "session_id", "include_ratios"))
        workout_id = _identifier(data.get("workout_id"), "workout_id")
        session_id = _identifier(data.get("session_id"), "session_id")
        if (workout_id is None) == (session_id is None):
            raise IntelligenceError(
                "invalid_argument",
                "exactly one of workout_id or session_id is required",
                field="workout_id" if workout_id is not None else "session_id",
            )
        include_ratios = data.get("include_ratios", False)
        if not isinstance(include_ratios, bool):
            raise IntelligenceError(
                "invalid_argument", "include_ratios must be true or false", field="include_ratios"
            )
        return cls(
            workout_id=workout_id,
            session_id=session_id,
            include_ratios=include_ratios,
        )

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {"include_ratios": self.include_ratios}
        if self.workout_id is not None:
            payload["workout_id"] = self.workout_id
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        return payload


def _identifier(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise IntelligenceError(
            "invalid_argument", f"{field} must be a non-empty identifier", field=field
        )
    return value.strip()


def _pick(value: object, keys: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: value.get(key) for key in keys if key in value}


def _section(value: object, name: str) -> object:
    """Return a structured section, rejecting a payload the contract cannot represent."""
    if value is None:
        return None
    if not isinstance(value, (dict, list)):
        raise IntelligenceError("unavailable", f"{name} is not available for this session")
    return value


def _summary(conn, workout_id: str, *, include_ratios: bool) -> dict:
    try:
        return workout.summary(conn, workout_id, include_ratios=include_ratios)
    except workout.WorkoutNotCompleted as exc:
        # WorkoutNotCompleted subclasses ValueError, so it must be caught first.
        raise IntelligenceError(
            "invalid_state", "workout must be completed before details are available",
            field="workout_id",
        ) from exc
    except ValueError as exc:
        raise IntelligenceError(
            "not_found", "no such workout", field="workout_id"
        ) from exc


def _from_workout(
    conn, request: SessionRequest, execution: ExecutionContext, workout_id: str
) -> Envelope:
    summary = _summary(conn, workout_id, include_ratios=request.include_ratios)
    day = str(summary["for_date"])
    feedback = _pick(summary.get("feedback"), FEEDBACK_KEYS)
    adherence = summary.get("adherence")
    vbt = summary.get("vbt")
    observation = summary.get("observation")
    evidence = list(summary.get("evidence") or ())
    observations: list[dict] = []
    if isinstance(observation, dict):
        # The summary embeds the owning evidence item inside the observation. Promote it into
        # the envelope's evidence array (never inventing one) and keep the observation to its
        # contract keys.
        embedded = observation.get("evidence")
        if isinstance(embedded, dict):
            known = {item.get("evidence_id") for item in evidence}
            if embedded.get("evidence_id") not in known:
                evidence.append(embedded)
        observations.append({
            key: observation.get(key)
            for key in ("family", "text", "gate", "n", "evidence_id", "limitations")
        })

    missing: list[str] = []
    if feedback.get("srpe") is None:
        missing.append("session RPE was not recorded")
    if isinstance(adherence, dict) and adherence.get("status") != "available":
        missing.append("prescription adherence is unavailable for this session")
    if isinstance(vbt, dict) and vbt.get("status") != "available":
        missing.append("VBT analysis is unavailable for this session")

    facts = {
        "session": FactBlock(
            value={
                "date": day,
                "session_type": summary.get("session_type"),
                "status": summary.get("status"),
                "source": "workout",
            },
            basis="observed",
            method="strength_coach.workout.summary",
        ),
        "strength": FactBlock(
            value=_section(summary.get("strength"), "strength"),
            basis="derived",
            method="strength_coach.workout.summary",
        ),
        "dose": FactBlock(
            value=_section(summary.get("dose"), "dose"),
            basis="derived",
            method="strength_coach.workout.summary",
        ),
        "adherence": FactBlock(
            value=_section(adherence, "adherence"),
            basis="derived",
            method="strength_coach.workout.summary",
        ),
        "vbt": FactBlock(
            value=_section(vbt, "vbt"),
            basis="derived",
            method="strength_coach.workout.summary",
        ),
        "feedback": FactBlock(
            value=feedback,
            basis="observed",
            method="strength_coach.workout.summary",
        ),
        "quality": FactBlock(
            value=_section(summary.get("quality"), "quality"),
            basis="derived",
            method="strength_coach.workout.summary",
        ),
    }

    return Envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok",
        as_of=day,
        period=Period(start=day, end=day, days=1, weeks=None, timezone=execution.timezone),
        units=UNITS,
        facts=facts,
        evidence=tuple(evidence),
        observations=tuple(observations),
        coverage={
            "sets_considered": _set_count(summary),
            "evidence_items": len(evidence),
            "observations": len(observations),
        },
        missing=tuple(missing),
        limitations=LIMITATIONS,
        quality_flags=tuple(
            str(flag)
            for flag in ((summary.get("quality") or {}).get("flags") or ())
            if isinstance(flag, str)
        ),
        privacy=_privacy(),
        provenance=execution.provenance(
            capability=CAPABILITY_NAME,
            version=CAPABILITY_VERSION,
            arguments=request.to_mapping(),
            modules=MODULES,
        ),
        generated_at=execution.generated_at,
    )


def _set_count(summary: dict) -> int | None:
    dose = summary.get("dose") or {}
    total = 0
    found = False
    for entry in dose.get("per_exercise") or ():
        sets = entry.get("sets")
        if isinstance(sets, int):
            total += sets
            found = True
    return total if found else None


def _from_imported(
    conn,
    request: SessionRequest,
    execution: ExecutionContext,
    session_id: str,
    *,
    detail: dict | None = None,
) -> Envelope:
    if detail is None:
        try:
            detail = history.detail(conn, session_id)
        except ValueError as exc:
            raise IntelligenceError(
                "not_found", "no such session", field="session_id"
            ) from exc
    day = str(detail["occurred_on"])
    voided = bool(detail.get("voided"))
    all_sets = detail.get("sets") or []
    sets = [_pick(item, SET_KEYS) for item in all_sets[:MAX_SETS]]
    feedback = _pick(detail.get("feedback"), FEEDBACK_KEYS)
    adherence = _pick(detail.get("adherence"), ("status", "reason"))
    vbt = _pick(detail.get("vbt"), ("status", "reason"))

    missing: list[str] = []
    if voided:
        missing.append("session is voided")
    if not feedback:
        missing.append("no session feedback recorded")
    if len(all_sets) > MAX_SETS:
        missing.append(f"sets truncated to the first {MAX_SETS}")
    if adherence.get("status") != "available":
        missing.append("prescription adherence is unavailable for an imported session")
    if vbt.get("status") != "available":
        missing.append("VBT analysis is unavailable for an imported session")

    facts = {
        "session": FactBlock(
            value={
                "date": day,
                "session_type": detail.get("session_type"),
                "status": "imported",
                "source": "imported",
                "duration_min": detail.get("duration_min"),
                "duration_basis": detail.get("duration_basis"),
            },
            basis="observed",
            method="strength_coach.history.detail",
        ),
        "sets": FactBlock(
            value=sets,
            basis="observed",
            method="strength_coach.history.detail",
            n=len(sets),
        ),
        "adherence": FactBlock(
            value=adherence,
            basis="derived",
            method="strength_coach.history.detail",
        ),
        "vbt": FactBlock(
            value=vbt,
            basis="derived",
            method="strength_coach.history.detail",
        ),
        "feedback": FactBlock(
            value=feedback,
            basis="observed",
            method="strength_coach.store.queries.session_feedback",
        ),
    }

    return Envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="no_data" if voided else "ok",
        as_of=day,
        period=Period(start=day, end=day, days=1, weeks=None, timezone=execution.timezone),
        units=UNITS,
        facts=facts,
        evidence=(),
        observations=(),
        coverage={
            "sets_considered": len(all_sets),
            "sets_returned": len(sets),
            "truncated": int(len(all_sets) > MAX_SETS),
        },
        missing=tuple(missing),
        limitations=LIMITATIONS
        + ("Imported sessions have no measured duration or plan adherence.",),
        quality_flags=(),
        privacy=_privacy(),
        provenance=execution.provenance(
            capability=CAPABILITY_NAME,
            version=CAPABILITY_VERSION,
            arguments=request.to_mapping(),
            modules=MODULES,
        ),
        generated_at=execution.generated_at,
    )


def _privacy() -> Privacy:
    return Privacy(
        classification="training",
        excluded_fields=(
            "session notes",
            "symptom attributions",
            "post-lift form ratings",
            "body measurements",
        ),
        redactions=(
            "feedback reduced to effort, duration and productivity",
        ),
    )


def session_details(
    conn: sqlite3.Connection, request: SessionRequest, execution: ExecutionContext
) -> Envelope:
    if request.workout_id is not None:
        return _from_workout(conn, request, execution, request.workout_id)

    assert request.session_id is not None
    try:
        detail = history.detail(conn, request.session_id)
    except ValueError as exc:
        raise IntelligenceError(
            "not_found", "no such session", field="session_id"
        ) from exc
    linked = detail.get("workout_id")
    if linked:
        # summary() maps an active or abandoned workout to invalid_state; a session row with a
        # workout id is the same session, so there is no second resolution rule here.
        return _from_workout(conn, request, execution, str(linked))
    return _from_imported(conn, request, execution, request.session_id, detail=detail)


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only detail for one completed or imported session: strength, dose, adherence, "
            "VBT, feedback and quality. Notes, symptoms and form ratings are excluded."
        ),
        request_type=SessionRequest,
        handler=session_details,
    )
)
