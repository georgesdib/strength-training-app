"""Step 1 provenance: blueprint digest and nullable resolver columns."""

from __future__ import annotations

import hashlib
import json

from strength_coach.prescribe import templates
from strength_coach.store import db, repositories
from strength_coach.utils import paths


def _append(conn, prescription_id: str, **kwargs) -> str:
    run = repositories.start_run(conn, input_hash=prescription_id, code_version="test")
    return repositories.append_prescription(
        conn,
        prescription_id=prescription_id,
        run_id=run.run_id,
        for_date="2026-11-01",
        session_type="squat",
        fallback_level="full",
        rule_document_version="test",
        calibration_ids=(),
        approved_by="deterministic",
        items=[],
        **kwargs,
    )


def test_blueprint_exposes_the_file_digest() -> None:
    expected = hashlib.sha256(paths.session_types_yaml().read_bytes()).hexdigest()
    assert templates.SessionTemplate.load("squat").digest == expected
    assert len(templates.SessionTemplate.load("hinge").digest) == 64


def test_prescription_provenance_columns_exist() -> None:
    with db.Store(":memory:") as store:
        columns = {
            row["name"]
            for row in store.connection.execute("PRAGMA table_info(prescription)")
        }
    assert {
        "template_digest",
        "policy_digest",
        "input_hash",
        "generated_session_json",
    } <= columns


def test_resolver_provenance_round_trips() -> None:
    with db.Store(":memory:") as store:
        _append(
            store.connection,
            "p-resolver",
            template_digest="blueprint-digest",
            policy_digest="policy-digest",
            input_hash="input-digest",
            generated_session={"session_type": "squat", "slots": ["squat_main"]},
        )
        row = store.connection.execute(
            "SELECT template_digest, policy_digest, input_hash, generated_session_json "
            "FROM prescription WHERE prescription_id = ?",
            ("p-resolver",),
        ).fetchone()
    assert row["template_digest"] == "blueprint-digest"
    assert row["policy_digest"] == "policy-digest"
    assert row["input_hash"] == "input-digest"
    assert json.loads(row["generated_session_json"])["slots"] == ["squat_main"]


def test_fixed_path_provenance_is_null_not_backfilled() -> None:
    with db.Store(":memory:") as store:
        _append(store.connection, "p-fixed")
        row = store.connection.execute(
            "SELECT template_digest, policy_digest, input_hash, generated_session_json "
            "FROM prescription WHERE prescription_id = ?",
            ("p-fixed",),
        ).fetchone()
    assert row["template_digest"] is None
    assert row["policy_digest"] is None
    assert row["input_hash"] is None
    assert row["generated_session_json"] is None
