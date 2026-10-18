"""Phase 5 acceptance on the real export.

V0-SCOPE §4.4 asks for an *executable* prescription: real loads, inside the RIR window, no
erector work on the hinge day, and a weekly spinal cost inside the cap. §4.8 asks that every
numeric rationale reference resolves. Both are asserted here against stored history.
"""

from __future__ import annotations

import pytest

from strength_coach.prescribe import build_prescription, loads, validate_references
from strength_coach.rules import RuleContext

pytestmark = pytest.mark.integration

FOR_DATE = "2026-09-15"


def test_real_export_prescription_is_executable(populated_db):
    store, _report, _shas = populated_db
    prescription = build_prescription(store.connection, for_date=FOR_DATE)

    assert prescription.executable, prescription.issues
    assert prescription.items[0].exercise_id == "trap_bar_deadlift"

    for item in prescription.items:
        assert item.load_kg is not None and item.load_kg > 0
        assert loads.is_multiple_of(item.load_kg, item.rounding_increment_kg)
        assert 2 <= item.rir_target <= 3


def test_no_direct_erector_work_on_the_hinge_day(populated_db):
    store, _report, _shas = populated_db
    prescription = build_prescription(store.connection, for_date=FOR_DATE)
    assert all(item.exercise_id != "back_extension" for item in prescription.items)


def test_every_rationale_reference_resolves(populated_db):
    store, _report, _shas = populated_db
    prescription = build_prescription(store.connection, for_date=FOR_DATE)
    context = RuleContext.from_store(store.connection, end=FOR_DATE)
    assert validate_references(prescription, context, store.connection) == []


def test_prescription_row_shape_matches_the_store(populated_db):
    store, _report, _shas = populated_db
    prescription = build_prescription(store.connection, for_date=FOR_DATE)
    rows = prescription.as_rows()
    assert len(rows) == len(prescription.items)
    assert {"exercise_id", "load_kg", "rir_target", "rationale_refs"} <= set(rows[0])
