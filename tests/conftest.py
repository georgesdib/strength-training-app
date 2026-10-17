"""Shared fixtures.

Tests fall into two groups:

* pure unit tests that build tiny frames in memory (fast, no repo data);
* `integration` tests that read the real CSVs in `data/raw`. Those are allowed to
  be slow but must stay deterministic — they assert measured facts recorded in
  docs/EVIDENCE.md, so a silent change in cleaning shows up as a test failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def data_available() -> bool:
    from strength_coach.utils import paths

    return paths.training_log_csv().exists() and paths.readiness_csv().exists()


@pytest.fixture(scope="session")
def training_frame(data_available):
    """Real training log, raw strings, untouched by cleaning."""
    if not data_available:
        pytest.skip("raw CSVs not present")
    from strength_coach.utils import io_utils

    return io_utils.read_training_log()


@pytest.fixture(scope="session")
def readiness_frame(data_available):
    if not data_available:
        pytest.skip("raw CSVs not present")
    from strength_coach.utils import io_utils

    return io_utils.read_readiness()


def make_training(rows: list[dict]):
    """Build a raw-shaped training frame from partial rows.

    Only the fields a test cares about need to be supplied; the rest default to the export's
    own "not recorded" representation, so fixtures stay readable.
    """
    import pandas as pd

    defaults = {
        "Date": "2024-01-01",
        "Workout": "Sheiko",
        "Exercise": "Competition Squat",
        "Weight_Used": "100.0",
        "Weight_Units": "kg",
        "Reps_Done": "5",
        "RIR": "2",
        "ExertionLoad": "0.0",
        "Main_Muscle": "Quadriceps",
        "Mechanics": "Compound",
        "Force": "Push",
        "Avg_velocity": "0.000000",
        "Avg_power": "0",
        "Avg_rom": "0",
        "TUT": "0",
        "Form": "0",
        "Video": "",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged, dtype="str" if hasattr(pd, "StringDtype") else None).astype(str)


def make_readiness(rows: list[dict]):
    """Build a raw-shaped readiness frame from partial rows (Date + Weight matter most)."""
    import pandas as pd

    defaults = {
        "Date": "2024-01-01",
        "Sleep": "4",
        "Energy": "4",
        "Mood": "4",
        "Soreness": "4",
        "Stress": "4",
        "Nutrition": "4",
        "Hydration": "4",
        "Squat_Readiness": "4",
        "Bench_Readiness": "4",
        "Deadlift_Readiness": "4",
        "HRV": "0",
        "RHR": "0",
        "Weight": "80.0",
        "Fat_Percent": "20.0",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged).astype(str)
