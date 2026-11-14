"""A persisted prescription and its recorded provenance, read-only."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from strength_coach.intelligence.capabilities._common import day_period, envelope
from strength_coach.intelligence.config import IntelligenceConfig
from strength_coach.intelligence.envelope import Envelope, FactBlock
from strength_coach.intelligence.errors import IntelligenceError
from strength_coach.intelligence.registry import (
    CAPABILITIES,
    CapabilityRequest,
    CapabilitySpec,
    payload_mapping,
    reject_unknown,
)
from strength_coach.intelligence.service import ExecutionContext
from strength_coach.store import queries

CAPABILITY_NAME = "get_prescription"
CAPABILITY_VERSION = "1.0.0"
MAX_ITEMS = 40
MAX_MODIFIERS = 20

MODULES = ("strength_coach.store.queries.prescription_detail",)

ITEM_FIELDS = (
    "order_index", "exercise_id", "sets", "reps_low", "reps_high", "load_kg",
    "load_basis", "rounding_increment", "rir_target", "velocity_target", "vbt_basis",
    "rest_s", "time_cap_s", "essential", "substitution_for",
)

LIMITATIONS = (
    "A persisted prescription is the artifact the deterministic engine wrote; it is not a "
    "forecast, and an unstarted issued plan is only a preview.",
    "Recorded modifiers and rationale refs are the stored trace; absent entries are not invented.",
    "Read-only: no prescription is created, changed or approved by this capability.",
)


@dataclass(frozen=True)
class PrescriptionRequest(CapabilityRequest):
    prescription_id: str | None
    for_date: str | None
    include_provenance: bool

    @classmethod
    def parse(
        cls, payload: object, *, config: IntelligenceConfig, today: dt.date
    ) -> PrescriptionRequest:
        data = payload_mapping(payload)
        reject_unknown(data, ("prescription_id", "for_date", "include_provenance"))
        prescription_id = data.get("prescription_id")
        for_date = data.get("for_date")
        if prescription_id is not None and for_date is not None:
            raise IntelligenceError(
                "invalid_argument",
                "provide at most one of prescription_id or for_date",
                field="prescription_id",
            )
        if prescription_id is not None and (
            not isinstance(prescription_id, str) or not prescription_id.strip()
        ):
            raise IntelligenceError(
                "invalid_argument", "prescription_id must be a non-empty string",
                field="prescription_id",
            )
        if for_date is not None:
            if not isinstance(for_date, str):
                raise IntelligenceError(
                    "invalid_argument", "for_date must be YYYY-MM-DD", field="for_date"
                )
            try:
                dt.date.fromisoformat(for_date)
            except ValueError as exc:
                raise IntelligenceError(
                    "invalid_argument", "for_date must be YYYY-MM-DD", field="for_date"
                ) from exc
        include_provenance = data.get("include_provenance", True)
        if not isinstance(include_provenance, bool):
            raise IntelligenceError(
                "invalid_argument", "include_provenance must be true or false",
                field="include_provenance",
            )
        return cls(
            prescription_id=prescription_id.strip() if prescription_id else None,
            for_date=for_date,
            include_provenance=include_provenance,
        )

    def to_mapping(self) -> dict[str, object]:
        payload: dict[str, object] = {"include_provenance": self.include_provenance}
        if self.prescription_id is not None:
            payload["prescription_id"] = self.prescription_id
        if self.for_date is not None:
            payload["for_date"] = self.for_date
        return payload


def prescription(
    conn: sqlite3.Connection, request: PrescriptionRequest, execution: ExecutionContext
) -> Envelope:
    detail = queries.prescription_detail(
        conn,
        prescription_id=request.prescription_id,
        on_date=request.for_date,
    )
    if detail is None:
        return envelope(
            capability=CAPABILITY_NAME,
            version=CAPABILITY_VERSION,
            status="no_data",
            as_of=request.for_date or execution.generated_at[:10],
            period=day_period(request.for_date or execution.generated_at[:10],
                              execution.timezone),
            facts={},
            coverage={"items": 0, "modifiers": 0},
            missing=("no persisted prescription matches the request",),
            limitations=LIMITATIONS,
            execution=execution,
            arguments=request.to_mapping(),
            modules=MODULES,
        )

    items = []
    rationale: list[str] = []
    for item in detail["items"][:MAX_ITEMS]:
        entry = {field: item.get(field) for field in ITEM_FIELDS}
        if request.include_provenance:
            refs = list(item.get("rationale_refs") or [])
            entry["rationale_refs"] = refs
            rationale.extend(str(ref) for ref in refs)
        items.append(entry)
    modifiers = detail["modifiers"][:MAX_MODIFIERS]

    facts = {
        "prescription": FactBlock(
            value={
                key: detail.get(key)
                for key in (
                    "prescription_id", "for_date", "session_type", "fallback_level",
                    "approved_by", "created_at", "rule_document_version",
                    "calibration_ids", "template_digest", "policy_digest", "input_hash",
                )
            },
            basis="observed",
            method="strength_coach.store.queries.prescription_detail",
        ),
        "items": FactBlock(
            value=items,
            basis="observed",
            method="strength_coach.store.queries.prescription_detail",
            n=len(items),
            note=f"at most {MAX_ITEMS} items are returned",
        ),
        "modifiers": FactBlock(
            value=modifiers,
            basis="observed",
            method="strength_coach.store.queries.prescription_detail",
            n=len(modifiers),
            note=f"at most {MAX_MODIFIERS} modifiers are returned",
        ),
    }
    if request.include_provenance:
        facts["rule_refs"] = FactBlock(
            value=sorted(set(rationale)),
            basis="observed",
            method="strength_coach.store.queries.prescription_detail",
            n=len(set(rationale)),
        )

    truncated = (
        len(detail["items"]) > MAX_ITEMS or len(detail["modifiers"]) > MAX_MODIFIERS
    )
    return envelope(
        capability=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        status="ok",
        as_of=str(detail["for_date"]),
        period=day_period(str(detail["for_date"]), execution.timezone),
        facts=facts,
        coverage={
            "items": len(detail["items"]),
            "items_returned": len(items),
            "modifiers": len(detail["modifiers"]),
            "modifiers_returned": len(modifiers),
            "truncated": int(truncated),
        },
        missing=(("result truncated to the configured maxima",) if truncated else ()),
        limitations=LIMITATIONS,
        execution=execution,
        arguments=request.to_mapping(),
        modules=MODULES,
    )


CAPABILITIES.register(
    CapabilitySpec(
        name=CAPABILITY_NAME,
        version=CAPABILITY_VERSION,
        summary=(
            "Read-only persisted prescription: header, items, recorded modifiers and rule refs. "
            "At most one of prescription_id or for_date; neither returns the newest."
        ),
        request_type=PrescriptionRequest,
        handler=prescription,
    )
)
