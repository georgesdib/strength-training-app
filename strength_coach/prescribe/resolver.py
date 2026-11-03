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
from strength_coach.prescribe import generated as generated_snapshot
from strength_coach.prescribe import generator, resolver_policy
from strength_coach.prescribe.evaluator import EvaluationInputs, evaluate_assignment
from strength_coach.prescribe.models import Prescription
from strength_coach.prescribe.resolver_settings import ResolverSettings
from strength_coach.utils import exercises


class _PrescriptionEvaluationError(Exception):
    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__(str(cause))


def _stage_evaluator(
    conn, *, for_date, base_template, assignment, candidate_pools, inputs=None, **kwargs
):
    try:
        return evaluate_assignment(
            conn,
            for_date=for_date,
            base_template=base_template,
            assignment=assignment,
            candidate_pools=candidate_pools,
            inputs=inputs,
            **kwargs,
        )
    except Exception as exc:
        raise _PrescriptionEvaluationError(exc) from exc


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
    pools: generator.CandidatePools
    generated_session: dict


def _dtype_info(dtype) -> dict:
    info = {
        "type": f"{type(dtype).__module__}.{type(dtype).__qualname__}",
        "str": str(dtype),
    }
    if hasattr(dtype, "categories"):
        info["categories"] = _canonical(
            list(dtype.categories), path="dtype.categories"
        )
        info["ordered"] = bool(getattr(dtype, "ordered", False))
    return info


def _canonical(value, *, path: str = "input"):
    """Deterministically canonicalise supported build inputs.

    Unsupported objects fail rather than being stringified with an unstable repr. Dataframes and
    known dataclasses are represented structurally; mappings are sorted by canonical key.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"__type__": "float", "value": "nan"}
        if math.isinf(value):
            return {
                "__type__": "float",
                "value": "inf" if value > 0 else "-inf",
            }
        if value == 0:
            return (
                {"__type__": "float", "value": "-0.0"}
                if math.copysign(1.0, value) < 0
                else 0.0
            )
        return value
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
    if module.startswith("pandas") and type(value).__name__ in {"NAType", "NaTType"}:
        return {"__type__": "pandas_missing", "name": type(value).__name__}
    if module.startswith("pandas") and type(value).__name__ == "DataFrame":
        return {
            "__type__": "dataframe",
            "columns": [
                {
                    "name": _canonical(column, path=f"{path}.columns[{index}]"),
                    "dtype": _dtype_info(value.columns.dtype),
                }
                for index, column in enumerate(value.columns)
            ],
            "column_names": _canonical(
                list(value.columns.names), path=f"{path}.column_names"
            ),
            "index": {
                "type": f"{type(value.index).__module__}.{type(value.index).__qualname__}",
                "dtype": _dtype_info(value.index.dtype),
                "names": _canonical(list(value.index.names), path=f"{path}.index.names"),
                "values": _canonical(
                    list(value.index), path=f"{path}.index.values"
                ),
            },
            "dtypes": [
                _dtype_info(dtype) for dtype in value.dtypes
            ],
            "data": _canonical(value.to_numpy().tolist(), path=f"{path}.data"),
            "attrs": _canonical(value.attrs, path=f"{path}.attrs"),
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


def _snapshot_slots(pools, assignment: tuple[tuple[str, str], ...]) -> list[dict]:
    selected = dict(assignment)
    return [
        {
            "id": slot.id,
            "exercise_id": selected.get(slot.id),
            "sets": slot.sets,
            "reps_low": slot.reps_low,
            "reps_high": slot.reps_high,
            "rir_low": slot.rir_low,
            "rir_high": slot.rir_high,
            "rest_s": slot.rest_s,
            "essential": slot.essential,
            "load_source": slot.load_source,
            "power": slot.power,
            "quality_stop": slot.quality_stop,
        }
        for slot in pools.template.slots
    ]


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
    beam_config: beam_mod.BeamConfig | None = None,
) -> str:
    """Fingerprint the material build/evaluation inputs and candidate pools.

    This is an audit fingerprint of the resolver's actual inputs, not a promise that changing
    unrelated database rows cannot change a later build. Candidate pools and resolved feature
    settings are included; unordered mappings are sorted canonically.
    """
    payload = {
        "fingerprint_version": "prescription-input-v3",
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
        "beam_config": _canonical(
            beam_config or beam_mod.BeamConfig(), path="beam_config"
        ),
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
    effective_beam_config = beam_config or beam_mod.BeamConfig()
    policy = policy or resolver_policy.ResolverPolicy.load()
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
            config=effective_beam_config,
            structure=beam_mod.BeamStructure(
                required_patterns=pools.required_patterns,
                patterns_by_slot=pools.candidate_patterns,
            ),
            inputs=inputs,
            evaluator=_stage_evaluator,
        )
    except _PrescriptionEvaluationError as exc:
        raise ResolverBuildError(
            "prescription_evaluation",
            f"prescription evaluation failed: {exc.cause}",
            cause=exc.cause,
            details={"for_date": for_date, "session_type": session_type},
        ) from exc
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
    structural = generator.required_pattern_violations(
        pools.template,
        dict(best.assignment),
        policy,
        exercises.taxonomy().entities,
    )
    if structural:
        raise ResolverBuildError(
            "final_integrity",
            "resolver assignment violates required patterns: " + "; ".join(structural),
            beam_result=result,
        )
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
            beam_config=effective_beam_config,
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
        "assignment_order": [list(pair) for pair in best.assignment],
        "slots": _snapshot_slots(pools, best.assignment),
        "template_digest": pools.template.digest,
        "policy_digest": pools.policy_digest,
        "catalogue_digest": pools.catalogue_digest,
        "input_hash": input_hash,
        "fingerprint_version": "prescription-input-v3",
        "fingerprint_scope": "material build/evaluation inputs, candidate pools and beam config",
        "beam_config": {
            "width": effective_beam_config.width,
            "max_candidates_per_slot": effective_beam_config.max_candidates_per_slot,
            "max_full_evaluations": effective_beam_config.max_full_evaluations,
        },
        "candidate_pools": {slot: list(pool) for slot, pool in pools.pools.items()},
        "beam": result.as_dict(),
        "evaluator": best.as_dict(),
        "top_set": best.prescription.notes.get("top_set"),
    }
    try:
        generated_snapshot.validate_snapshot(generated_session)
    except generated_snapshot.SnapshotError as exc:
        raise ResolverBuildError(
            "final_integrity",
            f"generated-session snapshot is invalid: {exc}",
            beam_result=result,
        ) from exc
    metadata = {
        "assignment": dict(best.assignment),
        "assignment_order": [list(pair) for pair in best.assignment],
        "slots": _snapshot_slots(pools, best.assignment),
        "template_digest": pools.template.digest,
        "policy_digest": pools.policy_digest,
        "catalogue_digest": pools.catalogue_digest,
        "input_hash": input_hash,
        "fingerprint_version": "prescription-input-v3",
        "fingerprint_scope": "material build/evaluation inputs, candidate pools and beam config",
        "beam_config": {
            "width": effective_beam_config.width,
            "max_candidates_per_slot": effective_beam_config.max_candidates_per_slot,
            "max_full_evaluations": effective_beam_config.max_full_evaluations,
        },
        "candidate_pools": {slot: list(pool) for slot, pool in pools.pools.items()},
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
        pools=pools,
        generated_session=generated_session,
    )
