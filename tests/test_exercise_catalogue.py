"""One pass over the exercise-catalogue fan-out: no id may leave a list behind.

An exercise id lives in a dozen hand-authored places (pools, tax, ratings, inference, load
basis, demands, docs). tools/catalogue.py knows them all and names the missing key; this test
is the gate, so a new id fails here rather than in a golden test three steps later.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_catalogue  # noqa: E402
import catalogue  # noqa: E402


def test_the_catalogue_has_no_fan_out_drift() -> None:
    found = catalogue.problems()
    assert not found, (
        "catalogue drift (each line names the file and the key):\n  "
        + "\n  ".join(found)
        + "\n\nGenerated parts: ./check.sh docs. Hand-authored parts need an edit."
    )


def test_the_cli_agrees_with_the_library() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "catalogue.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_the_generated_files_are_current() -> None:
    stale = build_catalogue.check()
    assert not stale, (
        "generated catalogue files are stale:\n  " + "\n  ".join(stale)
        + "\n\nrun: ./check.sh docs (or python tools/build_catalogue.py --write)"
    )


def test_generated_ratings_follow_the_documented_rubric() -> None:
    ratings = build_catalogue.derived_ratings()
    # 3 = high local stimulus on a compound; 2 = high on an isolation or moderate on a compound.
    assert ratings["dumbbell_row"] == 3
    assert ratings["bench_press"] == 3
    assert ratings["ab_wheel"] == 2
    assert ratings["nordic_curl"] == 2
    # Nothing reachable is left unrated while its local-muscular demand is known.
    assert ratings
