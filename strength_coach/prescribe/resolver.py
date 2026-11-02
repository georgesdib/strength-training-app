"""Step 4C resolver wiring: candidate pools -> bounded beam -> final prescription.

The generator supplies eligible pools, the beam searches complete assignments, and the real
evaluator builds each final candidate through the normal prescription pipeline once. The winning
prescription is the final build; it is not rebuilt. This module does not persist anything and does
not own scheduler/UI concerns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from strength_coach.prescribe import beam as beam_mod
from strength_coach.prescribe import generator
from strength_coach.prescribe.evaluator import EvaluationInputs
from strength_coach.prescribe.models import Prescription
from strength_coach.prescribe.resolver_settings import ResolverSettings


class ResolverBuildError(ValueError):
    """Resolver generation failed before a feasible assignment could be built."""

    def __init__(self, message: str, *, beam_result=None) -> None:
        self.beam_result = beam_result
        super().__init__(message)


@dataclass(frozen=True)
class ResolvedPrescription:
    prescription: Prescription
    assignment: tuple[tuple[str, str], ...]
    template_digest: str
    policy_digest: str
    catalogue_digest: str
    input_hash: str
    beam: beam_mod.BeamResult
    generated_session: dict


def _input_hash(
    *,
    for_date: str,
    session_type: str,
    assignment: tuple[tuple[str, str], ...],
    policy_digest: str,
    catalogue_digest: str,
    inputs: EvaluationInputs,
) -> str:
    payload = {
        "for_date": for_date,
        "session_type": session_type,
        "assignment": dict(assignment),
        "policy_digest": policy_digest,
        "catalogue_digest": catalogue_digest,
        "top_set_requested": inputs.top_set_requested,
        "technique_throttle": inputs.technique_throttle,
        "minimum_session": inputs.minimum_session,
        "deload": inputs.deload_decision is not None,
        "projected_sessions": inputs.projected_sessions,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_resolved(
    conn,
    *,
    for_date: str,
    session_type: str,
    inputs: EvaluationInputs,
    policy=None,
    settings: ResolverSettings | None = None,
    beam_config: beam_mod.BeamConfig | None = None,
) -> ResolvedPrescription:
    """Run the generator/beam/evaluator path and return the already-built final prescription."""
    settings = settings or ResolverSettings.load(conn, for_date)
    if not settings.enabled:
        raise ResolverBuildError("resolver is disabled")
    inputs.validate_for_resolver()
    pools = generator.candidate_pools(
        conn,
        for_date=for_date,
        session_type=session_type,
        policy=policy,
        settings=settings,
    )
    result = beam_mod.search(
        conn,
        for_date=for_date,
        base_template=pools.template,
        candidates=pools.pools,
        config=beam_config,
        inputs=inputs,
    )
    if result.best is None:
        raise ResolverBuildError(
            "resolver found no feasible assignment; " + result.reason,
            beam_result=result,
        )
    best = result.best
    if not best.assignment_preserved or best.session_replaced:
        raise ResolverBuildError(
            "resolver best assignment was not preserved: "
            + (best.infeasibility_reason or "unknown reason"),
            beam_result=result,
        )
    if best.prescription.session_type != session_type:
        raise ResolverBuildError(
            f"resolver final session type {best.prescription.session_type!r} "
            f"does not match requested {session_type!r}",
            beam_result=result,
        )

    input_hash = _input_hash(
        for_date=for_date,
        session_type=session_type,
        assignment=best.assignment,
        policy_digest=pools.policy_digest,
        catalogue_digest=pools.catalogue_digest,
        inputs=inputs,
    )
    generated_session = {
        "for_date": for_date,
        "session_type": session_type,
        "assignment": dict(best.assignment),
        "template_digest": pools.template.digest,
        "policy_digest": pools.policy_digest,
        "catalogue_digest": pools.catalogue_digest,
        "input_hash": input_hash,
        "beam": result.as_dict(),
        "evaluator": best.as_dict(),
        "top_set": best.prescription.notes.get("top_set"),
    }
    metadata = {
        "assignment": dict(best.assignment),
        "template_digest": pools.template.digest,
        "policy_digest": pools.policy_digest,
        "catalogue_digest": pools.catalogue_digest,
        "input_hash": input_hash,
        "beam": result.as_dict(),
        "evaluator": best.as_dict(),
        "top_set": best.prescription.notes.get("top_set"),
        "generated_session": generated_session,
    }
    notes = dict(best.prescription.notes)
    notes["resolver"] = metadata
    prescription = replace(best.prescription, notes=notes)
    return ResolvedPrescription(
        prescription=prescription,
        assignment=best.assignment,
        template_digest=pools.template.digest,
        policy_digest=pools.policy_digest,
        catalogue_digest=pools.catalogue_digest,
        input_hash=input_hash,
        beam=result,
        generated_session=generated_session,
    )
