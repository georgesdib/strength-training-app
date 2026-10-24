"""Extract durable modifier provenance from a built prescription.

This does not decide whether a modifier was correct. It records which modifiers changed the
stored prescription, for the outcome review and later audit.
"""

from __future__ import annotations

from typing import Iterable

from strength_coach.store import repositories

MODIFIER_KEYS = (
    "MOD-FAT-001", "MOD-GAP-001", "MOD-DELOAD-001",
    "MOD-VOL-001", "MOD-VOL-002", "MOD-SELECT-001", "MOD-MIN-001",
)


def extract(prescription) -> list[tuple[str, dict]]:
    """Return (modifier_key, detail) pairs for modifiers actually cited by items/notes."""
    refs: set[str] = set()
    changed: dict[str, list[str]] = {}
    for item in prescription.items:
        for ref in item.rationale_refs:
            if ref in MODIFIER_KEYS:
                refs.add(ref)
                changed.setdefault(ref, []).append(item.exercise_id)
    out: list[tuple[str, dict]] = []
    for key in MODIFIER_KEYS:
        if key not in refs:
            continue
        detail: dict = {"items": sorted(set(changed.get(key, ())))}
        notes = prescription.notes or {}
        if key == "MOD-FAT-001":
            detail["readiness_trigger"] = notes.get("fatigue_trigger")
            detail["per_lift_readiness"] = notes.get("per_lift_readiness")
        elif key == "MOD-GAP-001":
            detail["gap_days"] = notes.get("gap_days")
            detail["gap_band"] = notes.get("gap_band")
        elif key == "MOD-DELOAD-001":
            detail["deload"] = notes.get("deload")
        elif key in {"MOD-VOL-001", "MOD-VOL-002"}:
            detail["volume_management"] = notes.get("volume_management")
        elif key == "MOD-SELECT-001":
            detail["selection"] = notes.get("selection")
        elif key == "MOD-MIN-001":
            detail["minimum_session"] = notes.get("minimum_session")
        out.append((key, detail))
    return out


def extract_plan(plan: dict) -> list[tuple[str, dict]]:
    """Same provenance extraction for the serialised UI/plan form."""
    refs: set[str] = set()
    changed: dict[str, list[str]] = {}
    for item in plan.get("items") or []:
        exercise_id = str(item.get("exercise_id"))
        for ref in item.get("refs") or ():
            if ref in MODIFIER_KEYS:
                refs.add(str(ref))
                changed.setdefault(str(ref), []).append(exercise_id)
    notes = plan.get("notes") or {}
    out: list[tuple[str, dict]] = []
    for key in MODIFIER_KEYS:
        if key not in refs:
            continue
        detail: dict = {"items": sorted(set(changed.get(key, ())))}
        if key == "MOD-FAT-001":
            detail["readiness_trigger"] = notes.get("fatigue_trigger")
            detail["per_lift_readiness"] = notes.get("per_lift_readiness")
        elif key == "MOD-GAP-001":
            detail["gap_days"] = notes.get("gap_days")
            detail["gap_band"] = notes.get("gap_band")
        elif key == "MOD-DELOAD-001":
            detail["deload"] = notes.get("deload")
        elif key in {"MOD-VOL-001", "MOD-VOL-002"}:
            detail["volume_management"] = notes.get("volume_management")
        elif key == "MOD-SELECT-001":
            detail["selection"] = notes.get("selection")
        elif key == "MOD-MIN-001":
            detail["minimum_session"] = notes.get("minimum_session")
        out.append((key, detail))
    return out


def record_plan(conn, prescription_id: str, plan: dict) -> int:
    """Append provenance for a serialised plan, without rebuilding the engine."""
    count = 0
    for key, detail in extract_plan(plan):
        repositories.append_prescription_modifier(
            conn,
            prescription_id=prescription_id,
            modifier_key=key,
            applied_on=str(plan["for_date"]),
            detail=detail,
        )
        count += 1
    return count


def record(conn, prescription_id: str, prescription) -> int:
    """Append provenance rows for the modifiers already reflected in the prescription."""
    count = 0
    for key, detail in extract(prescription):
        repositories.append_prescription_modifier(
            conn,
            prescription_id=prescription_id,
            modifier_key=key,
            applied_on=prescription.for_date,
            detail=detail,
        )
        count += 1
    return count
