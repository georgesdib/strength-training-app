"""Deterministic prescription engine (Day B in v0).

Layering: above `rules` and `store`; below `critique` and `agents`. Nothing here calls a
model -- the LLM layer may only *explain* what this produced, or propose something the policy
engine accepts.
"""

from strength_coach.prescribe.config import Thresholds
from strength_coach.prescribe.engine import build_prescription, validate_references
from strength_coach.prescribe.models import Prescription, PrescriptionItem
from strength_coach.prescribe.templates import DayTemplate, Slot, TemplateError

__all__ = [
    "DayTemplate",
    "Prescription",
    "PrescriptionItem",
    "Slot",
    "TemplateError",
    "Thresholds",
    "build_prescription",
    "validate_references",
]
