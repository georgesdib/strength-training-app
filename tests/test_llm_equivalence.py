"""V0-SCOPE §4 criterion 5: removing the model changes nothing but the narrative.

Two databases, identical history. One `run --llm off`, one `run --llm on` with a fake client.
Every persisted artifact -- critique, rubric scores, prescription, prescription items -- must be
byte-identical; the model's text may appear only in the run trace.
"""

from __future__ import annotations

import json

from conftest import make_readiness, make_training

from strength_coach import cli
from strength_coach.agents import LLMResponse
from strength_coach.store import db, importer

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5", "RIR": "2",
     "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30", "RIR": "3",
     "Reps_Done": "8"},
]


class FakeClient:
    model = "fake-1"
    available = True

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt, *, system=None):
        self.calls += 1
        return LLMResponse(text=f"narrative {self.calls}", model=self.model, tokens=11)


def populate(path) -> None:
    training = make_training(ROWS)
    readiness = make_readiness([{}])
    store = db.Store(path)
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
    finally:
        store.close()


def artifacts(path) -> dict:
    store = db.Store(path)
    try:
        conn = store.connection

        def rows(sql: str) -> list[tuple]:
            return [tuple(row) for row in conn.execute(sql)]

        return {
            "critique": rows(
                "SELECT session_id, facts_hash, narrative FROM critique ORDER BY session_id"
            ),
            "scores": rows(
                "SELECT item, score, weight, evidence_refs, rule_ids, measurable "
                "FROM rubric_score ORDER BY item"
            ),
            "prescription": rows(
                "SELECT for_date, session_type, fallback_level, rule_document_version, "
                "approved_by, calibration_ids FROM prescription"
            ),
            "items": rows(
                "SELECT order_index, exercise_id, sets, reps_low, reps_high, load_kg, "
                "rir_target, rest_s, essential, rationale_refs "
                "FROM prescription_item ORDER BY order_index"
            ),
        }
    finally:
        store.close()


def test_model_absence_changes_nothing_but_the_narrative(tmp_path, monkeypatch):
    off_path = tmp_path / "off.db"
    on_path = tmp_path / "on.db"
    populate(off_path)
    populate(on_path)

    assert cli.main(["--db", str(off_path), "run", "--date", "2024-02-01"]) == 0

    fake = FakeClient()
    monkeypatch.setattr(cli, "build_client", lambda settings=None: fake)
    assert cli.main(["--db", str(on_path), "run", "--date", "2024-02-01", "--llm", "on"]) == 0
    assert fake.calls == 2          # one narrative for the critique, one for the prescription

    assert artifacts(off_path) == artifacts(on_path)


def test_the_model_output_lives_only_in_the_trace(tmp_path, monkeypatch):
    on_path = tmp_path / "on.db"
    populate(on_path)
    fake = FakeClient()
    monkeypatch.setattr(cli, "build_client", lambda settings=None: fake)
    cli.main(["--db", str(on_path), "run", "--date", "2024-02-01", "--llm", "on"])

    store = db.Store(on_path)
    try:
        events = [
            json.loads(row["payload"])
            for row in store.connection.execute(
                "SELECT payload FROM run_event WHERE kind = 'llm_output'"
            )
        ]
        assert len(events) == 2
        assert all(event["status"] == "ok" for event in events)
        assert any(event["text"] == "narrative 1" for event in events)

        run = store.connection.execute(
            "SELECT llm_tokens FROM run ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        assert run["llm_tokens"] == 22

        # The model's prose is not in the scored artifact.
        narratives = [
            row["narrative"]
            for row in store.connection.execute("SELECT narrative FROM critique")
        ]
        assert all("narrative 1" not in (n or "") for n in narratives)
    finally:
        store.close()


def test_off_run_records_no_model_usage(tmp_path):
    off_path = tmp_path / "off.db"
    populate(off_path)
    cli.main(["--db", str(off_path), "run", "--date", "2024-02-01"])
    store = db.Store(off_path)
    try:
        count = store.connection.execute(
            "SELECT COUNT(*) AS c FROM run_event WHERE kind = 'llm_output'"
        ).fetchone()["c"]
        assert count == 0
    finally:
        store.close()
