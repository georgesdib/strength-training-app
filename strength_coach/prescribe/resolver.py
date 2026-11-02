"""Step 4C resolver wiring: candidate pools -> bounded beam -> final prescription.

The generator supplies eligible pools, the beam searches complete assignments, and the real
evaluator builds each final candidate through the normal prescription pipeline once. The winning
prescription is the final build; it is not rebuilt. This module does not persist anything and does
not own scheduler/UI concerns.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from decimal import Decimal
from pathlib import PurePath

from strength_coach import settings_profile
from strength_coach.prescribe import beam as beam_mod
from strength_coach.prescribe import generator
from strength_coach.prescribe.evaluator import EvaluationInputs
from strength_coach.prescribe.models import Prescription
from strength_coach.prescribe.resolver_settings import ResolverSettings

RESOLVER_STAGES = (
    "dispatch",
    "pool_generation",
    "assignment_search",
    "prescription_evaluation",
    "final_integrity",
)


class ResolverBuildError(ValueError):
    """Structured resolver failure with a stable stage and original cause."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        cause: Exception | None = None,
        beam_result=None,
        details: Mapping | None = None,
    ) -> None:
        if stage not in RESOLVER_STAGES:
            raise ValueError(f"unknown resolver failure stage {stage!r}")
        self.stage = stage
        self.message = message
        self.cause = cause
        self.beam_result = beam_result
        self.details = dict(details or {})
        super().__init__(message)

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "message": self.message,
            "cause": None if self.cause is None else {
                "type": type(self.cause).__name__,
                "message": str(self.cause),
            },
            "beam": (
                self.beam_result.as_dict() if self.beam_result is not None else None
            ),
            "details": self.details,
        }


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


