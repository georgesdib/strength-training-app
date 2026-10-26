"""Persist a UI-built plan as the same prescription artifact the CLI stores.

The UI preview stays read-only. The artifact is written when the athlete commits by starting a
workout, so repeated previews do not create duplicate prescriptions.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping

from strength_coach import __version__
from strength_coach.features import prescription_provenance
from strength_coach.prescribe import volume_budget
from strength_coach.store import repositories


def _rows(plan: Mapping[str, Any]) -> list[dict]:
    rows = []
    for index, item in enumerate(plan.get("items") or []):
        rows.append({
            "order_index": int(item.get("order_index", index)),
            "exercise_id": str(item["exercise_id"]),
            "sets": int(item["sets"]),
            "reps_low": item.get("reps_low"),
            "reps_high": item.get("reps_high"),
            "load_kg": item.get("load_kg"),
            "load_basis": str(item.get("load_basis") or "unknown"),
            "rounding_increment": item.get("rounding_increment_kg"),
            "rir_target": item.get("rir_target"),
            "velocity_target": item.get("velocity_target"),
            "vbt_basis": item.get("vbt_basis"),
            "e1rm_source_sets": item.get("e1rm_source_sets"),
            "rest_s": item.get("rest_s"),
            "time_cap_s": item.get("time_cap_s"),
            "essential": bool(item.get("essential", True)),
            "rationale_refs": list(item.get("refs") or ()),
            "substitution_for": item.get("substitution_for"),
            "warmup": list(item.get("warmup") or ()),
        })
    return rows


def store_plan(conn, plan: Mapping[str, Any], *, approved_by: str = "deterministic") -> str:
    """Append a prescription for a committed UI plan and return its id.

    Caller owns the transaction: the workout start and this artifact must commit or roll back
    together.
    """
    if not isinstance(plan, Mapping) or not plan.get("items"):
        raise ValueError("plan.items must be a non-empty list")
    payload = json.dumps(plan, sort_keys=True, default=str)
    run = repositories.start_run(
        conn,
        input_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        code_version=__version__,
        window_end=str(plan.get("for_date") or "") or None,
    )
    prescription_id = uuid.uuid4().hex
    repositories.append_prescription(
        conn,
        prescription_id=prescription_id,
        run_id=run.run_id,
        for_date=str(plan["for_date"]),
        session_type=str(plan["session_type"]),
        fallback_level=str(plan.get("fallback_level") or "full"),
        rule_document_version=str(plan.get("rule_document_version") or "unknown"),
        calibration_ids=tuple(plan.get("calibration_ids") or ()),
        approved_by=approved_by,
        items=_rows(plan),
    )
    volume_budget.record_exemptions(
        conn, prescription_id=prescription_id,
        effective_on=str(plan["for_date"]),
        session_type=str(plan["session_type"]),
        items=plan.get("items") or (),
    )
    prescription_provenance.record_plan(conn, prescription_id, plan)
    return prescription_id