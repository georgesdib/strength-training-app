"""Portability: a second athlete, a second database, the same code.

The acceptance criterion is behavioural: import, run, review and calibrate work end to end on a
database the first athlete's data never touches. Nothing personal may be tracked by git.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from conftest import make_readiness, make_training
from strength_coach import cli
from strength_coach.store import db, importer

ATHLETE_A = [
    {"Date": "2024-01-01", "Exercise": "Safety Squat Bar", "Weight_Used": "100",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Competition Bench Press", "Weight_Used": "80",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-01-01", "Exercise": "Lateral Raise", "Weight_Used": "12.5",
     "RIR": "2", "Reps_Done": "10"},
]

# A different athlete: a hinge-led day, different dates and loads, different day.
ATHLETE_B = [
    {"Date": "2024-03-01", "Exercise": "Trap Bar Deadlift", "Weight_Used": "140",
     "RIR": "3", "Reps_Done": "3"},
    {"Date": "2024-03-01", "Exercise": "Bench Press (narrow grip)", "Weight_Used": "60",
     "RIR": "2", "Reps_Done": "5"},
    {"Date": "2024-03-01", "Exercise": "Lateral Raise", "Weight_Used": "8",
     "RIR": "2", "Reps_Done": "12"},
    {"Date": "2024-03-01", "Exercise": "Split Squat", "Weight_Used": "20",
     "RIR": "3", "Reps_Done": "8"},
]


def build_db(path: Path, rows) -> None:
    training = make_training(rows)
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


def write_labels(path: Path, session_id: str) -> None:
    path.write_text(yaml.safe_dump({
        "version": 1,
        "sessions": {
            session_id: {
                "scores": {"RIR_ADHERENCE": 1.0, "ESSENTIAL_WORK": 1.0},
                "confidence": "high",
            },
        },
    }), encoding="utf-8")


def test_two_athletes_run_the_whole_loop_independently(tmp_path, capsys):
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    build_db(first, ATHLETE_A)
    build_db(second, ATHLETE_B)

    assert cli.main(["--db", str(first), "run", "--date", "2024-02-01",
                     "--session-type", "squat"]) == 0
    assert cli.main(["--db", str(second), "run", "--date", "2024-04-01",
                     "--session-type", "hinge"]) == 0

    labels_first = tmp_path / "labels-first.yaml"
    labels_second = tmp_path / "labels-second.yaml"
    write_labels(labels_first, "2024-01-01")
    write_labels(labels_second, "2024-03-01")
    assert cli.main(["--db", str(first), "review", "--session", "2024-01-01",
                     "--scores", str(labels_first)]) == 0
    assert cli.main(["--db", str(second), "review", "--session", "2024-03-01",
                     "--scores", str(labels_second)]) == 0
    assert cli.main(["--db", str(first), "calibrate"]) == 0
    assert cli.main(["--db", str(second), "calibrate"]) == 0

    with db.Store(first) as store:
        first_items = [
            row["exercise_id"] for row in store.connection.execute(
                "SELECT exercise_id FROM prescription_item"
            )
        ]
        first_dates = [
            row["for_date"] for row in store.connection.execute(
                "SELECT for_date FROM prescription"
            )
        ]
    with db.Store(second) as store:
        second_items = [
            row["exercise_id"] for row in store.connection.execute(
                "SELECT exercise_id FROM prescription_item"
            )
        ]
        second_dates = [
            row["for_date"] for row in store.connection.execute(
                "SELECT for_date FROM prescription"
            )
        ]

    assert "ssb_squat" in first_items and "ssb_squat" not in second_items
    assert "trap_bar_deadlift" in second_items and "trap_bar_deadlift" not in first_items
    assert first_dates == ["2024-02-01"]
    assert second_dates == ["2024-04-01"]


def test_the_database_path_is_the_only_switch(tmp_path, capsys):
    """Two databases from the same data produce separate artifacts, not shared ones."""
    first = tmp_path / "one.db"
    second = tmp_path / "two.db"
    build_db(first, ATHLETE_A)
    build_db(second, ATHLETE_A)

    assert cli.main(["--db", str(first), "run", "--date", "2024-02-01",
                     "--session-type", "squat"]) == 0
    with db.Store(first) as store:
        assert store.connection.execute("SELECT COUNT(*) AS c FROM prescription"
                                        ).fetchone()["c"] == 1
    with db.Store(second) as store:
        assert store.connection.execute("SELECT COUNT(*) AS c FROM prescription"
                                        ).fetchone()["c"] == 0


def test_no_personal_artifacts_are_tracked():
    repo = Path(__file__).resolve().parents[1]
    if not (repo / ".git").exists():
        pytest.skip("not a git checkout")
    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-files"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    # data/README.md is a committed placeholder describing the folder; everything else under
    # private/ or data/ is personal and must stay untracked.
    allowed = {"data/README.md"}
    leaked = [
        p for p in listed
        if p.startswith(("private/", "data/")) and p not in allowed
    ]
    assert leaked == [], f"personal paths are tracked: {leaked}"
    assert "config/llm.local.toml" not in listed

    ignore = (repo / ".gitignore").read_text(encoding="utf-8")
    for needle in ("private/", "data/", "config/llm.local.toml"):
        assert needle in ignore
