"""WP6 role-quality hierarchy: deterministic classes, neutral missing data, no composite."""

from __future__ import annotations

from strength_coach.prescribe import role_quality, templates
from strength_coach.prescribe.models import Prescription, PrescriptionItem
from strength_coach.store import db


def _item(order, slot, exercise, *, intensity=None):
    return PrescriptionItem(
        order_index=order,
        exercise_id=exercise,
        sets=slot.sets,
        reps_low=slot.reps_low,
        reps_high=slot.reps_high,
        load_kg=100.0,
        load_basis="external",
        rounding_increment_kg=2.5,
        rir_target=slot.rir_low,
        rest_s=slot.rest_s,
        essential=slot.essential,
        intensity=intensity,
        e1rm_quality="ok" if intensity is not None else None,
        e1rm_age_days=7 if intensity is not None else None,
    )


def _snapshot(*, band_penalty=0, intent_penalty=0):
    base = templates.SessionTemplate.load("squat")
    assignment = {slot.id: slot.exercises[0] for slot in base.slots}
    items = tuple(
        _item(
            index,
            slot,
            slot.exercises[0],
            intensity=0.85 if index == 0 else None,
        )
        for index, slot in enumerate(base.slots)
    )
    prescription = Prescription(
        for_date="2024-01-15",
        session_type=base.session_type,
        fallback_level="none",
        rule_document_version="test",
        items=items,
        notes={
            "volume_panel": {
                "band": {"low": 10.0, "high": 20.0},
                "after": 15.0,
                "groups": {},
            }
        },
    )
    with db.Store(":memory:") as store:
        return role_quality.snapshot(
            conn=store.connection,
            for_date="2024-01-15",
            base=base,
            assignment=assignment,
            prescription=prescription,
            band_penalty=band_penalty,
            intent_penalty=intent_penalty,
        )


def test_role_quality_snapshot_has_roles_and_a_lexicographic_vector() -> None:
    snapshot = _snapshot()
    assert snapshot.roles["main"]
    assert snapshot.roles["secondary"]
    assert snapshot.vector[0:2] == (0, 0)
    assert len(snapshot.vector) > 2
    assert snapshot.as_dict()["version"] == role_quality.VERSION


def test_band_and_intent_penalties_change_the_first_vector_positions() -> None:
    clean = _snapshot()
    gated = _snapshot(band_penalty=1, intent_penalty=1)
    assert gated.vector[:2] == (1, 1)
    assert gated.vector[:2] != clean.vector[:2]
    assert clean.vector[2:] == gated.vector[2:]


def test_missing_exposure_is_neutral_not_zero() -> None:
    base = templates.SessionTemplate.load("squat")
    assignment = {slot.id: slot.exercises[0] for slot in base.slots}
    items = tuple(
        _item(index, slot, slot.exercises[0], intensity=None)
        for index, slot in enumerate(base.slots)
    )
    prescription = Prescription(
        for_date="2024-01-15",
        session_type=base.session_type,
        fallback_level="none",
        rule_document_version="test",
        items=items,
    )
    with db.Store(":memory:") as store:
        snapshot = role_quality.snapshot(
            conn=store.connection,
            for_date="2024-01-15",
            base=base,
            assignment=assignment,
            prescription=prescription,
            band_penalty=0,
            intent_penalty=0,
        )
    main = snapshot.roles["main"][0]["classes"]
    assert main["exposure"] == 1
    assert "missing_item" not in snapshot.limitations