def _canonical(value, *, path: str = "input"):
    """Deterministically canonicalise supported build inputs.

    Unsupported objects fail rather than being stringified with an unstable repr. Dataframes and
    known dataclasses are represented structurally; mappings are sorted by canonical key.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "__nan__"
        if math.isinf(value):
            return "__inf__" if value > 0 else "__-inf__"
        return 0.0 if value == 0 else value
    if isinstance(value, Decimal):
        return {"__type__": "decimal", "value": str(value)}
    if isinstance(value, PurePath):
        return {"__type__": "path", "name": value.name}
    if isinstance(value, (dt.date, dt.datetime)):
        return {"__type__": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, bytes):
        return {"__type__": "bytes", "hex": value.hex()}
    if isinstance(value, Mapping):
        items = [
            [_canonical(key, path=f"{path}.key"), _canonical(item, path=f"{path}.{key}")]
            for key, item in value.items()
        ]
        items.sort(key=lambda pair: json.dumps(pair[0], sort_keys=True))
        return {"__type__": "mapping", "items": items}
    if isinstance(value, (list, tuple)):
        return {
            "__type__": "sequence",
            "items": [
                _canonical(item, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ],
        }
    if isinstance(value, (set, frozenset)):
        items = [_canonical(item, path=f"{path}[]") for item in value]
        items.sort(key=lambda item: json.dumps(item, sort_keys=True))
        return {"__type__": "set", "items": items}
    module = type(value).__module__
    if module.startswith("pandas") and type(value).__name__ == "DataFrame":
        return {
            "__type__": "dataframe",
            "columns": _canonical(list(value.columns), path=f"{path}.columns"),
            "index": _canonical(list(value.index), path=f"{path}.index"),
            "data": _canonical(value.to_numpy().tolist(), path=f"{path}.data"),
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__type__": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": {
                field.name: _canonical(
                    getattr(value, field.name), path=f"{path}.{field.name}"
                )
                for field in fields(value)
            },
        }
    if module.startswith("numpy") and hasattr(value, "item"):
        return _canonical(value.item(), path=path)
    raise TypeError(f"{path}: unsupported fingerprint input {type(value).__name__}")


def prescription_input_fingerprint(
    *,
    for_date: str,
    session_type: str,
    assignment: tuple[tuple[str, str], ...],
    template_digest: str,
    policy_digest: str,
    catalogue_digest: str,
    inputs: EvaluationInputs,
    resolved,
    resolver_settings: ResolverSettings,
    candidate_pools,
) -> str:
    """Fingerprint the material build/evaluation inputs and candidate pools.

    This is an audit fingerprint of the resolver's actual inputs, not a promise that changing
    unrelated database rows cannot change a later build. Candidate pools and resolved feature
    settings are included; unordered mappings are sorted canonically.
    """
    payload = {
        "fingerprint_version": "prescription-input-v2",
        "for_date": for_date,
        "session_type": session_type,
        "assignment": assignment,
        "template_digest": template_digest,
        "policy_digest": policy_digest,
        "catalogue_digest": catalogue_digest,
        "inputs": _canonical(inputs, path="inputs"),
        "resolved_settings": _canonical(resolved, path="resolved_settings"),
        "resolver_settings": _canonical(resolver_settings, path="resolver_settings"),
        "candidate_pools": _canonical(candidate_pools, path="candidate_pools"),
    }
    body = json.dumps(
        _canonical(payload, path="fingerprint"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
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
        raise ResolverBuildError(
            "dispatch", "resolver is disabled; enable it or use the fixed path",
            details={"for_date": for_date, "session_type": session_type},
        )
    try:
        inputs.validate_for_resolver()
    except ValueError as exc:
        raise ResolverBuildError(
            "prescription_evaluation", str(exc), cause=exc,
            details={"for_date": for_date, "session_type": session_type},
        ) from exc
    try:
        pools = generator.candidate_pools(
            conn,
            for_date=for_date,
            session_type=session_type,
            policy=policy,
            settings=settings,
        )
    except Exception as exc:
        raise ResolverBuildError(
            "pool_generation", f"candidate pool generation failed: {exc}", cause=exc,
            details={"for_date": for_date, "session_type": session_type},
        ) from exc
    try:
        result = beam_mod.search(
            conn,
            for_date=for_date,
            base_template=pools.template,
            candidates=pools.pools,
            config=beam_config,
            inputs=inputs,
        )
    except Exception as exc:
        raise ResolverBuildError(
            "assignment_search", f"assignment search failed: {exc}", cause=exc,
            details={"for_date": for_date, "session_type": session_type},
        ) from exc
    if result.best is None:
        raise ResolverBuildError(
            "assignment_search",
            "resolver found no feasible assignment; " + result.reason,
            beam_result=result,
            details={"pools": [len(v) for v in pools.pools.values()]},
        )
    best = result.best
    if not best.assignment_preserved or best.session_replaced:
        raise ResolverBuildError(
            "final_integrity",
            "resolver best assignment was not preserved: "
            + (best.infeasibility_reason or "unknown reason"),
            beam_result=result,
        )
    if best.prescription.session_type != session_type:
        raise ResolverBuildError(
            "final_integrity",
            f"resolver final session type {best.prescription.session_type!r} "
            f"does not match requested {session_type!r}",
            beam_result=result,
        )

    try:
        resolved_settings = settings_profile.feature_settings(conn, for_date)
        input_hash = prescription_input_fingerprint(
            for_date=for_date,
            session_type=session_type,
            assignment=best.assignment,
            template_digest=pools.template.digest,
            policy_digest=pools.policy_digest,
            catalogue_digest=pools.catalogue_digest,
            inputs=inputs,
            resolved=resolved_settings,
            resolver_settings=settings,
            candidate_pools=pools.pools,
        )
    except Exception as exc:
        raise ResolverBuildError(
            "final_integrity", f"prescription fingerprint failed: {exc}", cause=exc,
            beam_result=result,
        ) from exc
    generated_session = {
        "for_date": for_date,
        "session_type": session_type,
        "assignment": dict(best.assignment),
        "template_digest": pools.template.digest,
        "policy_digest": pools.policy_digest,
        "catalogue_digest": pools.catalogue_digest,
        "input_hash": input_hash,
        "fingerprint_version": "prescription-input-v2",
        "fingerprint_scope": "material build/evaluation inputs and candidate pools",
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
        "fingerprint_version": "prescription-input-v2",
        "fingerprint_scope": "material build/evaluation inputs and candidate pools",
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
