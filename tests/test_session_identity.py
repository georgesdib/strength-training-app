"""9c-2 session identity, startability and derived-session review."""

from __future__ import annotations

from strength_coach import workout
from strength_coach.critique import facts as facts_mod
from strength_coach.prescribe import session_identity
from strength_coach.prescribe.models import Prescription
from strength_coach.store import db, queries
from strength_coach.web.server import prescription_dict

READINESS = {
    "sleep": 3, "energy": 3, "mood": 3, "soreness": 3,
    "stress": 3, "nutrition": 3, "hydration": 3,
}


def test_derived_session_labels_and_exposure():
    assert session_identity.label("volume_fill_squat") == "Volume fill (squat omitted)"
    assert session_identity.label("volume_fill_bench_hinge") == (
        "Volume fill (bench hinge omitted)"
    )
    assert session_identity.label("technique") == "Technique (week complete)"
    assert session_identity.original_type("volume_fill_hinge") == "hinge"
    assert session_identity.original_type("technique") is None
    assert session_identity.counts_as_main("volume_fill_squat") is False
    assert session_identity.counts_as_main("technique") is False
    assert session_identity.counts_as_main("squat") is True
    assert session_identity.rotation_family("volume_fill_bench_hinge") == "bench"


def test_technique_session_can_start_and_end_empty():
    store = db.Store(":memory:")
    try:
        started = workout.start(
            store.connection, for_date="2026-10-29",
            plan={"session_type": "technique", "items": []},
            readiness=READINESS,
        )
        assert started["session_type"] == "technique"
        ended = workout.end(
            store.connection, started["workout_id"], session_rpe=None,
            not_recorded=True,
        )
        assert ended["status"] == "completed"
        assert ended["critique_id"] is None
        sessions = queries.sessions(store.connection, start="2026-10-29", end="2026-10-29")
    finally:
        store.close()
    assert list(sessions["session_type"]) == ["technique"]


def test_prescription_api_exposes_the_derived_label():
    data = prescription_dict(Prescription(
        for_date="2026-10-29", session_type="volume_fill_squat",
        fallback_level="full", rule_document_version="test", items=(),
    ))
    assert data["session_label"] == "Volume fill (squat omitted)"
    assert data["session_kind"] == "volume_fill"
    assert data["session_original_type"] == "squat"
    assert data["counts_as_main"] is False


def test_derived_types_have_no_fixed_template():
    def fail(_session_type):
        raise AssertionError("a derived type must not load a fixed template")

    assert facts_mod._template_for("volume_fill_squat", fail) is None
    assert facts_mod._template_for("technique", fail) is None