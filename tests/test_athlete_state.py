"""Athlete state (DATA-MODEL §11): goals, constraints, suitability, symptoms.

The acceptance criteria for this phase are about *effect*, not storage: a stored hard
constraint must veto a proposed exercise deterministically, a suitability rating must be
surfaced rather than silently ignored, and an unrecorded state must read as unknown rather
than as permission.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.prescribe import build_prescription
from strength_coach.store import db, importer, queries, repositories

ROWS = [
    {"Date": "2024-01-01", "Exercise": "Competition Deadlift", "Weight_Used": "150",
     "RIR": "2", "Reps_Done": "3"},
    {"Date": "2024-01-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "90",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5", "RIR": "2",
     "Reps_Done": "10"},
    {"Date": "2024-01-01", "Exercise": "Split Squat", "Weight_Used": "30", "RIR": "3",
     "Reps_Done": "8"},
]


@contextmanager
def store_with(rows=ROWS):
    training = make_training(rows)
    readiness = make_readiness([{}])
    store = db.Store(":memory:")
    try:
        importer.import_export(
            store.connection, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        yield store
    finally:
        store.close()


def add_profile(conn, *, goal="longevity", block_start=None):
    repositories.append_athlete_profile(
        conn,
        effective_from="2026-10-17",
        primary_goal=goal,
        goal_rank=["longevity", "strength"],
        focus_lifts=[],
        sessions_per_week_target=3,
        max_session_minutes=90,
        block_start_date=block_start,
    )


# --- storage ---------------------------------------------------------------


def test_the_five_tables_exist():
    with db.Store(":memory:") as store:
        tables = set(store.tables())
    assert {
        "athlete_profile", "athlete_constraint", "exercise_suitability",
        "metric_definition", "symptom_log",
    } <= tables


def test_latest_profile_wins_and_history_is_kept():
    with db.Store(":memory:") as store:
        conn = store.connection
        add_profile(conn, goal="strength")
        add_profile(conn, goal="longevity")
        assert queries.athlete_profile(conn)["primary_goal"] == "longevity"
        count = conn.execute("SELECT COUNT(*) c FROM athlete_profile").fetchone()["c"]
        assert count == 2

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE athlete_profile SET primary_goal = 'competition'")


def test_suitability_latest_rating_wins():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_exercise_suitability(
            conn, exercise_id="split_squat", rated_on="2024-01-01",
            can_do=True, will_do=True, feels_bad=False,
        )
        repositories.append_exercise_suitability(
            conn, exercise_id="split_squat", rated_on="2024-06-01",
            can_do=True, will_do=False, feels_bad=True,
        )
        ratings = queries.exercise_suitability(conn)
        assert ratings["split_squat"]["will_do"] == 0
        assert ratings["split_squat"]["rated_on"] == "2024-06-01"


def test_symptom_entries_are_append_only():
    with db.Store(":memory:") as store:
        conn = store.connection
        repositories.append_symptom(
            conn, logged_on="2026-10-17", timing="pre_session", region="low_back", level=0,
        )
        assert len(queries.symptom_entries(conn)) == 1
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM symptom_log")


# --- constraint effects ----------------------------------------------------


def test_hard_exclude_vetoes_the_prescription():
    with store_with() as store:
        conn = store.connection
        add_profile(conn)
        repositories.append_athlete_constraint(
            conn, kind="contraindication", region="low_back", severity="hard_exclude",
            forbidden_exercises=["trap_bar_deadlift"],
        )
        prescription = build_prescription(conn, for_date="2024-02-01")

    assert not prescription.executable
    assert any(issue.startswith("CONSTRAINT_VETO:trap_bar_deadlift") for issue in prescription.issues)


def test_a_forbidden_pattern_also_vetoes():
    with store_with() as store:
        conn = store.connection
        add_profile(conn)
        repositories.append_athlete_constraint(
            conn, kind="contraindication", region="low_back", severity="hard_exclude",
            forbidden_patterns=["hinge"],
        )
        prescription = build_prescription(conn, for_date="2024-02-01")

    assert any("CONSTRAINT_VETO" in issue for issue in prescription.issues)


def test_cannot_do_vetoes_but_will_not_do_only_warns():
    with store_with() as store:
        conn = store.connection
        add_profile(conn)
        repositories.append_exercise_suitability(
            conn, exercise_id="split_squat", rated_on="2026-10-17",
            can_do=True, will_do=False, feels_bad=False,
        )
        prescription = build_prescription(conn, for_date="2024-02-01")

    # A preference is surfaced, never silently dropped and never treated as a safety veto.
    assert prescription.executable
    assert any("split_squat" in warning for warning in prescription.warnings)


def test_unrecorded_state_reads_as_unknown_not_as_permission():
    with store_with() as store:
        prescription = build_prescription(store.connection, for_date="2024-02-01")

    assert any("athlete state not recorded" in warning for warning in prescription.warnings)
    assert prescription.notes["constraints"] == "none_recorded"


# --- CLI -------------------------------------------------------------------


def test_state_import_and_show(tmp_path, capsys):
    path = tmp_path / "coach.db"
    cli.main(["--db", str(path), "import"])
    state = tmp_path / "state.yaml"
    state.write_text(
        """
profile:
  effective_from: "2026-10-17"
  primary_goal: longevity
  goal_rank: [longevity, strength]
  sessions_per_week_target: 3
  max_session_minutes: 90
constraints:
  - kind: injury
    region: low_back
    severity: monitor
    since: "2026-06"
suitability:
  rated_on: "2026-10-17"
  exercises:
    split_squat: {can_do: true, will_do: false, feels_bad: false}
""".strip(),
        encoding="utf-8",
    )
    assert cli.main(["--db", str(path), "state", "--import", str(state)]) == 0
    out = capsys.readouterr().out
    assert "primary goal        longevity" in out
    assert "will not do         ['split_squat']" in out

    # Importing again is refused rather than silently duplicating state.
    assert cli.main(["--db", str(path), "state", "--import", str(state)]) == 2


def test_block_start_declares_week_one_and_reset_replaces_it(tmp_path, capsys):
    path = tmp_path / "coach.db"
    cli.main(["--db", str(path), "import"])
    state = tmp_path / "state.yaml"
    state.write_text(
        'profile:\n  effective_from: "2026-10-17"\n  primary_goal: longevity\n',
        encoding="utf-8",
    )
    cli.main(["--db", str(path), "state", "--import", str(state)])
    capsys.readouterr()

    assert cli.main(["--db", str(path), "block", "--date", "2026-11-02"]) == 0
    store = db.Store(path)
    try:
        assert queries.athlete_profile(store.connection)["block_start_date"] == "2026-11-02"
    finally:
        store.close()

    # A second start is refused unless it is an explicit reset.
    assert cli.main(["--db", str(path), "block", "--date", "2026-12-01"]) == 2
    assert cli.main(["--db", str(path), "block", "--date", "2026-12-01", "--force"]) == 0
    store = db.Store(path)
    try:
        assert queries.athlete_profile(store.connection)["block_start_date"] == "2026-12-01"
    finally:
        store.close()
