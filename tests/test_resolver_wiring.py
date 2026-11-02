"""Step 4C: resolver dispatch into the real prescription path."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

from conftest import make_readiness, make_training

from strength_coach import settings_profile
from strength_coach.prescribe import (
    build_prescription,
    generator,
    resolver,
    templates,
)
from strength_coach.prescribe import (
    persistence as prescription_persistence,
)
from strength_coach.store import db, importer
from strength_coach.web import server

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-08", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
]


@contextmanager
def store():
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    instance = db.Store(":memory:")
    try:
        importer.import_export(
            instance.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield instance
    finally:
        instance.close()


def _pools():
    base = templates.SessionTemplate.load("squat")
    slots = tuple(slot for slot in base.slots if slot.id in {"power", "squat_main"})
    return generator.CandidatePools(
        template=replace(base, slots=slots),
        pools={
            "power": ("box_jump",),
            "squat_main": ("ssb_squat",),
        },
        main_slot=next(slot for slot in slots if slot.id == "squat_main"),
        policy_digest="p" * 64,
        catalogue_digest="c" * 64,
    )


def test_enabled_resolver_dispatches_and_attaches_provenance(monkeypatch) -> None:
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            effective_from="2024-01-01",
        )
        monkeypatch.setattr(
            resolver.generator, "candidate_pools", lambda *args, **kwargs: _pools()
        )
        prescription = build_prescription(
            instance.connection, for_date="2024-01-15", session_type="squat"
        )
    assert [item.exercise_id for item in prescription.items] == [
        "box_jump", "ssb_squat"
    ]
    metadata = prescription.notes["resolver"]
    assert metadata["assignment"]["squat_main"] == "ssb_squat"
    assert metadata["template_digest"]
    assert metadata["policy_digest"] == "p" * 64
    assert metadata["catalogue_digest"] == "c" * 64
    assert metadata["input_hash"]
    assert metadata["generated_session"]["assignment"]["squat_main"] == "ssb_squat"
    assert metadata["beam"]["best"]["feasible"] is True
    payload = server.prescription_dict(prescription)
    assert payload["generated_session"] == metadata["generated_session"]
    assert payload["policy_digest"] == "p" * 64
    assert payload["input_hash"] == metadata["input_hash"]
    with store() as instance:
        prescription_id = prescription_persistence.store_plan(instance.connection, payload)
        row = instance.connection.execute(
            "SELECT template_digest, policy_digest, input_hash, generated_session_json "
            "FROM prescription WHERE prescription_id = ?",
            (prescription_id,),
        ).fetchone()
    assert row["template_digest"] == metadata["template_digest"]
    assert row["policy_digest"] == metadata["policy_digest"]
    assert row["input_hash"] == metadata["input_hash"]
    assert row["generated_session_json"]


def test_enabled_resolver_rejects_selection_override(monkeypatch) -> None:
    with store() as instance:
        settings_profile.save(
            instance.connection,
            set_values={"resolver.enabled": True},
            effective_from="2024-01-01",
        )
        monkeypatch.setattr(
            resolver.generator, "candidate_pools", lambda *args, **kwargs: _pools()
        )
        try:
            build_prescription(
                instance.connection,
                for_date="2024-01-15",
                session_type="squat",
                apply_selection=True,
            )
        except ValueError as exc:
            assert "cannot apply selection" in str(exc)
        else:
            raise AssertionError("resolver must reject selection override")
